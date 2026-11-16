import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from bridge import mapgenie
from bridge.profiles import Profiles, cover_type


def lib_entry(id_, name, d, steam=None, cover=None):
    return {"id": id_, "name": name, "source": "x", "dir": str(d), "steam": steam, "cover": cover}


class LibraryProfilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        gp = self.d / "games.json"
        gp.write_text(json.dumps({"games": [
            {"id": "sc", "name": "Star Citizen", "exe": ["StarCitizen.exe"], "steam": None, "panels": ["main"]},
            {"id": "hl", "name": "Half", "exe": [], "steam": 70, "panels": []}]}), encoding="utf-8")
        self.p = Profiles(self.d / "profiles", gp)
        self.p.load_games()

    def tearDown(self):
        self.tmp.cleanup()

    def test_links_and_extras(self):
        (self.d / "sc" / "Bin").mkdir(parents=True)
        (self.d / "sc" / "Bin" / "StarCitizen.exe").write_text("x")
        cov = self.d / "c.jpg"
        cov.write_bytes(b"jpg")
        self.p.set_library([
            lib_entry("rsi-launcher", "RSI", self.d / "sc", cover=str(cov)),
            lib_entry("half-life", "Half-Life", self.d / "hl", steam="70"),
            lib_entry("sc", "Fremdes", self.d / "other"),          # id kollidiert mit games.json
            lib_entry("witcher", "Witcher", self.d / "w", cover=str(cov))])
        self.assertEqual(self.p.game("sc")["cover"], str(cov))     # games.json hat Vorrang, bekommt cover
        self.assertEqual(self.p.game("sc")["name"], "Star Citizen")
        self.assertEqual(self.p.game("hl")["dir"], str(self.d / "hl"))   # per AppID
        ids = self.p.game_ids()
        self.assertEqual(ids[:2], ["sc", "hl"])
        self.assertEqual(sorted(ids[2:]), ["sc-2", "witcher"])
        s = self.p.summary("witcher")
        self.assertEqual((s["panels"], s["maps"], s["cover"]), ([], [], True))
        self.assertFalse(self.p.summary("hl")["cover"])
        self.assertTrue(self.p.is_extra("witcher"))
        self.assertFalse(self.p.is_extra("sc"))

    def test_match_library_maps_to_games_json_id(self):
        (self.d / "sc").mkdir()
        (self.d / "sc" / "StarCitizen.exe").write_text("x")
        self.p.set_library([lib_entry("rsi", "RSI", self.d / "sc"), lib_entry("w", "W", self.d / "w")])
        self.assertEqual(self.p.match_library([str(self.d / "sc" / "StarCitizen.exe")]), "sc")
        self.assertEqual(self.p.match_library([str(self.d / "w" / "bin" / "w.exe")]), "w")
        self.assertIsNone(self.p.match_library([str(self.d / "zz" / "a.exe")]))

    def test_extra_maps(self):
        self.p.set_library([lib_entry("w", "W", self.d / "w")])
        self.assertNotIn("w", [g["id"] for g in self.p.map_games()])
        self.p.set_extra_maps("w", [{"name": "Map Genie", "url": "https://mapgenie.io/w"}])
        self.assertEqual(self.p.map_games()[-1]["id"], "w")
        self.assertEqual(self.p.summary("w")["maps"][0]["name"], "Map Genie")

    def test_cover_file_checks(self):
        ok = self.d / "c.png"
        ok.write_bytes(b"png")
        bad = self.d / "c.txt"
        bad.write_text("secret")
        self.p.set_library([lib_entry("a", "A", self.d, cover=str(ok)), lib_entry("b", "B", self.d, cover=str(bad)),
                            lib_entry("c", "C", self.d, cover=str(self.d / "fehlt.jpg"))])
        self.assertEqual(self.p.cover_file("a"), (str(ok), "image/png"))
        for bad_id in ("b", "c", "unbekannt", "../a", "A", "", "a" * 41, None, "a/b"):
            self.assertIsNone(self.p.cover_file(bad_id), bad_id)
        self.assertEqual(cover_type("x.JPG"), "image/jpeg")
        self.assertIsNone(cover_type("x.exe"))


class FakeResp:
    def __init__(self, url):
        self.url = url

    def geturl(self):
        return self.url

    def close(self):
        pass


class MapGenieTest(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(mapgenie.slug("S.T.A.L.K.E.R. 2: Heart of Chornobyl"), "stalker-2-heart-of-chornobyl")
        self.assertEqual(mapgenie.slug("Marvel's Spider-Man™ Remastered"), "marvels-spider-man-remastered")
        self.assertEqual(mapgenie.slug("Elden Ring"), "elden-ring")

    def test_lookup_and_cache(self):
        with tempfile.TemporaryDirectory() as t:
            cache = Path(t) / "c.json"
            calls = []

            def ok(req, timeout):
                calls.append((req.full_url, timeout, req.get_header("User-agent")))
                return FakeResp(req.full_url)

            clock = [1000.0]
            now = lambda: clock[0]
            self.assertEqual(mapgenie.lookup("Elden Ring", cache, ok, now), "https://mapgenie.io/elden-ring")
            self.assertEqual(calls[0][1], 5)
            self.assertIn("Mozilla", calls[0][2])
            self.assertEqual(mapgenie.lookup("Elden Ring", cache, ok, now), "https://mapgenie.io/elden-ring")
            self.assertEqual(len(calls), 1)                         # aus dem Zwischenspeicher
            clock[0] += mapgenie.TTL_S + 1
            mapgenie.lookup("Elden Ring", cache, ok, now)
            self.assertEqual(len(calls), 2)                         # abgelaufen

    def test_miss_cached_and_errors(self):
        with tempfile.TemporaryDirectory() as t:
            cache = Path(t) / "c.json"
            n = []

            def nf(req, timeout):
                n.append(1)
                raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO())

            self.assertIsNone(mapgenie.lookup("Anno 1800", cache, nf, lambda: 1.0))
            self.assertIsNone(mapgenie.lookup("Anno 1800", cache, nf, lambda: 2.0))
            self.assertEqual(len(n), 1)                             # Fehlschlag wird gemerkt

            def redirect(req, timeout):
                return FakeResp("https://mapgenie.io/")
            self.assertIsNone(mapgenie.lookup("Other", cache, redirect, lambda: 1.0))
            for i, final in enumerate(["https://mapgenie.io/other-game", "https://evil.example/other",
                                       "https://mapgenie.io.evil.com/zelda", "https://mapgenie.io/zeldax"]):
                self.assertIsNone(mapgenie.lookup("Zelda%s" % ("" if i < 2 else ""), Path(t) / ("c%d.json" % i),
                                                  lambda req, timeout, f=final: FakeResp(f), lambda: 1.0))
            self.assertEqual(mapgenie.lookup("Zelda", Path(t) / "ok.json",
                                             lambda req, timeout: FakeResp("https://www.mapgenie.io/zelda/maps/x"),
                                             lambda: 1.0), "https://mapgenie.io/zelda")

            def boom(req, timeout):
                raise urllib.error.URLError("offline")
            with self.assertRaises(urllib.error.URLError):
                mapgenie.lookup("Neu", cache, boom, lambda: 1.0)
            self.assertNotIn("neu", json.loads(cache.read_text()))  # Netzfehler nicht gemerkt


if __name__ == "__main__":
    unittest.main()
