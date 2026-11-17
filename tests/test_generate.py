"""Unit-Tests für Panel-Generator und Belegungs-Adapter (bridge/generate.py, bridge/bindings/).

Aufruf: python -m unittest tests.test_generate
"""
import json
import tempfile
import unittest
from pathlib import Path

from bridge import bindings
from bridge.bindings import Binding, Result
from bridge.bindings.cryengine import key_to_sc, sc_to_key
from bridge.generate import actions, actions_message, draft, generate, list_templates, load_template
from bridge.layout import validate_layout


def setUpModule():
    # Tests durchsuchen nie die echten Spielordner des Rechners (generischer Rückfall: bindings/scan.py)
    import unittest.mock as um
    from bridge.bindings import scan
    global _no_scan
    _no_scan = [um.patch("bridge.generate.library_entry", lambda gi: {}),
                um.patch.object(scan, "search", lambda *a, **k: scan.Found("none", message=scan.STATE_TEXT["none"]))]
    for p in _no_scan:
        p.start()


def tearDownModule():
    for p in _no_scan:
        p.stop()

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_XML = """<profile><actionmap name="spaceship_general">
  <action name="v_flightready" keyboard="ralt+r"/>
  <action name="v_lights" keyboard="l"/>
  <action name="v_fire" keyboard="mouse1"/>
  <action name="v_boost" keyboard="b" activationMode="hold"/>
  <action name="v_double" keyboard="x" activationMode="double_tap"/>
  <action name="v_empty" keyboard=" "/>
</actionmap></profile>"""
USER_XML = """<ActionMaps><ActionProfiles><actionmap name="spaceship_general">
  <action name="v_lights"><rebind input="kb1_lalt+l"/></action>
  <action name="v_empty"><rebind input="kb1_np_5"/></action>
</actionmap></ActionProfiles></ActionMaps>"""


def tpl(*buttons):
    return {"title": "T", "pages": [{"id": "p1", "title": "Eins", "buttons": list(buttons)},
                                    {"id": "p2", "title": "Zwei", "buttons": [{"id": "z", "label": "Z"}]}]}


