import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from bridge.profiles import Profiles, validate_maps
from bridge.usermaps import UserMaps, validate

SC = [{"name": "Ark", "url": "https://robertsspaceindustries.com/en/starmap", "heavy": True},
      {"name": "VerseGuide", "url": "https://verseguide.com/"}]


class ValidateMapsTest(unittest.TestCase):
    def test_ok_and_heavy(self):
        out = validate_maps([{"name": " A ", "url": "https://a.example/x", "heavy": False},
                             {"name": "B", "url": "https://b.example", "heavy": True}], "g")
        self.assertEqual(out, [{"name": "A", "url": "https://a.example/x"},
                               {"name": "B", "url": "https://b.example", "heavy": True}])

    def test_rejects(self):
        bad = [
            [{"name": "", "url": "https://a.example"}],
            [{"name": "x" * 61, "url": "https://a.example"}],
            [{"name": "A", "url": "http://a.example"}],
            [{"name": "A", "url": "javascript:alert(1)"}],
            [{"name": "A", "url": "https://user@evil.example/"}],
            [{"name": "A", "url": "https://a b"}],
            [{"name": "A", "url": "https://a.example\\x"}],
            [{"name": "A", "url": "https://a.example/\x00"}],
            [{"name": "A", "url": "https://a.example/x y"}],
            [{"name": "A", "url": "https://a.example/x "}],
            [{"name": "A", "url": "https://K.example/"}],
            [{"name": "A", "url": "https://:80/"}],
            [{"name": "A", "url": "https://a.example", "heavy": "ja"}],
            [{"name": "A", "url": "https://a.example"}, {"name": "B", "url": "https://a.example"}],
            [{"name": "A", "url": "https://a%d.example" % i} for i in range(31)],
            "keine Liste",
        ]
        for maps in bad:
            with self.assertRaises(ValueError, msg=repr(maps)[:80]):
                validate_maps(maps, "g")

    def test_file_validate(self):
        self.assertEqual(validate({"games": {"sc": SC}})["sc"][0]["heavy"], True)
        for data in ({"games": []}, {"games": {"../x": []}}, {"games": {"sc": [{"name": "A"}]}}, []):
            with self.assertRaises(ValueError):
                validate(data)


class UserMapsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        gp = self.d / "games.json"
        gp.write_text(json.dumps({"games": [{"id": "sc", "name": "Star Citizen", "exe": [], "maps": SC},
                                            {"id": "wh", "name": "Warhammer", "exe": [], "maps": []}]}),
                      encoding="utf-8")
        self.p = Profiles(self.d / "profiles", gp)
        self.p.load_games()
        self.p.set_library([{"id": "enshrouded", "name": "Enshrouded", "source": "x", "dir": str(self.d / "e")}])
        self.p.set_extra_maps("enshrouded", [{"name": "Embervale", "url": "https://mapgenie.io/enshrouded/maps/embervale"}])
        self.u = UserMaps(self.d / "maps.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_override_and_reset(self):
        self.assertFalse(self.u.load())                      # Datei fehlt: nichts
        own = [{"name": "Eigene", "url": "https://example.org/map"}]
        self.u.set("sc", own)
        self.u.set("enshrouded", [])
        self.p.user_maps = self.u.maps
        self.assertEqual(self.p.game("sc")["maps"], own)
        self.assertEqual(self.p.default_maps("sc"), validate_maps(SC, "sc"))
        self.assertEqual(self.p.game("enshrouded")["maps"], [])
        ids = [g["id"] for g in self.p.map_games()]
        self.assertIn("sc", ids)
        self.assertNotIn("enshrouded", ids)                  # eigene leere Liste: nicht angeboten
        saved = json.loads((self.d / "maps.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["games"]["sc"], own)
        self.u.set("enshrouded", None)
        self.p.user_maps = self.u.maps
        self.assertIn("enshrouded", [g["id"] for g in self.p.map_games()])   # wieder Map Genie
        self.assertEqual(self.p.game("enshrouded")["maps"][0]["name"], "Embervale")

    def test_reload_and_broken_file(self):
        f = self.d / "maps.json"
        f.write_text(json.dumps({"games": {"wh": [{"name": "X", "url": "https://x.example"}]}}), encoding="utf-8")
        self.assertTrue(self.u.load())
        self.assertFalse(self.u.load())                      # unverändert
        import os
        f.write_text("{kaputt", encoding="utf-8")
        os.utime(f, (1, 1))
        self.assertFalse(self.u.load())
        self.assertIn("wh", self.u.maps)                     # alte Listen bleiben
        self.u.set("wh", [{"name": "X", "url": "https://x.example"}])   # unverändert, aber Datei kaputt: ersetzen
        self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["games"]["wh"][0]["name"], "X")
        f.unlink()
        self.assertTrue(self.u.load())
        self.assertEqual(self.u.maps, {})

    def test_set_rejects(self):
        with self.assertRaises(ValueError):
            self.u.set("../x", [])
        with self.assertRaises(ValueError):
            self.u.set("sc", [{"name": "A", "url": "http://a"}])
        self.assertFalse((self.d / "maps.json").exists())   # nichts geschrieben
        self.u.set("sc", None)                               # nichts zu entfernen: keine Datei anlegen
        self.assertFalse((self.d / "maps.json").exists())


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))


