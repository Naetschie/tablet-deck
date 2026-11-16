"""Unit-Tests für die App-Lautstärke in bridge/audio.py mit Attrappen (keine echte Audio-Hardware).

Aufruf: python -m unittest tests.test_audio
"""
import math
import unittest
from unittest import mock

from bridge import audio as audio_mod
from bridge.audio import Audio, mixer_changed
from bridge.pcinput import PcInput


class Vol:
    def __init__(self, v, mute=False):
        self.v, self.mute = v, mute

    def GetMasterVolume(self):
        return self.v

    def GetMute(self):
        return 1 if self.mute else 0

    def SetMasterVolume(self, v, ctx):
        self.v = v

    def SetMute(self, m, ctx):
        self.mute = bool(m)


class Proc:
    def __init__(self, name, exe=None):
        self._name, self._exe = name, exe

    def name(self):
        return self._name

    def exe(self):
        if self._exe is None:
            raise PermissionError("Zugriff verweigert")
        return self._exe


class Sess:
    def __init__(self, pid, name=None, v=0.5, mute=False, state=1, exe=None):
        self.ProcessId = pid
        self.Process = Proc(name, exe) if pid and name else None
        self.State = state
        self.SimpleAudioVolume = Vol(v, mute)


class Dev:
    def __init__(self, id, name):
        self.id, self.FriendlyName = id, name


class FakeUtil:
    def __init__(self, sessions=(), devices=(), default=None):
        self.sessions, self.devices, self.default = list(sessions), list(devices), default
        self.set_calls = []

    def GetAllSessions(self):
        return self.sessions

    def GetAllDevices(self, flow, state):
        return self.devices

    def GetSpeakers(self):
        return self.default

    def SetDefaultDevice(self, dev_id, roles):
        self.set_calls.append(dev_id)


def make(util):
    a = Audio()
    a._util = lambda: util
    return a


class SessionsTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(audio_mod, "file_description", lambda path: {"C:/a.exe": "Musik-App"}.get(path))
        p.start()
        self.addCleanup(p.stop)

    def test_zusammenfassen_je_pid(self):
        a, b = Sess(10, "chrome.exe", 0.2, True), Sess(10, "chrome.exe", 0.7, True)
        out = make(FakeUtil([a, b])).sessions()
        self.assertEqual(out, [{"k": "10", "name": "chrome", "v": 0.7, "mute": True}])
        b.SimpleAudioVolume.mute = False
        self.assertFalse(make(FakeUtil([a, b])).sessions()[0]["mute"])   # stumm nur, wenn alle stumm

    def test_systemklaenge_und_abgelaufen(self):
        sys_s = Sess(0, v=0.3)
        gone = Sess(5, "x.exe", state=audio_mod.SESSION_EXPIRED)
        orphan = Sess(77, None, v=0.1) # PID ohne Prozess -> Systemklänge
        out = make(FakeUtil([sys_s, gone, orphan])).sessions()
        self.assertEqual(out, [{"k": "sys", "name": "Systemklänge", "v": 0.3, "mute": False}])

    def test_namen(self):
        sess = [Sess(1, "Game.exe", exe="C:/g.exe"), Sess(2, "player.exe", exe="C:/a.exe"),
                Sess(3, "tool.exe"), Sess(4, "x" * 100 + ".exe")]
        out = make(FakeUtil(sess)).sessions(lambda exe: "Mein Spiel" if exe.lower() == "game.exe" else None)
        names = {x["k"]: x["name"] for x in out}
        self.assertEqual(names["1"], "Mein Spiel")          # name_for vor Beschreibung
        self.assertEqual(names["2"], "Musik-App")           # Beschreibung der exe
        self.assertEqual(names["3"], "tool")                # exe-Name ohne .exe
        self.assertEqual(len(names["4"]), 60)
        self.assertEqual([x["name"] for x in out], sorted(names.values(), key=str.lower))

    def test_set_session_klemmt_und_gilt_fuer_alle(self):
        a, b = Sess(10, "a.exe", 0.2), Sess(10, "a.exe", 0.4)
        au = make(FakeUtil([a, b]))
        self.assertTrue(au.set_session("10", v=1.7))
        self.assertEqual((a.SimpleAudioVolume.v, b.SimpleAudioVolume.v), (1.0, 1.0))
        au.set_session("10", v=-3, mute=True)
        self.assertEqual((a.SimpleAudioVolume.v, b.SimpleAudioVolume.mute), (0.0, True))
        self.assertFalse(au.set_session("999", v=0.5))      # nicht in der aktuellen Liste

    def test_fehler_liefert_none(self):
        util = FakeUtil()
        util.GetAllSessions = mock.Mock(side_effect=OSError("weg"))
        au = make(util)
        self.assertIsNone(au.sessions())
        util.GetAllDevices = mock.Mock(side_effect=OSError("weg"))
        self.assertIsNone(au.mixer())


