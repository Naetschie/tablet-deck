"""Unit-Tests für bridge/profiles.py (games.json, Profile, Übernahme von layout.json, Spielerkennung).

Aufruf: python -m unittest tests.test_profiles
"""
import json
import tempfile
import unittest
from pathlib import Path

from bridge.profiles import Profiles, validate_games

ROOT = Path(__file__).resolve().parent.parent


def lay(title=None, bid="a"):
    d = {"pages": [{"id": "p", "title": "P", "buttons": [{"id": bid, "label": "A", "key": "F1"}]}]}
    if title:
        d["title"] = title
    return d


def games(*entries):
    return {"games": [dict({"exe": [], "panels": [], "maps": []}, **e) for e in entries]}


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.prof_dir = self.d / "profiles"   # erst bei Bedarf angelegt (Übernahme nur ohne Ordner)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, games_data=None, legacy=None):
        gp = self.d / "games.json"
        if games_data is not None:
            gp.write_text(json.dumps(games_data), encoding="utf-8")
        lp = None
        if legacy is not None:
            lp = self.d / "layout.json"
            lp.write_text(json.dumps(legacy), encoding="utf-8")
        p = Profiles(self.prof_dir, gp, lp)
        p.migrate()
        p.load_games()
        p.scan()
        return p

    def write(self, game, panel, data):
        f = self.prof_dir / game / f"{panel}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data), encoding="utf-8")

    def test_repo_games_json_is_valid(self):
        gl = validate_games(json.loads((ROOT / "games.json").read_text(encoding="utf-8")))
        self.assertIn("star-citizen", [g["id"] for g in gl])

    def test_migrates_legacy_layout_once(self):
        p = self.make(games(), legacy=lay())
        self.assertEqual(list(p.panels), ["star-citizen/main"])
        self.assertEqual(p.panels["star-citizen/main"]["layout"]["title"], "Pilot")
        self.assertTrue((self.d / "layout.json").exists())          # Original bleibt
        (self.d / "layout.json").write_text(json.dumps(lay("Neu")), encoding="utf-8")
        self.assertFalse(p.migrate())                                # Profile vorhanden: nichts überschreiben
        p.delete("star-citizen", "main")
        self.assertFalse(p.migrate())                                # gelöscht bleibt gelöscht

    def test_panel_order_and_titles(self):
        self.write("g", "b", lay("Bergbau"))
        self.write("g", "a", lay("Alpha"))
        self.write("g", "z", lay())
        p = self.make(games({"id": "g", "name": "Spiel", "panels": ["b", "fehlt"]}))
        self.assertEqual(p.panel_ids("g"), ["b", "a", "z"])
        self.assertEqual([x["title"] for x in p.panel_list("g")], ["Bergbau", "Alpha", "z"])
        self.assertEqual(p.default_key(), "g/b")

    def test_same_button_id_in_two_panels(self):
        self.write("g", "a", lay(bid="x"))
        self.write("g", "b", lay(bid="x"))
        p = self.make(games({"id": "g", "name": "G"}))
        self.assertIn("x", p.get("g/a")["buttons"])
        self.assertIn("x", p.get("g/b")["buttons"])

    def test_broken_file_keeps_old_panel(self):
        self.write("g", "a", lay("Alt"))
        p = self.make(games({"id": "g", "name": "G"}))
        f = self.prof_dir / "g" / "a.json"
        f.write_text("{kaputt", encoding="utf-8")
        import os
        os.utime(f, (1, 1))
        self.assertEqual(p.scan(), [])
        self.assertEqual(p.get("g/a")["layout"]["title"], "Alt")

    def test_detect_running_game(self):
        p = self.make(games({"id": "sc", "name": "SC", "exe": ["StarCitizen.exe"]},
                            {"id": "fp", "name": "FP", "exe": ["Frostpunk.exe"]}))
        self.assertEqual(p.detect({"explorer.exe", "frostpunk.exe"}), "fp")
        self.assertIsNone(p.detect({"explorer.exe"}))

    def test_folders_without_entry_and_ignored_names(self):
        self.write("eigenes", "main", lay())
        (self.prof_dir / ".papierkorb").mkdir(parents=True)
        (self.prof_dir / ".papierkorb" / "g--a-1.json").write_text(json.dumps(lay()), encoding="utf-8")
        self.write("Gross", "main", lay())
        p = self.make(games())
        self.assertEqual(list(p.panels), ["eigenes/main"])
        self.assertEqual(p.game_ids(), ["eigenes"])

    def test_create_copy_delete(self):
        self.write("g", "a", lay("Alpha"))
        p = self.make(games({"id": "g", "name": "G"}))
        p.create("g", "b", "Kopie", copy_from="g/a")
        p.create("g", "c", "Leer")
        with self.assertRaises(ValueError):
            p.create("g", "a", "x")                     # nie überschreiben
        with self.assertRaises(ValueError):
            p.create("../x", "a", "x")                  # keine Pfade
        with self.assertRaises(ValueError):
            p.create("g", "main\n", "x")
        (self.prof_dir / "g" / "kaputt.json").write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            p.save("g", "kaputt", lay("Neu"), new=True)   # ungeladene Datei nie überschreiben
        p.scan()
        self.assertEqual(p.get("g/b")["layout"]["title"], "Kopie")
        self.assertIn("a", p.get("g/b")["buttons"])
        p.delete("g", "a")
        p.scan()
        self.assertNotIn("g/a", p.panels)
        self.assertTrue(list((self.prof_dir / ".papierkorb").glob("g--a-*.json")))

    def test_invalid_games(self):
        for bad in ({"games": [{"id": "Gross"}]}, {"games": [{"id": "a"}, {"id": "a"}]},
                    {"games": [{"id": "a", "exe": ["C:\\x.exe"]}]},
                    {"games": [{"id": "a", "maps": [{"name": "M", "url": "http://unsicher"}]}]},
                    {"games": [{"id": "a", "panels": ["../x"]}]}, {"games": [{"id": "a\n"}]},
                    {"games": [{"id": "a", "exe": ["x.exe\n"]}]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_games(bad)


if __name__ == "__main__":
    unittest.main()