class FakeEditBridge:
    """Minimaler Hub für maps_edit (nur die benutzten Teile)."""

    def __init__(self, profiles, user_maps):
        from bridge.__main__ import Bridge
        self.profiles, self.user_maps, self.game = profiles, user_maps, "sc"
        self.tiles = [{"id": "maps", "type": "maps"}]
        self.sent = []
        self.tab = FakeWs()
        self.ctl_device = {self.tab: "TAB1"}
        self.tiles_for = lambda dev: self.tiles
        self.maps_list = Bridge.maps_list.__get__(self)
        self.maps_edit = Bridge.maps_edit.__get__(self)
        self.maps_msg = Bridge.maps_msg.__get__(self)

    async def ctl_send(self, msg):
        self.sent.append(msg)


class MapsEditTest(unittest.TestCase):
    setUp = UserMapsTest.setUp
    tearDown = UserMapsTest.tearDown

    def test_edit_messages(self):
        b = FakeEditBridge(self.p, self.u)
        run = lambda m: asyncio.run(b.maps_edit(m))
        lst = run({"t": "maps_list"})
        sc = next(g for g in lst["games"] if g["id"] == "sc")
        self.assertEqual((sc["custom"], sc["source"], lst["current"]), (False, "games", "sc"))
        self.assertEqual(next(g for g in lst["games"] if g["id"] == "enshrouded")["source"], "library")
        own = [{"name": "Eigene", "url": "https://example.org/map"}]
        r = run({"t": "maps_save", "game": "sc", "maps": own})
        self.assertEqual(r["saved"], "sc")
        self.assertTrue(next(g for g in r["games"] if g["id"] == "sc")["custom"])
        self.assertEqual(b.sent[-1]["t"], "maps")
        self.assertEqual(next(g for g in b.sent[-1]["games"] if g["id"] == "sc")["maps"], own)
        run({"t": "maps_show", "game": "sc", "url": own[0]["url"]})
        self.assertEqual(b.tab.sent[-1], {"t": "map_show", "game": "sc", "url": own[0]["url"]})
        with self.assertRaises(ValueError):                  # maps fehlt: nicht wie Zurücksetzen behandeln
            run({"t": "maps_save", "game": "sc"})
        self.assertTrue(self.u.maps.get("sc"))
        with self.assertRaises(ValueError):                  # nicht gespeicherte Adresse
            run({"t": "maps_show", "game": "sc", "url": "https://evil.example/"})
        with self.assertRaises(ValueError):
            run({"t": "maps_save", "game": "unbekannt", "maps": own})
        run({"t": "maps_reset", "game": "sc"})
        self.assertFalse(next(g for g in run({"t": "maps_list"})["games"] if g["id"] == "sc")["custom"])
        b.tiles = []
        with self.assertRaises(ValueError):                  # keine Karten-Kachel
            run({"t": "maps_show", "game": "sc", "url": SC[1]["url"]})
        b.tiles = [{"id": "maps", "type": "maps"}]
        b.ctl_device = {}
        with self.assertRaises(ValueError):                  # kein Tablet verbunden
            run({"t": "maps_show", "game": "sc", "url": SC[1]["url"]})

    def test_lookup_error_is_message(self):
        import http.client
        from unittest import mock
        b = FakeEditBridge(self.p, self.u)
        with mock.patch("bridge.mapgenie.lookup", side_effect=http.client.IncompleteRead(b"")):
            with self.assertRaises(ValueError):
                asyncio.run(b.maps_edit({"t": "maps_lookup", "game": "sc"}))


if __name__ == "__main__":
    unittest.main()
