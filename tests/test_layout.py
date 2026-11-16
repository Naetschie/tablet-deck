"""Unit-Tests für bridge/layout.py (Prüfung, atomares Speichern).

Aufruf: python -m unittest tests.test_layout
"""
import json
import tempfile
import unittest
from pathlib import Path

from bridge.layout import button_for_press, needed_keys, save_layout, validate_layout

ROOT = Path(__file__).resolve().parent.parent


def lay(**btn):
    b = {"id": "a", "label": "A"}
    b.update(btn)
    return {"pages": [{"id": "p", "title": "P", "buttons": [b]}]}


class LayoutTest(unittest.TestCase):
    def test_repo_profiles_are_valid(self):
        files = sorted((ROOT / "profiles").glob("*/*.json"))
        self.assertTrue(files)
        for f in files:
            with self.subTest(f.name):
                validate_layout(json.loads(f.read_text(encoding="utf-8")))

    def test_free_page(self):
        ok = {"pages": [{"id": "p", "title": "P", "type": "free", "cols": 4, "rows": 2, "buttons": [
            {"id": "a", "label": "A", "key": "F1", "x": 0, "y": 0, "w": 4, "h": 1},
            {"id": "b", "label": "B", "page": "q", "x": 3, "y": 1, "w": 1, "h": 1}]},
            {"id": "q", "title": "Q", "buttons": []}]}
        validate_layout(ok)
        for btn in ({"x": 1, "y": 0, "w": 4, "h": 1}, {"x": 0, "y": 2, "w": 1, "h": 1}, {"x": 0, "y": 0, "w": 0, "h": 1},
                    {"x": "0", "y": 0, "w": 1, "h": 1}, {"y": 0, "w": 1, "h": 1}):
            bad = json.loads(json.dumps(ok))
            bad["pages"][0]["buttons"][0].update(btn)
            bad["pages"][0]["buttons"][0].pop("x", None) if "x" not in btn else None
            with self.subTest(btn=btn), self.assertRaises(ValueError):
                validate_layout(bad)
        for cols, rows in ((1, 8), (17, 8), (12, 13), (12, "8")):
            bad = json.loads(json.dumps(ok))
            bad["pages"][0].update(cols=cols, rows=rows)
            with self.subTest(cols=cols, rows=rows), self.assertRaises(ValueError):
                validate_layout(bad)

    def test_page_link(self):
        validate_layout({"pages": [{"id": "p", "title": "P", "buttons": [{"id": "a", "label": "A", "page": "p"}]}]})
        for b in ({"id": "a", "label": "A", "page": "gibtsnicht"}, {"id": "a", "label": "A", "page": "p", "key": "F1"},
                  {"id": "a", "label": "A", "page": 3}, {"id": "a", "label": "A", "page": "p", "mode": "toggle"},
                  {"id": "a", "label": "A", "page": "p", "hold": True}):
            with self.subTest(b=b), self.assertRaises(ValueError):
                validate_layout({"pages": [{"id": "p", "title": "P", "buttons": [b]}]})

    def test_valid_macro(self):
        validate_layout(lay(macro=[{"key": "LALT+1"}, {"wait": 200}, {"text": "o7"}, {"media": "playpause"}]))

    def test_open(self):
        validate_layout(lay(open="https://robertsspaceindustries.com/"))
        validate_layout(lay(open=r"C:\Program Files\App\app.exe"))
        for bad in ("javascript:alert(1)", "notepad", r"\\server\share\x.exe", "C:relativ", 42, "file:///C:/x"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_layout(lay(open=bad))

    def test_rejects(self):
        bad = [
            lay(key="GIBTSNICHT"), lay(mode="explode"), lay(style="pink"),
            lay(macro=[]), lay(macro=[{"wait": 99999}]), lay(macro=[{"run": "cmd.exe"}]),
            lay(macro=[{"key": "A", "text": "x"}]), lay(macro=[{"media": "shutdown"}]),
            {"pages": []}, {"pages": [{"id": "p", "title": "P", "buttons": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]}]},
            {"pages": [{"id": "p", "title": "P", "type": "shield", "buttons": [{"id": "a", "label": "A"}]}]},
            {"holdMs": 10, "pages": [{"id": "p", "title": "P", "buttons": []}]},
        ]
        for l in bad:
            with self.assertRaises(ValueError, msg=json.dumps(l)):
                validate_layout(l)

    def test_states(self):
        st = [{"label": "FIX", "key": "LALT+G"}, {"label": "GIMBAL", "key": "LALT+H"}, {"label": "AUTO"}]
        validate_layout(lay(states=[{"label": "A", "key": "F1"}, {"label": "B", "key": "F2"}]))
        validate_layout(lay(key="F5", states=st))
        bad = [lay(states=st), lay(key="F5", states=st[:1]), lay(key="F5", states=st * 3),
               lay(key="F5", states="x"), lay(key="F5", states=[{"label": "", "key": "F1"}, {"label": "B"}]),
               lay(key="F5", states=[{"label": "x" * 21}, {"label": "B"}]),
               lay(key="F5", states=[{"label": "A", "key": "NOPE"}, {"label": "B"}]),
               lay(key="F5", states=[{"label": "A", "extra": 1}, {"label": "B"}]),
               lay(key="F5", states=st, macro=[{"wait": 1}]), lay(key="F5", states=st, open="https://x.de"),
               lay(key="F5", states=st, page="p"), lay(key="F5", states=st, mode="toggle"),
               lay(key="F5", states=st, slider={"up": "F1", "down": "F2", "steps": 5})]
        for l in bad:
            with self.subTest(l=l), self.assertRaises(ValueError):
                validate_layout(l)

    def test_slider(self):
        sl = {"up": "F1", "down": "F2", "steps": 10}
        validate_layout(lay(slider=sl))
        bad = [dict(sl, steps=1), dict(sl, steps=21), dict(sl, steps="5"), dict(sl, up="NOPE"), dict(sl, down=""),
               {"up": "F1", "steps": 5}, dict(sl, extra=1), "x"]
        for v in bad:
            with self.subTest(v=v), self.assertRaises(ValueError):
                validate_layout(lay(slider=v))
        for extra in ({"key": "F3"}, {"macro": [{"wait": 1}]}, {"open": "https://x.de"}, {"page": "p"},
                      {"states": [{"label": "A", "key": "F1"}, {"label": "B", "key": "F2"}]},
                      {"mode": "toggle"}, {"hold": True}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_layout(lay(slider=sl, **extra))

    def test_button_for_press(self):
        st = {"id": "a", "key": "F5", "states": [{"label": "A", "key": "F1"}, {"label": "B"}]}
        self.assertEqual(button_for_press(st, {"state": 0})["key"], "F1")
        for m in ({"state": 1}, {"state": 5}, {"state": -1}, {"state": "0"}, {"state": True}, {}):
            self.assertEqual(button_for_press(st, m)["key"], "F5", m)
        self.assertEqual(button_for_press({"id": "k", "key": "F9"}, {"state": 0})["key"], "F9")
        sl = {"id": "s", "slider": {"up": "F1", "down": "F2", "steps": 5}}
        self.assertEqual(button_for_press(sl, {"dir": "up"})["key"], "F1")
        self.assertEqual(button_for_press(sl, {"dir": "down"})["key"], "F2")
        for m in ({}, {"dir": "left"}, {"dir": 1}):
            self.assertIsNone(button_for_press(sl, m))
        self.assertNotIn("key", sl)   # Original bleibt unverändert
        self.assertEqual(needed_keys(sl), ["F1", "F2"])
        self.assertEqual(needed_keys(st), ["F1", "F5"])
        self.assertIsNone(needed_keys({"id": "k", "key": "F9"}))

    def test_save_atomic_and_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "layout.json"
            save_layout(p, lay(key="F1"))
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["pages"][0]["buttons"][0]["key"], "F1")
            with self.assertRaises(ValueError):
                save_layout(p, lay(key="NOPE"))
            # alte Datei unverändert, keine Reste
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["pages"][0]["buttons"][0]["key"], "F1")
            self.assertEqual([x.name for x in Path(d).iterdir()], ["layout.json"])


if __name__ == "__main__":
    unittest.main()