class DevicesTest(unittest.TestCase):
    def test_set_default_nur_bekannte_ids(self):
        util = FakeUtil(devices=[Dev("a", "Lautsprecher"), Dev("b", "Headset")], default=Dev("a", "Lautsprecher"))
        au = make(util)
        au._ev = object()
        devs, default = au.devices()
        self.assertEqual((devs, default), ([{"id": "b", "name": "Headset"}, {"id": "a", "name": "Lautsprecher"}], "a"))
        self.assertFalse(au.set_default("evil"))
        self.assertEqual(util.set_calls, [])
        with mock.patch.dict("sys.modules"):   # ERole kommt aus pycaw - nur falls installiert
            self.assertTrue(au.set_default("b"))
        self.assertEqual(util.set_calls, ["b"])
        self.assertIsNone(au._ev)

    def test_abgelehntes_geraet_verschwindet_mit_hinweis(self):
        # Chat-Kanal eines Headsets: Windows/Treiber lehnt ihn als Standard-Ausgabe ab (E_FAIL)
        util = FakeUtil(devices=[Dev("a", "Lautsprecher"), Dev("c", "Kopfhörer (Communication)")],
                        default=Dev("a", "Lautsprecher"))
        util.SetDefaultDevice = mock.Mock(side_effect=OSError(-2147467259, "Unbekannter Fehler"))
        au = make(util)
        self.assertIsNone(au.set_default("c"))
        self.assertEqual([d["id"] for d in au.devices()[0]], ["a"])
        st = au.mixer()
        self.assertEqual([d["id"] for d in st["devices"]], ["a"])
        self.assertIn("Kopfhörer (Communication)", st["note"])
        self.assertFalse(au.set_default("c"))              # nicht mehr in der Liste


class ChangedTest(unittest.TestCase):
    base = {"sessions": [{"k": "1", "name": "A", "v": 0.501, "mute": False}],
            "devices": [{"id": "d", "name": "D"}], "default": "d"}

    def copy(self, **kw):
        s = {"sessions": [dict(x) for x in self.base["sessions"]], "devices": list(self.base["devices"]),
             "default": self.base["default"]}
        s.update(kw)
        return s

    def test_aenderung(self):
        self.assertTrue(mixer_changed(None, self.base))
        self.assertFalse(mixer_changed(self.base, self.copy()))
        small = self.copy()
        small["sessions"][0]["v"] = 0.504            # unter 0,01 gerundet gleich
        self.assertFalse(mixer_changed(self.base, small))
        big = self.copy()
        big["sessions"][0]["v"] = 0.52
        self.assertTrue(mixer_changed(self.base, big))
        self.assertTrue(mixer_changed(self.base, self.copy(default="x")))


class PcInputMixerTest(unittest.TestCase):
    def setUp(self):
        self.audio = mock.Mock()
        self.pc = PcInput(self.audio)
        self.st = self.pc.new_client()

    def test_gueltig(self):
        self.pc.handle(self.st, {"t": "app_volume", "k": "1234", "v": 0.4})
        self.audio.set_session.assert_called_with("1234", v=0.4)
        self.pc.handle(self.st, {"t": "app_mute", "k": "sys", "on": True})
        self.audio.set_session.assert_called_with("sys", mute=True)
        self.pc.handle(self.st, {"t": "output", "id": "{0.0.0}"})
        self.audio.set_default.assert_called_with("{0.0.0}")

    def test_ungueltig(self):
        for m in ({"t": "app_volume", "k": 12, "v": 0.4}, {"t": "app_volume", "k": "x1", "v": 0.4},
                  {"t": "app_volume", "k": "1", "v": "0.4"}, {"t": "app_volume", "k": "1", "v": True},
                  {"t": "app_volume", "k": "1", "v": math.nan}, {"t": "app_mute", "k": "1", "on": 1},
                  {"t": "output", "id": 5}, {"t": "output", "id": ""}, {"t": "output", "id": "x" * 300}):
            self.assertTrue(self.pc.handle(self.st, m))
        self.audio.set_session.assert_not_called()
        self.audio.set_default.assert_not_called()



class WorkerTest(unittest.TestCase):
    def test_ergebnis_fehler_abbrechen_daemon(self):
        import threading
        from bridge.audio import AudioWorker
        w = AudioWorker()
        self.assertEqual(w.submit(lambda: 41 + 1).result(5), 42)
        with self.assertRaises(ZeroDivisionError):
            w.submit(lambda: 1 / 0).result(5)
        gate = threading.Event()
        blocker = w.submit(lambda: gate.wait(5))
        waiting = w.submit(lambda: "nie")
        self.assertTrue(waiting.cancel())          # noch nicht gestartet: verwerfbar
        gate.set()
        blocker.result(5)
        self.assertTrue(waiting.cancelled())
        audio = [t for t in threading.enumerate() if t.name == "audio"]
        self.assertTrue(audio and all(t.daemon for t in audio))   # hält das Beenden nicht auf

if __name__ == "__main__":
    unittest.main()
