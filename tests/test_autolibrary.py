import asyncio
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
    def __init__(self, url, body=b""):
        self.url = url
        self.body = body

    def geturl(self):
        return self.url

    def read(self, n=-1):
        return self.body

    def close(self):
        pass


ER = [{"name": "Map Genie", "url": "https://mapgenie.io/elden-ring"}]


class MapGenieTest(unittest.TestCase):
    def test_slug_and_title(self):
        self.assertEqual(mapgenie.slug("S.T.A.L.K.E.R. 2: Heart of Chornobyl"), "stalker-2-heart-of-chornobyl")
        self.assertEqual(mapgenie.slug("Marvel's Spider-Man™ Remastered"), "marvels-spider-man-remastered")
        self.assertEqual(mapgenie.slug("Elden Ring"), "elden-ring")
        self.assertEqual(mapgenie.title("the-lands-between"), "The Lands Between")

    def test_parse_maps(self):
        html = ('<a href="/enshrouded/maps/embervale">x</a>'
                '<a href="https://mapgenie.io/enshrouded/maps/embervale?x=1">'
                "<a href='https://www.mapgenie.io/enshrouded/maps/the-cave/'><a href=\"/other/maps/nope\">"
                '<a href="https://evil.example/enshrouded/maps/bad"><a href="/enshrouded/maps/../x">')
        self.assertEqual(mapgenie.parse_maps("enshrouded", html), ["embervale", "the-cave"])
        many = "".join('<a href="/g/maps/m%d">' % i for i in range(40))
        self.assertEqual(len(mapgenie.parse_maps("g", many)), mapgenie.MAX_MAPS)

    def test_lookup_direct_links(self):
        with tempfile.TemporaryDirectory() as t:
            cache = Path(t) / "c.json"
            body = b'<a href="/enshrouded/maps/embervale">Embervale</a>'
            got = mapgenie.lookup("Enshrouded", cache, lambda req, timeout: FakeResp(req.full_url, body), lambda: 1.0)
            self.assertEqual(got, [{"name": "Embervale", "url": "https://mapgenie.io/enshrouded/maps/embervale"}])
            self.assertEqual(mapgenie.cached("Enshrouded", cache, lambda: 2.0), got)
            # Umleitung direkt auf eine Karte: die zählt mit
            got = mapgenie.lookup("Zelda", Path(t) / "z.json",
                                  lambda req, timeout: FakeResp("https://www.mapgenie.io/zelda/maps/hyrule"), lambda: 1.0)
            self.assertEqual([m["url"] for m in got], ["https://mapgenie.io/zelda/maps/hyrule"])

    def test_lookup_and_cache(self):
        with tempfile.TemporaryDirectory() as t:
            cache = Path(t) / "c.json"
            calls = []

            def ok(req, timeout):
                calls.append((req.full_url, timeout, req.get_header("User-agent")))
                return FakeResp(req.full_url)

            clock = [1000.0]
            now = lambda: clock[0]
            self.assertIsNone(mapgenie.cached("Elden Ring", cache, now))       # unbekannt
            self.assertEqual(mapgenie.lookup("Elden Ring", cache, ok, now), ER)  # ohne Kartenlinks: Spielseite
            self.assertEqual(calls[0][1], 5)
            self.assertIn("Mozilla", calls[0][2])
            self.assertEqual(mapgenie.lookup("Elden Ring", cache, ok, now), ER)
            self.assertEqual(len(calls), 1)                         # aus dem Zwischenspeicher
            clock[0] += mapgenie.TTL_S + 1
            self.assertIsNone(mapgenie.cached("Elden Ring", cache, now))
            mapgenie.lookup("Elden Ring", cache, ok, now)
            self.assertEqual(len(calls), 2)                         # abgelaufen

    def test_old_and_bad_cache_entries(self):
        with tempfile.TemporaryDirectory() as t:
            cache = Path(t) / "c.json"
            cache.write_text(json.dumps({
                "elden-ring": {"url": "https://mapgenie.io/elden-ring", "t": 1.0},          # altes Format
                "zelda": {"maps": [{"name": "X", "url": "https://evil.example/"}], "t": 1.0},
                "anno": {"maps": [], "t": 1.0}}))
            self.assertIsNone(mapgenie.cached("Elden Ring", cache, lambda: 2.0))
            self.assertIsNone(mapgenie.cached("Zelda", cache, lambda: 2.0))
            data = json.loads(cache.read_text())
            data["old-miss"] = {"url": None, "t": 1.0}                                    # altes "gibt es nicht"
            data["bad"] = {"maps": [{"name": "X", "url": "https://mapgenie.io/bad/maps/a/b"}], "t": 1.0}
            self.assertEqual(mapgenie.cached("Old Miss", data=data, now=lambda: 2.0), [])
            self.assertIsNone(mapgenie.cached("Bad", data=data, now=lambda: 2.0))
            self.assertEqual(mapgenie.cached("Anno", cache, lambda: 2.0), [])
            self.assertEqual(mapgenie.lookup("Elden Ring", cache, lambda req, timeout: FakeResp(req.full_url),
                                             lambda: 2.0), ER)

    def test_miss_cached_and_errors(self):
        with tempfile.TemporaryDirectory() as t:
            cache = Path(t) / "c.json"
            n = []

            def nf(req, timeout):
                n.append(1)
                raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO())

            self.assertEqual(mapgenie.lookup("Anno 1800", cache, nf, lambda: 1.0), [])
            self.assertEqual(mapgenie.lookup("Anno 1800", cache, nf, lambda: 2.0), [])
            self.assertEqual(len(n), 1)                             # Fehlschlag wird gemerkt

            def redirect(req, timeout):
                return FakeResp("https://mapgenie.io/")
            self.assertEqual(mapgenie.lookup("Other", cache, redirect, lambda: 1.0), [])
            for i, final in enumerate(["https://mapgenie.io/other-game", "https://evil.example/other",
                                       "https://mapgenie.io.evil.com/zelda", "https://mapgenie.io/zeldax"]):
                self.assertEqual(mapgenie.lookup("Zelda", Path(t) / ("c%d.json" % i),
                                                 lambda req, timeout, f=final: FakeResp(f), lambda: 1.0), [], final)

            def boom(req, timeout):
                raise urllib.error.URLError("offline")
            with self.assertRaises(urllib.error.URLError):
                mapgenie.lookup("Neu", cache, boom, lambda: 1.0)
            self.assertNotIn("neu", json.loads(cache.read_text()))  # Netzfehler nicht gemerkt


