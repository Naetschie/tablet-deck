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


DEFAULT_XML = ('<profile><actionmap name="spaceship">'
               '<action name="v_a" keyboard="lalt+1"/><action name="v_hold" keyboard="g" activationMode="hold"/>'
               '<action name="v_none" keyboard=""/></actionmap></profile>')


def sc_lay(title="Cockpit"):
    return {"title": title, "pages": [{"id": "p", "title": "P", "buttons": [
        {"id": "a", "label": "A", "sc": "v_a", "key": "F1"}, {"id": "h", "label": "H", "sc": "v_hold", "key": "F2"},
        {"id": "n", "label": "N", "sc": "v_none", "key": "F3"}, {"id": "u", "label": "U", "sc": "v_fehlt", "key": "F4"},
        {"id": "x", "label": "X", "key": "F5"}]}]}


class BundledTest(unittest.TestCase):
    """Mitgelieferte Panels (panels/): getrennter Namensraum std--, schreibgeschützt, Kopie bearbeiten."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.prof_dir = self.d / "profiles"
        self.bun_dir = self.d / "panels"

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, games_data):
        gp = self.d / "games.json"
        gp.write_text(json.dumps(games_data), encoding="utf-8")
        p = Profiles(self.prof_dir, gp, None, bundled=self.bun_dir)
        p.load_games()
        p.scan()
        return p

    def w(self, folder, game, panel, data):
        f = folder / game / f"{panel}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data), encoding="utf-8")

    def wb(self, game, panel, data):
        self.w(self.bun_dir, game, panel, data)

    def test_namespaces_both_visible(self):
        self.w(self.prof_dir, "g", "cockpit", lay("Eigenes"))
        self.wb("g", "cockpit", lay("Mitgeliefert"))
        p = self.make(games({"id": "g", "name": "G"}))
        self.assertEqual(sorted(p.panels), ["g/cockpit", "g/std--cockpit"])
        self.assertEqual([(x["id"], x["origin"]) for x in p.panel_list("g")],
                         [("cockpit", "own"), ("std--cockpit", "bundled")])
        self.assertEqual(p.default_key("g"), "g/cockpit")          # eigenes hat als Standard Vorrang

    def test_bundled_is_fallback_default(self):
        self.wb("g", "cockpit", lay("Mitgeliefert"))
        p = self.make(games({"id": "g", "name": "G"}))
        self.assertEqual(p.default_key("g"), "g/std--cockpit")
        self.assertEqual(p.get("g/std--cockpit")["origin"], "bundled")
        self.assertEqual(p.game_ids(), ["g"])

    def test_own_cannot_use_reserved_prefix(self):
        self.w(self.prof_dir, "g", "std--x", lay())
        p = self.make(games({"id": "g", "name": "G"}))
        self.assertEqual(list(p.panels), [])
        for fn in (lambda: p.save("g", "std--x", lay()), lambda: p.create("g", "std--x", "T"),
                   lambda: p.delete("g", "std--x")):
            with self.assertRaisesRegex(ValueError, "mitgeliefert"):
                fn()

    def test_bundled_write_protected(self):
        self.wb("g", "cockpit", lay("M"))
        p = self.make(games({"id": "g", "name": "G"}))
        for fn in (lambda: p.save("g", "std--cockpit", lay("X")), lambda: p.delete("g", "std--cockpit")):
            with self.assertRaisesRegex(ValueError, "Kopie bearbeiten"):
                fn()
        self.assertTrue((self.bun_dir / "g" / "cockpit.json").is_file())

    def test_copy_bundled(self):
        self.wb("g", "cockpit", lay("Cockpit"))
        p = self.make(games({"id": "g", "name": "G"}))
        self.assertEqual(p.copy_bundled("g", "std--cockpit"), "g/cockpit-eigen")
        self.assertEqual(p.copy_bundled("g", "std--cockpit", title="Mein Ding"), "g/cockpit-eigen-2")
        self.assertEqual(p.copy_bundled("g", "std--cockpit", layout=lay("Geändert", bid="neu")), "g/cockpit-eigen-3")
        p.scan()
        self.assertEqual(p.get("g/cockpit-eigen")["layout"]["title"], "Cockpit (eigen)")
        self.assertEqual(p.get("g/cockpit-eigen-2")["layout"]["title"], "Mein Ding")
        self.assertIn("neu", p.get("g/cockpit-eigen-3")["buttons"])
        self.assertEqual(p.get("g/cockpit-eigen")["origin"], "own")
        self.assertEqual(p.panel_ids("g")[-1], "std--cockpit")
        with self.assertRaises(ValueError):
            p.copy_bundled("g", "cockpit-eigen")            # nur von mitgelieferten
        with self.assertRaises(ValueError):
            p.copy_bundled("g", "std--fehlt")
        long = "a" * 35
        self.wb("g", long, lay("L"))
        p.scan()
        self.assertLessEqual(len(p.copy_bundled("g", "std--" + long).split("/")[1]), 40)

    def test_create_from_bundled_copies(self):
        self.wb("g", "cockpit", lay("M"))
        p = self.make(games({"id": "g", "name": "G"}))
        p.create("g", "mein", "Mein", copy_from="g/std--cockpit")
        p.scan()
        self.assertEqual(p.get("g/mein")["origin"], "own")

    def test_bundled_removed(self):
        self.wb("g", "cockpit", lay("M"))
        p = self.make(games({"id": "g", "name": "G"}))
        (self.bun_dir / "g" / "cockpit.json").unlink()
        self.assertEqual(p.scan(), ["g/std--cockpit"])
        self.assertNotIn("g/std--cockpit", p.panels)

    def test_sc_keys_from_real_bindings(self):
        """Mitgeliefertes Panel: Tasten mit sc bekommen die echte Belegung, eigene Panels bleiben unberührt."""
        sc = self.d / "sc"
        sc.mkdir()
        (sc / "default.xml").write_text(DEFAULT_XML, encoding="utf-8")
        user = sc / "actionmaps.xml"
        user.write_text('<ActionMaps><ActionProfiles><actionmap name="spaceship"><action name="v_a">'
                        '<rebind input="kb1_rctrl+np_5"/></action></actionmap></ActionProfiles></ActionMaps>',
                        encoding="utf-8")
        self.wb("g", "cockpit", sc_lay())
        self.w(self.prof_dir, "g", "eigen", sc_lay("Eigen"))
        p = self.make(games({"id": "g", "name": "G", "bindings": {
            "adapter": "cryengine", "default": str(sc / "default.xml"), "user": str(user)}}))
        b = p.get("g/std--cockpit")["buttons"]
        self.assertEqual(b["a"]["key"], "RCTRL+NUMPAD5")      # eigene Belegung schlägt Standard
        self.assertEqual((b["h"]["key"], b["h"].get("hold")), ("G", True))
        self.assertEqual(b["n"]["key"], "F3")                  # unbelegt: Rückfall aus der Datei
        self.assertEqual(b["u"]["key"], "F4")                  # unbekannte Aktion: unverändert
        self.assertEqual(b["x"]["key"], "F5")                  # ohne sc: unverändert
        self.assertEqual(p.get("g/eigen")["buttons"]["a"]["key"], "F1")
        # Belegung im Spiel geändert -> mitgeliefertes Panel wird neu geladen
        import os
        user.write_text(user.read_text(encoding="utf-8").replace("np_5", "np_6"), encoding="utf-8")
        st = os.stat(user)
        os.utime(user, (st.st_atime, st.st_mtime + 5))
        self.assertEqual(p.scan(), ["g/std--cockpit"])
        self.assertEqual(p.get("g/std--cockpit")["buttons"]["a"]["key"], "RCTRL+NUMPAD6")

    def test_sc_without_readable_bindings_keeps_file_keys(self):
        self.wb("g", "cockpit", sc_lay())
        p = self.make(games({"id": "g", "name": "G", "bindings": {"adapter": "cryengine", "default": "fehlt.xml"}}))
        self.assertEqual(p.get("g/std--cockpit")["buttons"]["a"]["key"], "F1")

    def test_apply_sc_pure(self):
        from bridge import bindings
        res = bindings.Result({"v_a": bindings.Binding("X", True, ""), "v_none": bindings.Binding(None, False, "x")}, [], "")
        src = sc_lay()
        out, n = bindings.apply_sc(src, res)
        self.assertEqual(n, 2)
        self.assertEqual(src, sc_lay())                        # Eingabe unverändert
        self.assertEqual((out["pages"][0]["buttons"][0]["key"], out["pages"][0]["buttons"][0]["hold"]), ("X", True))
        self.assertEqual(out["pages"][0]["buttons"][2]["key"], "F3")


if __name__ == "__main__":
    unittest.main()
