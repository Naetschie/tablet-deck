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
from bridge.generate import draft, generate, list_templates, load_template
from bridge.layout import validate_layout

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


if __name__ == "__main__":
    unittest.main()
