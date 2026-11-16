"""Unit-Tests für bridge/stats.py (Hub-Anbindung der PC-Werte): Abos, Formatumwandlung, Rückfall ohne
Sensor-Helfer, Spielziel für PresentMon. Eine Runde läuft gegen den echten Sensor-Helfer-Server (Atrappe als
Sammler, Port vom System). Braucht keine Hardware und kein Netz nach außen.

Aufruf: python -m unittest tests.test_stats
"""
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path

from bridge import stats
from bridge.sensors.server import make_server
from bridge.stats import SensorError, Stats, convert, exe_from_paths, pick_exe, read_token

TOKEN = "t" * 40


class FakeWs:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send(self, data):
        if self.fail:
            raise ConnectionError("weg")
        self.sent.append(json.loads(data))


class FakeProfiles:
    def __init__(self, names=None, folder=None):
        self.names, self.folder = names or {}, folder

    def exe_names(self, gid):
        return self.names.get(gid, [])

    def game(self, gid):
        return {"dir": self.folder} if self.folder else {}


def item(i, v, unit="%", lo=None, hi=None, name=None):
    return {"id": i, "name": name or i, "value": v, "unit": unit, "min": lo, "max": hi}


class Env(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "secrets").mkdir()
        self.key = self.root / "secrets" / "sensors.key"
        self.key.write_text(TOKEN + "\n", encoding="ascii")
        self.now = 0.0
        self.calls = []
        self.items = [item("cpu.load", 12.5, "%", 0, 100), item("ram.used", 4096, "MB", 0, 8192)]
        self.fetch_error = None
        self.posts = []
        self.post_error = None
        self.fb = [item("cpu.load", 3.0, "%", 0, 100)]

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, port, token):
        self.calls.append((port, token))
        if self.fetch_error:
            raise self.fetch_error
        return {"time": 1, "values": list(self.items), "sources": {"psutil": "ok", "lhm": "kein Admin"}}

    def post(self, port, token, exe):
        if self.post_error:
            raise self.post_error
        self.posts.append(exe)

    def make(self, profiles=None, paths=None, cfg=None):
        return Stats(self.root, cfg or {}, profiles, fetch=self.fetch, post=self.post, fallback=lambda: lambda: self.fb,
                     paths=paths, clock=lambda: self.now, retry=5.0)