class FakeBridge:
    def __init__(self, profiles):
        self.profiles = profiles
        self.sent = []

    def maps_msg(self):
        return {"t": "maps", "games": [g["id"] for g in self.profiles.map_games()]}

    async def ctl_send(self, msg):
        self.sent.append(msg)


class MapFinderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        gp = d / "games.json"
        gp.write_text(json.dumps({"games": [{"id": "sc", "name": "Star Citizen", "exe": ["StarCitizen.exe"]}]}),
                      encoding="utf-8")
        self.p = Profiles(d / "profiles", gp)
        self.p.load_games()
        self.p.set_library([lib_entry("enshrouded", "Enshrouded", d / "e"), lib_entry("anno", "Anno", d / "a"),
                            lib_entry("elden-ring", "Elden Ring", d / "r")])
        self.b = FakeBridge(self.p)

    def tearDown(self):
        self.tmp.cleanup()

    def test_prefill_and_background_lookup(self):
        from bridge.games import MapFinder
        cache = {"Enshrouded": [{"name": "Embervale", "url": "https://mapgenie.io/enshrouded/maps/embervale"}],
                 "Anno": []}
        asked = []

        def lookup(name):
            asked.append(name)
            return [{"name": "Map Genie", "url": "https://mapgenie.io/elden-ring"}]

        f = MapFinder(self.b, lookup=lookup, cached=cache.get, pause=0)
        known, unknown = f.prefill()
        self.assertEqual(set(known), {"enshrouded", "anno"})
        self.assertEqual(unknown, ["elden-ring"])
        self.assertTrue(f.apply(known))
        self.assertFalse(f.apply(known))                               # unverändert
        self.assertIn("enshrouded", [g["id"] for g in self.p.map_games()])
        self.assertNotIn("anno", [g["id"] for g in self.p.map_games()])   # keine Karten: nicht angeboten

        async def go():
            for gid in unknown:
                f.want(gid)
            f.want("elden-ring")                                       # doppelt: nur einmal
            await f.task
        asyncio.run(go())
        self.assertEqual(asked, ["Elden Ring"])
        self.assertEqual(self.p.game("elden-ring")["maps"][0]["url"], "https://mapgenie.io/elden-ring")
        self.assertEqual(len(self.b.sent), 1)

    def test_running_game_first_and_forget(self):
        from bridge.games import MapFinder
        asked = []
        clock = [0.0]
        f = MapFinder(self.b, lookup=lambda n: asked.append(n) or [], cached=lambda n: None, pause=0,
                      clock=lambda: clock[0])

        async def go():
            f.want("enshrouded")
            f.want("anno")
            f.want("elden-ring")
            f.want("elden-ring", front=True)    # läuft gerade: vor die anderen Wartenden
            await f.task
        asyncio.run(go())
        self.assertEqual(asked, ["Elden Ring", "Enshrouded", "Anno"])
        f.forget(["anno"])                      # gerade gefragt (Zwischenspeicher fehlt): nicht erneut
        self.assertIn("anno", f.checked)
        clock[0] += mapgenie.TTL_S + 1
        f.forget(["anno"])                      # abgelaufen: darf wieder gefragt werden

        async def again():
            f.want("anno")
            f.want("enshrouded")                # nicht vergessen: bleibt geprüft
            await f.task
        asyncio.run(again())
        self.assertEqual(asked[3:], ["Anno"])

    def test_network_error_backs_off(self):
        from bridge.games import MapFinder, RETRY_S
        clock = [100.0]
        asked = []

        def lookup(name):
            asked.append(name)
            raise urllib.error.URLError("offline")

        f = MapFinder(self.b, lookup=lookup, cached=lambda n: None, pause=0, clock=lambda: clock[0])

        async def go():
            f.want("enshrouded")
            f.want("elden-ring")
            await f.task
            f.want("anno")                                             # während der Pause: nichts
        asyncio.run(go())
        self.assertEqual(asked, ["Enshrouded"])                        # nach dem ersten Fehler aufgehört
        self.assertEqual(f.queue, [])
        clock[0] += RETRY_S + 1

        async def again():
            f.want("elden-ring", front=True)
            await f.task
        asyncio.run(again())
        self.assertEqual(asked[-1], "Elden Ring")


if __name__ == "__main__":
    unittest.main()