class CryengineTest(unittest.TestCase):
    def test_sc_key_roundtrip(self):
        self.assertEqual(sc_to_key("lalt+np_5"), "LALT+NUMPAD5")
        self.assertIsNone(sc_to_key("mouse1"))
        self.assertEqual(key_to_sc("RCTRL+NUMPAD1"), "rctrl+np_1")

    def test_read_default_plus_user(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "def.xml").write_text(DEFAULT_XML, encoding="utf-8")
            (Path(d) / "user.xml").write_text(USER_XML, encoding="utf-8")
            r = bindings.read({"adapter": "cryengine", "default": "def.xml", "user": str(Path(d) / "user.xml")}, d)
        b = r.bindings
        self.assertEqual(b["v_flightready"].key, "RALT+R")
        self.assertEqual(b["v_lights"].key, "LALT+L")          # eigene Belegung gewinnt
        self.assertEqual(b["v_empty"].key, "NUMPAD5")
        self.assertTrue(b["v_boost"].hold)
        self.assertIsNone(b["v_fire"].key)
        self.assertIn("Maus", b["v_fire"].note)
        self.assertIsNone(b["v_double"].key)
        self.assertIn("Doppeltipp", b["v_double"].note)
        self.assertNotIn("LALT+L", r.free)

    def test_missing_default_profile(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(FileNotFoundError):
            bindings.read({"adapter": "cryengine", "default": "fehlt.xml"}, d)

    def test_unknown_adapter(self):
        with self.assertRaises(ValueError):
            bindings.read({"adapter": "gibtsnicht"}, ".")


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.res = Result({"a_bound": Binding("F1", False, ""), "a_hold": Binding("F2", True, ""),
                           "a_mouse": Binding(None, False, "nur Maus/Achse (mouse1)")},
                          ["RCTRL+NUMPAD1", "RCTRL+NUMPAD2"], "test")

    def test_template_bindings_fallback(self):
        from bridge.generate import template_bindings
        r = template_bindings(str(Path(__file__).resolve().parent.parent), "stalker2")
        self.assertGreaterEqual(len(r.bindings), 10)
        self.assertTrue(all(b.key for b in r.bindings.values()))         # nur Aktionen mit Taste
        self.assertIn("Vorlage", r.source)
        self.assertIsNone(template_bindings(str(Path(__file__).resolve().parent.parent), "gibtsnicht"))

    def test_filter_spec_sections_and_device(self):
        from bridge.generate import filter_spec
        spec = {"sections": [
            {"title": "A", "areas": [{"title": "X", "items": [
                {"label": "J", "action": "on_js"}, {"label": "K", "action": "kb"},
                {"pair": [{"label": "P", "action": "on_js"}, {"label": "P", "action": "kb2"}]},
                {"pair": [{"label": "Q", "action": "on_js"}, {"label": "Q", "action": "on_js2"}]}]},
                {"title": "Nur Joystick", "items": [{"label": "J2", "action": "on_js2"}]},
                {"title": "Schilde", "shield": {"front": {"label": "V", "action": "on_js"}}}]},
            {"title": "B", "areas": [{"title": "Y", "items": [{"label": "Z", "action": "z"}]}]}]}
        out, dropped = filter_spec(spec, ["A"], frozenset({"on_js", "on_js2"}))
        self.assertEqual([s["title"] for s in out["sections"]], ["A"])
        areas = out["sections"][0]["areas"]
        self.assertEqual([a["title"] for a in areas], ["X", "Schilde"])          # leerer Bereich fällt weg, Schiff bleibt
        self.assertEqual(len(areas[0]["items"]), 2)                               # K und das gemischte Paar
        self.assertEqual(sorted(d["label"] for d in dropped), ["J", "J2", "Q", "Q"])
        self.assertEqual(len(spec["sections"][0]["areas"][0]["items"]), 4)       # Eingabe unverändert
        with self.assertRaises(ValueError):
            filter_spec(spec, ["gibtsnicht"])

    def test_semantic_template_press_ms_and_no_decor_rows(self):
        from bridge.autolayout import build
        spec = {"sections": [{"title": "S", "areas": [
            {"title": "A", "items": [{"label": "Lang", "action": "a_long"}, {"label": "Kurz", "action": "a_bound"}]}]}]}
        res = Result({"a_long": Binding("N", False, "", 350), "a_bound": Binding("F1", False, "")}, [], "t")
        layout, report = generate(build(spec), res)
        btn = {b["label"]: b for b in layout["pages"][0]["buttons"] if "kind" not in b}
        self.assertEqual((btn["Lang"]["key"], btn["Lang"]["press_ms"]), ("N", 350))
        self.assertNotIn("press_ms", btn["Kurz"])
        self.assertEqual(sorted(r["label"] for r in report), ["Kurz", "Lang"])   # Rahmen nicht im Bericht

    def test_priority_binding_template_missing(self):
        t = tpl({"id": "b1", "label": "B1", "sc": "a_bound", "key": "Q"},
                {"id": "b2", "label": "B2", "action": "a_hold"},
                {"id": "b3", "label": "B3", "sc": "a_mouse", "key": "Q"},
                {"id": "b4", "label": "B4", "sc": "a_unknown", "key": "W"},
                {"id": "b5", "label": "B5", "sc": "a_unknown2"},
                {"id": "b6", "label": "B6", "macro": [{"text": "o7"}]})
        lay, rep = generate(t, self.res)
        by = {r["id"]: r for r in rep}
        btn = {b["id"]: b for b in lay["pages"][0]["buttons"]}
        self.assertEqual((btn["b1"]["key"], by["b1"]["source"]), ("F1", "Belegung"))
        self.assertTrue(btn["b2"]["hold"])
        self.assertNotIn("key", btn["b3"])                      # Maus-Belegung: Vorlagentaste nicht nutzen
        self.assertEqual(by["b3"]["source"], "fehlt")
        self.assertEqual(by["b3"]["suggest"], "RCTRL+NUMPAD1")
        self.assertEqual((btn["b4"]["key"], by["b4"]["source"]), ("W", "Vorlage"))
        self.assertEqual(by["b5"]["suggest"], "RCTRL+NUMPAD2")
        self.assertEqual(by["b6"]["source"], "Makro")
        validate_layout(lay)

    def test_without_bindings_uses_template_keys(self):
        lay, rep = generate(tpl({"id": "b1", "label": "B1", "action": "x", "key": "F5"}))
        self.assertEqual(lay["pages"][0]["buttons"][0]["key"], "F5")
        self.assertEqual(rep[0]["source"], "Vorlage")

    def test_page_filter_and_template_untouched(self):
        t = tpl({"id": "b1", "label": "B1", "sc": "a_bound"})
        lay, rep = generate(t, self.res, pages=["p2"])
        self.assertEqual([p["id"] for p in lay["pages"]], ["p2"])
        self.assertEqual({r["page_id"] for r in rep}, {"p2"})
        self.assertNotIn("key", t["pages"][0]["buttons"][0])   # Vorlage nicht verändert
        with self.assertRaises(ValueError):
            generate(t, self.res, pages=[])

    def test_repo_templates_are_valid(self):
        dirs = [d for d in (ROOT / "templates").iterdir() if d.is_dir()]
        self.assertTrue(dirs)
        for d in dirs:
            listed = list_templates(ROOT, d.name)
            self.assertEqual(len(listed), len(list(d.glob("*.json"))), d.name)
            for t in listed:
                load_template(ROOT, d.name, t["id"])

    def test_template_ids_are_checked(self):
        self.assertEqual(list_templates(ROOT, "../x"), [])
        with self.assertRaises(ValueError):
            load_template(ROOT, "star-citizen", "../../games")

    def test_draft_with_unreadable_bindings_falls_back(self):
        entry = {"id": "star-citizen", "bindings": {"adapter": "cryengine", "default": "fehlt/gibtsnicht.xml"}}
        lay, rep, src = draft(ROOT, entry, "bergbau")
        self.assertIn("nicht lesbar", src)
        self.assertTrue(lay["pages"])


class ActionsTest(unittest.TestCase):
    """Palette des Panel-Editors: Spielaktionen aus den Vorlagen mit der Taste aus der eigenen Belegung."""

    def make_root(self, d):
        root = Path(d)
        (root / "templates" / "spiel").mkdir(parents=True)
        t = {"title": "Vorlage", "pages": [
            {"id": "p1", "title": "Eins", "type": "grid", "buttons": [
                {"id": "a", "label": "A", "sc": "v_flightready", "group": "Schiff", "wide": True},
                {"id": "b", "label": "B", "sc": "v_fire", "key": "Q", "group": "Waffen"},
                {"id": "m", "label": "M", "macro": [{"text": "o7"}]},
                {"id": "link", "label": "L", "page": "p2"}]},
            {"id": "p2", "title": "Frei", "type": "free", "cols": 4, "rows": 2, "buttons": [
                {"id": "c", "label": "C", "sc": "v_lights", "x": 0, "y": 0, "w": 2, "h": 1, "mode": "toggle"}]},
            {"id": "leer", "title": "Nur Link", "type": "grid", "buttons": [{"id": "l2", "label": "L2", "page": "p1"}]}]}
        (root / "templates" / "spiel" / "vorlage.json").write_text(json.dumps(t), encoding="utf-8")
        (root / "def.xml").write_text(DEFAULT_XML, encoding="utf-8")
        return root

    def test_actions_use_binding_and_strip_position(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.make_root(d)
            entry = {"id": "spiel", "bindings": {"adapter": "cryengine", "default": "def.xml"}}
            tpls, source = actions(root, entry)
        self.assertEqual(len(tpls), 1)
        self.assertEqual([p["id"] for p in tpls[0]["pages"]], ["p1", "p2"])    # Seite nur mit Link entfällt
        a = {x["button"]["id"]: x for p in tpls[0]["pages"] for x in p["actions"]}
        self.assertNotIn("link", a)                                           # Seiten-Link entfällt
        self.assertEqual((a["a"]["key"], a["a"]["source"], a["a"]["group"]), ("RALT+R", "Belegung", "Schiff"))
        self.assertEqual(a["a"]["button"]["key"], "RALT+R")
        self.assertEqual(a["b"]["source"], "fehlt")                           # Maus-Belegung: Vorlagentaste gilt nicht
        self.assertNotIn("key", a["b"]["button"])
        self.assertEqual(a["m"]["source"], "Makro")
        self.assertEqual(a["c"]["button"]["mode"], "toggle")
        for x in a.values():
            for k in ("x", "y", "w", "h", "zone", "wide", "group"):
                self.assertNotIn(k, x["button"])
        self.assertTrue(source)

    def test_actions_buttons_are_valid_when_added_to_a_panel(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.make_root(d)
            tpls, _ = actions(root, {"id": "spiel"})
        buttons = [x["button"] for p in tpls[0]["pages"] for x in p["actions"]]
        validate_layout({"pages": [{"id": "x", "title": "X", "buttons": buttons}]})

    def test_actions_without_bindings_and_without_templates(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.make_root(d)
            tpls, source = actions(root, {"id": "spiel"})
            self.assertIn("keine Steuerungsdatei", source)   # Rückfall-Suche fand nichts
            self.assertEqual(tpls[0]["pages"][0]["actions"][1]["source"], "Vorlage")     # Taste Q aus der Vorlage
            self.assertEqual(actions(root, {"id": "gibtsnicht"}), ([], source))

    def test_actions_message(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.make_root(d)
            m = actions_message(root, {"id": "spiel"})
            json.dumps(m)
        self.assertEqual((m["t"], m["game"], m["bindings"]), ("actions", "spiel", False))
        self.assertEqual(m["templates"][0]["title"], "Vorlage")

    def test_repo_templates_all_give_valid_actions(self):
        for d in (ROOT / "templates").iterdir():
            tpls, _ = actions(ROOT, {"id": d.name})
            self.assertTrue(tpls, d.name)
            for t in tpls:
                for p in t["pages"]:
                    validate_layout({"pages": [{"id": "x", "title": "X", "buttons": [a["button"] for a in p["actions"]]}]})


if __name__ == "__main__":
    unittest.main()