class ConvertTest(unittest.TestCase):
    def test_convert(self):
        values, meta = convert([
            item("cpu.load", 12.5, "%", 0, 100, "CPU-Last"),
            {"id": "x", "value": True},                 # Wahrheitswert ist keine Zahl
            {"id": "y", "value": float("nan")},
            {"id": "z", "value": "5"},
            {"value": 1},                                # keine ID
            "müll",
            {"id": "gpu.fan1", "value": 0},              # 0 ist ein gültiger Wert
            {"id": "n", "value": 1, "name": 5, "unit": None, "min": "a", "max": 9},
        ])
        self.assertEqual(values, {"cpu.load": 12.5, "gpu.fan1": 0, "n": 1})
        self.assertEqual(meta["cpu.load"], {"name": "CPU-Last", "unit": "%", "min": 0, "max": 100})
        self.assertEqual(meta["n"], {"name": "n", "unit": "", "min": None, "max": 9})
        self.assertEqual(convert(None), ({}, {}))

    def test_pick_exe(self):
        self.assertEqual(pick_exe(["a.exe", "b.exe"], {"b.exe"}), "b.exe")
        self.assertEqual(pick_exe(["a.exe", "b.exe"], set()), "a.exe")
        self.assertEqual(pick_exe(["b.exe"], {"B.exe".lower()}), "b.exe")
        self.assertIsNone(pick_exe([], {"a.exe"}))
        # nur reine Dateinamen; nichts, was auf einer Befehlszeile stören könnte
        self.assertIsNone(pick_exe(["C:\\Spiele\\a.exe", "x/y.exe", "a.exe;calc", "a.bat", 5], None))
        self.assertEqual(pick_exe(["C:\\Spiele\\a.exe", "Star Citizen.exe"], None), "Star Citizen.exe")

    def test_exe_from_paths(self):
        paths = ["C:\\Windows\\explorer.exe", "D:\\Spiele\\Foo\\Binaries\\crashreporter.exe",
                 "D:\\Spiele\\Foo\\Binaries\\Foo-Win64-Shipping.exe", "D:\\Spiele\\Foobar\\Bar.exe"]
        self.assertEqual(exe_from_paths(paths, "D:\\Spiele\\Foo"), "Foo-Win64-Shipping.exe")
        self.assertEqual(exe_from_paths(paths, "d:/spiele/foo/"), "Foo-Win64-Shipping.exe")
        self.assertIsNone(exe_from_paths(paths, "D:\\Andere"))
        self.assertIsNone(exe_from_paths(paths, None))

    def test_read_token(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "k"
            self.assertIsNone(read_token(p))
            p.write_text("  abc \n", encoding="ascii")
            self.assertEqual(read_token(p), "abc")
            p.write_text("\n", encoding="ascii")
            self.assertIsNone(read_token(p))

    def test_port(self):
        for bad in ("8768", 80, True, None, 70000):
            self.assertEqual(Stats("x", {"sensors_port": bad}).port, 8768)
        self.assertEqual(Stats("x", {"sensors_port": 9000}).port, 9000)


class SubscriptionTest(Env):
    async def test_sub_tick_unsub(self):
        s = self.make()
        a, b = FakeWs(), FakeWs()
        s.subscribe(a)
        await s.tick()
        self.assertEqual(len(a.sent), 1)
        m = a.sent[0]
        self.assertEqual(m["t"], "stats")
        self.assertEqual(m["values"], {"cpu.load": 12.5, "ram.used": 4096})
        self.assertEqual(m["meta"]["ram.used"], {"name": "ram.used", "unit": "MB", "min": 0, "max": 8192})
        self.assertEqual(m["sources"], {"psutil": "ok", "lhm": "kein Admin"})
        self.assertEqual(self.calls, [(8768, TOKEN)])          # Token wird gelesen und benutzt
        # zweiter Durchlauf: keine Meta mehr
        await s.tick()
        self.assertNotIn("meta", a.sent[1])
        # neuer Abonnent bekommt die Meta beim ersten Mal
        s.subscribe(b)
        await s.tick()
        self.assertIn("meta", b.sent[0])
        self.assertNotIn("meta", a.sent[2])
        s.unsubscribe(a)
        await s.tick()
        self.assertEqual((len(a.sent), len(b.sent)), (3, 2))
        s.unsubscribe(a)                                         # doppeltes Abmelden schadet nicht
        s.unsubscribe(FakeWs())

    async def test_meta_resent_on_change(self):
        s = self.make()
        a = FakeWs()
        s.subscribe(a)
        await s.tick()
        await s.tick()
        self.items.append(item("gpu.temp", 40, "°C", 0, 100))
        await s.tick()
        self.assertEqual(sorted(a.sent[2]["meta"]), ["cpu.load", "gpu.temp", "ram.used"])
        await s.tick()
        self.assertNotIn("meta", a.sent[3])
        self.items[0]["value"] = 99                              # nur der Wert ändert sich: keine Meta
        await s.tick()
        self.assertNotIn("meta", a.sent[4])
        self.assertEqual(a.sent[4]["values"]["cpu.load"], 99)

    async def test_broken_client_is_dropped(self):
        s = self.make()
        ok, bad = FakeWs(), FakeWs(fail=True)
        s.subscribe(ok)
        s.subscribe(bad)
        await s.tick()
        self.assertEqual(len(ok.sent), 1)
        self.assertNotIn(bad, s.subs)
        self.assertIn(ok, s.subs)

    async def test_run_polls_only_while_subscribed(self):
        s = Stats(self.root, {}, fetch=self.fetch, post=self.post, fallback=lambda: lambda: self.fb,
                  interval=0.01, retry=0.01)
        task = asyncio.ensure_future(s.run())
        await asyncio.sleep(0.1)
        self.assertEqual(self.calls, [])                         # niemand abonniert: keine Abfrage
        a = FakeWs()
        s.subscribe(a)
        for _ in range(100):
            if len(a.sent) >= 3:
                break
            await asyncio.sleep(0.01)
        self.assertGreaterEqual(len(a.sent), 3)
        s.unsubscribe(a)
        await asyncio.sleep(0.05)
        n = len(self.calls)
        await asyncio.sleep(0.1)
        self.assertEqual(len(self.calls), n)                     # nach dem Abmelden ruht der Task wieder
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


class FallbackTest(Env):
    async def test_no_token_file_uses_fallback_and_retries_every_5s(self):
        self.key.unlink()
        s = self.make()
        a = FakeWs()
        s.subscribe(a)
        with self.assertLogs("stats", "WARNING") as cm:
            await s.tick()
        self.assertEqual(len(cm.records), 1)
        self.assertIn("kein Token", cm.output[0])
        self.assertNotIn(TOKEN, cm.output[0])
        self.assertEqual(a.sent[0]["values"], {"cpu.load": 3.0})
        self.assertEqual(a.sent[0]["sources"]["psutil"], "ok (Rückfall)")
        self.assertIn("kein Token", a.sent[0]["sources"]["sensord"])
        self.assertEqual(self.calls, [])
        # Datei erscheint, aber vor Ablauf der 5 s wird nicht erneut versucht
        self.key.write_text(TOKEN, encoding="ascii")
        self.now = 4.0
        await s.tick()
        self.assertEqual(self.calls, [])
        self.assertEqual(a.sent[1]["values"], {"cpu.load": 3.0})
        self.now = 5.1
        with self.assertLogs("stats", "INFO") as cm:
            await s.tick()
        self.assertEqual(len(self.calls), 1)
        self.assertIn("erreichbar", cm.output[0])
        self.assertEqual(a.sent[2]["values"]["ram.used"], 4096)
        self.assertEqual(a.sent[2]["meta"]["cpu.load"]["unit"], "%")

    async def test_errors_logged_only_on_state_change(self):
        s = self.make()
        s.subscribe(FakeWs())
        self.fetch_error = SensorError("nicht erreichbar")
        with self.assertLogs("stats", "WARNING") as cm:
            for t in (0, 5, 10, 15):                              # viermal dasselbe Problem: einmal loggen
                self.now = float(t)
                await s.tick()
        self.assertEqual(len(cm.records), 1)
        self.fetch_error = SensorError("Token abgelehnt", 401)    # anderer Grund: neue Meldung
        with self.assertLogs("stats", "WARNING") as cm:
            self.now = 20.0
            await s.tick()
        self.assertIn("Token abgelehnt", cm.output[0])
        self.fetch_error = None
        with self.assertLogs("stats", "INFO") as cm:
            self.now = 25.0
            await s.tick()
        self.assertEqual(len(cm.records), 1)
        self.assertEqual(s.ok, True)

    async def test_unexpected_error_does_not_break(self):
        s = self.make()
        a = FakeWs()
        s.subscribe(a)
        self.fetch_error = RuntimeError("boom")
        with self.assertLogs("stats", "WARNING"):
            await s.tick()
        self.assertEqual(a.sent[0]["values"], {"cpu.load": 3.0})

    async def test_fallback_failure_gives_empty_values(self):
        s = Stats(self.root, {}, fetch=self.fetch, post=self.post, clock=lambda: 0.0,
                  fallback=lambda: (_ for _ in ()).throw(ImportError("psutil")))
        a = FakeWs()
        s.subscribe(a)
        self.key.unlink()
        with self.assertLogs("stats", "WARNING") as cm:
            await s.tick()
            await s.tick()
        self.assertEqual(len([r for r in cm.output if "nicht lesbar" in r]), 1)   # nur einmal gemeldet
        self.assertEqual(a.sent[0]["values"], {})
        self.assertEqual(a.sent[0]["sources"]["psutil"], "Fehler")

    async def test_real_psutil_fallback_format(self):
        """Der echte Rückfall liefert dieselben IDs und Einheiten wie der Helfer."""
        try:
            import psutil  # noqa: F401
        except ImportError:
            self.skipTest("psutil fehlt")
        read = stats.psutil_fallback()
        values, meta = convert(read())
        for i in ("cpu.load", "ram.used", "ram.total"):
            self.assertIn(i, values)
        self.assertEqual(meta["cpu.load"]["unit"], "%")
        self.assertEqual(meta["ram.used"]["max"], values["ram.total"])
        values, _ = convert(read())
        self.assertIn("net.down", values)


class TargetTest(Env):
    async def settle(self, s):
        while s._bg:
            await asyncio.gather(*list(s._bg))

    async def test_game_exe_sent(self):
        prof = FakeProfiles({"sc": ["starcitizen.exe", "other.exe"]})
        s = self.make(prof)
        s.set_game("sc", {"other.exe"})
        await self.settle(s)
        self.assertEqual(self.posts, ["other.exe"])               # der laufende zuerst
        self.assertFalse(s.target_dirty)
        s.set_game(None)
        await self.settle(s)
        self.assertEqual(self.posts, ["other.exe", None])          # kein Spiel -> {}

    async def test_library_game_without_known_exe_uses_running_paths(self):
        prof = FakeProfiles({}, folder="D:\\Spiele\\Foo")
        s = self.make(prof, paths=lambda: ["D:\\Spiele\\Foo\\Bin\\Foo.exe"])
        s.set_game("foo", set())
        await self.settle(s)
        self.assertEqual(self.posts, ["Foo.exe"])

    async def test_slow_resolution_does_not_overwrite_later_switch(self):
        import threading
        gate = threading.Event()

        def slow_paths():
            gate.wait(5)                 # Auflösung für "foo" hängt im Executor
            return ["D:\\Spiele\\Foo\\Foo.exe"]
        prof = FakeProfiles({}, folder="D:\\Spiele\\Foo")
        s = self.make(prof, paths=slow_paths)
        s.set_game("foo", set())
        await asyncio.sleep(0.05)
        s.set_game(None)                 # Spiel schon wieder beendet
        await asyncio.sleep(0.05)
        gate.set()
        await self.settle(s)
        self.assertIsNone(s.target)
        self.assertEqual(self.posts, [None])

    async def test_failure_is_silent_and_retried(self):
        prof = FakeProfiles({"g": ["g.exe"]})
        s = self.make(prof)
        self.post_error = SensorError("nicht erreichbar")
        s.set_game("g", None)
        await self.settle(s)                                       # kein Fehler nach außen
        self.assertTrue(s.target_dirty)
        self.post_error = None
        a = FakeWs()
        s.subscribe(a)
        await s.tick()                                             # Helfer erreichbar -> Ziel wird nachgereicht
        self.assertEqual(self.posts, ["g.exe"])
        self.assertFalse(s.target_dirty)

    async def test_restarted_helper_gets_target_again(self):
        prof = FakeProfiles({"g": ["g.exe"]})
        s = self.make(prof)
        s.subscribe(FakeWs())
        await s.tick()
        s.set_game("g", None)
        await self.settle(s)
        self.assertEqual(self.posts, ["g.exe"])
        self.fetch_error = SensorError("nicht erreichbar")        # Helfer weg ...
        self.now = 10.0
        with self.assertLogs("stats", "WARNING"):
            await s.tick()
        self.fetch_error = None                                    # ... und wieder da
        self.now = 20.0
        with self.assertLogs("stats", "INFO"):
            await s.tick()
        self.assertEqual(self.posts, ["g.exe", "g.exe"])

    async def test_unsupported_target_is_dropped(self):
        prof = FakeProfiles({"g": ["g.exe"]})
        s = self.make(prof)
        self.post_error = SensorError("HTTP 404", 404)
        with self.assertLogs("stats", "INFO"):
            s.set_game("g", None)
            await self.settle(s)
        self.assertFalse(s.target_dirty)                           # nicht endlos wiederholen

    async def test_errors_in_profiles_do_not_propagate(self):
        class Broken:
            def exe_names(self, gid):
                raise RuntimeError("kaputt")
        s = self.make(Broken())
        with self.assertLogs("stats", "WARNING"):
            s.set_game("g", None)
            await self.settle(s)


class RoundTripTest(Env):
    """Gegen den echten Server des Sensor-Helfers (Atrappe als Sammler)."""

    def setUp(self):
        super().setUp()

        class Collector:
            def snapshot(inner):
                return {"time": 1, "values": [item("cpu.load", 7.5, "%", 0, 100)], "sources": {"psutil": "ok"}}

        class PM:
            targets = []

            def set_target(inner, t):
                inner.targets.append(t)
        self.pm = PM()
        self.server = make_server(Collector(), TOKEN, 0, self.pm)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    async def test_fetch_and_target_against_server(self):
        s = Stats(self.root, {"sensors_port": self.port}, FakeProfiles({"g": ["Spiel.exe"]}))
        a = FakeWs()
        s.subscribe(a)
        await s.tick()
        self.assertEqual(a.sent[0]["values"], {"cpu.load": 7.5})
        self.assertEqual(a.sent[0]["sources"], {"psutil": "ok"})
        self.assertTrue(s.ok)
        s.set_game("g", None)
        while s._bg:
            await asyncio.gather(*list(s._bg))
        self.assertEqual(self.pm.targets, [("exe", "Spiel.exe")])
        s.set_game(None)
        while s._bg:
            await asyncio.gather(*list(s._bg))
        self.assertEqual(self.pm.targets[-1], None)

    async def test_wrong_token_is_reported_as_such(self):
        self.key.write_text("falsch" * 8, encoding="ascii")
        s = Stats(self.root, {"sensors_port": self.port}, fallback=lambda: lambda: [])
        s.subscribe(FakeWs())
        with self.assertLogs("stats", "WARNING") as cm:
            await s.tick()
        self.assertIn("Token abgelehnt", cm.output[0])
        self.assertNotIn("falsch", cm.output[0])

    async def test_nothing_listening(self):
        self.server.shutdown()
        self.server.server_close()                                 # sonst nähme der Port Verbindungen an
        s = Stats(self.root, {"sensors_port": self.port}, fallback=lambda: lambda: [item("cpu.load", 1, "%")])
        a = FakeWs()
        s.subscribe(a)
        with self.assertLogs("stats", "WARNING") as cm:
            await s.tick()
        self.assertIn("nicht erreichbar", cm.output[0])
        self.assertEqual(a.sent[0]["values"], {"cpu.load": 1})


if __name__ == "__main__":
    unittest.main()
