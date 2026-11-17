"""Tests für die Cockpit-Bausteine des Panel-Formats (Plan v4, Schritt 1): frame/text, look, mode double,
segment, section, Raster bis 24 x 16 sowie das Demo-Panel docs/beispiele/cockpit-demo.json.

Aufruf: python -m unittest tests.test_layout_cockpit
"""
import json
import unittest
from pathlib import Path

from bridge.layout import button_for_press, needed_keys, validate_layout

ROOT = Path(__file__).resolve().parent.parent


def free(*buttons, cols=24, rows=16, **page):
    p = {"id": "p", "title": "P", "type": "free", "cols": cols, "rows": rows, "buttons": list(buttons)}
    p.update(page)
    return {"pages": [p]}


def key(**kw):
    b = {"id": "a", "label": "A", "key": "F1", "x": 0, "y": 0, "w": 2, "h": 2}
    b.update(kw)
    for k in [k for k, v in b.items() if v is None]:
        del b[k]
    return b


def bad(testcase, layout):
    with testcase.assertRaises(ValueError):
        validate_layout(layout)


class CockpitTest(unittest.TestCase):
    def test_press_ms(self):
        validate_layout(free(key(press_ms=350)))
        for v in (0, 49, 3001, "350", 1.5, True):
            bad(self, free(key(press_ms=v)))

    def test_shield_element(self):
        sh = {"kind": "shield", "id": "sh", "x": 0, "y": 0, "w": 6, "h": 4}
        z = lambda zid, zone, **kw: dict({"id": zid, "label": zid, "key": "F1", "zone": zone}, **kw)
        btns = validate_layout(free(sh, z("v", "front"), z("h", "back"), z("r", "reset"), key(x=8)))
        self.assertEqual(set(btns), {"v", "h", "r", "a"})                      # Zonen sind normale Tasten
        bad(self, free(z("v", "front")))                                       # Zone ohne shield
        bad(self, free(sh, dict(sh, id="sh2"), z("v", "front")))               # zwei shields
        bad(self, free(sh, z("v", "front"), z("w", "front")))                  # Zone doppelt
        bad(self, free(sh, z("v", "top")))                                     # top/bottom nur auf Schild-Seiten
        bad(self, free(sh, z("v", "front", x=0, y=0, w=1, h=1)))               # Zone ohne Position
        bad(self, free(sh, z("v", "front", look="big")))
        bad(self, free(dict(sh, label="Schilde")))                             # shield ohne Titel (dafür frame)
        bad(self, {"pages": [{"id": "p", "title": "P", "buttons": [sh]}]})     # nur auf freien Seiten

    def test_lists_instead_of_text_are_value_errors(self):
        # handgeschriebene Panels: Listen/Zahlen in Auswahlfeldern -> Fehlermeldung statt TypeError
        bad(self, free({"kind": ["frame"], "id": "f", "x": 0, "y": 0, "w": 2, "h": 2}))
        bad(self, free(key(look=["big"])))
        bad(self, free(key(look="arrow", dir=["up"])))
        bad(self, free(key(mode=["tap"])))
        bad(self, free(key(style=1)))
        bad(self, free({"kind": "text", "id": "t", "label": "T", "align": ["left"], "x": 0, "y": 0, "w": 2, "h": 1}))

    def test_grid_up_to_24x16(self):
        validate_layout(free(key(x=22, y=14), cols=24, rows=16))
        for cols, rows in ((25, 8), (12, 17)):
            bad(self, free(key(), cols=cols, rows=rows))
        validate_layout({"pages": [{"id": "p", "title": "P", "type": "free", "buttons": [key(x=10, y=6)]}]})
        bad(self, {"pages": [{"id": "p", "title": "P", "type": "free", "buttons": [key(x=11, y=0)]}]})   # 12 x 8

    def test_frame_and_text(self):
        lay = free({"kind": "frame", "id": "f", "label": "Landing", "x": 0, "y": 0, "w": 8, "h": 6},
                   {"kind": "frame", "id": "f2", "x": 8, "y": 0, "w": 4, "h": 4},
                   {"kind": "text", "id": "t", "label": "Hinweis", "x": 0, "y": 6, "w": 4, "h": 1,
                    "align": "center", "size": "l"},
                   key())
        buttons = validate_layout(lay)
        self.assertEqual(list(buttons), ["a"])   # frame/text sind keine Tasten (Hub kennt sie nicht)

    def test_frame_and_text_invalid(self):
        f = {"kind": "frame", "id": "f", "label": "L", "x": 0, "y": 0, "w": 4, "h": 4}
        t = {"kind": "text", "id": "t", "label": "T", "x": 0, "y": 0, "w": 4, "h": 1}
        for extra in ({"key": "F1"}, {"mode": "tap"}, {"style": "danger"}, {"look": "pill"}, {"align": "left"}):
            with self.subTest(frame=extra):
                bad(self, free(dict(f, **extra)))
        for extra in ({"key": "F1"}, {"align": "mitte"}, {"size": "xl"}, {"label": ""}, {"label": "  "},
                      {"label": "x" * 121}):
            with self.subTest(text=extra):
                bad(self, free(dict(t, **extra)))
        bad(self, free(dict(f, kind="icon")))
        bad(self, free(dict(f, label="x" * 41)))
        bad(self, free(dict(f, label=5)))
        bad(self, free(dict(f, x=20, w=8)))                 # außerhalb des Rasters
        bad(self, free(dict(f), dict(t, id="f")))            # id doppelt
        bad(self, free(dict(f), key(id="f")))
        bad(self, free(key(id="f"), dict(f)))
        # nur auf free-Seiten
        for ptype in ("grid", "shield"):
            with self.subTest(page=ptype):
                bad(self, {"pages": [{"id": "p", "title": "P", "type": ptype, "buttons": [dict(f)]}]})
        bad(self, {"pages": [{"id": "p", "title": "P", "buttons": [dict(t)]}]})

    def test_look(self):
        for look, extra in (("big", {}), ("pill", {}), ("arrow", {"dir": "up2"}), ("pill", {"mode": "toggle"}),
                            ("big", {"mode": "hold-confirm", "style": "danger"})):
            with self.subTest(look=look, extra=extra):
                validate_layout(free(key(look=look, **extra)))
        for d in ("up", "down", "left", "right", "up2", "down2"):
            validate_layout(free(key(look="arrow", dir=d)))
        bad(self, free(key(look="rund")))
        bad(self, free(key(look="switch")))                     # Kippschalter wieder entfernt (zeigten keinen Zustand)
        bad(self, free(key(look="arrow")))                       # dir fehlt
        bad(self, free(key(look="arrow", dir="oben")))
        bad(self, free(key(look="pill", dir="up")))              # dir nur mit arrow
        bad(self, free(key(dir="up")))
        bad(self, free(key(look="big", states=[{"label": "A"}, {"label": "B"}])))
        bad(self, free(key(look="big", slider={"up": "F1", "down": "F2", "steps": 5}, key=None)))
        bad(self, free(key(look="pill", key=None,
                           segment=[{"label": "A", "key": "F1"}, {"label": "B", "key": "F2"}])))

    def test_mode_double(self):
        validate_layout(free(key(mode="double", style="danger")))
        validate_layout(free(key(mode="double", hold=True)))
        validate_layout(free(key(mode="double", macro=[{"key": "F1"}], key=None)))
        bad(self, free(key(mode="dreifach")))
        # wie hold-confirm: nicht mit states/slider/page/segment
        bad(self, free(key(mode="double", states=[{"label": "A"}, {"label": "B"}])))
        bad(self, free(key(mode="double", page="p", key=None)))

    def test_segment(self):
        seg = [{"label": "ALLE", "key": "F1"}, {"label": "FEINDE", "key": "F2"}]
        b = {"id": "s", "label": "Ziele", "segment": seg, "x": 0, "y": 0, "w": 6, "h": 2}
        self.assertIn("s", validate_layout(free(b)))
        validate_layout(free(dict(b, segment=[{"label": str(i), "key": "F1"} for i in range(6)])))
        validate_layout(free(dict(b, label="")))
        validate_layout(free(dict(b, style="accent")))
        for seg_bad in (seg[:1], [{"label": str(i), "key": "F1"} for i in range(7)], "F1", [],
                        [{"label": "A", "key": "F1"}, {"label": "B"}],
                        [{"label": "A", "key": "F1"}, {"label": "B", "key": ""}],
                        [{"label": "A", "key": "F1"}, {"label": "B", "key": "NOPE"}],
                        [{"label": "", "key": "F1"}, {"label": "B", "key": "F2"}],
                        [{"label": "x" * 21, "key": "F1"}, {"label": "B", "key": "F2"}],
                        [{"label": "A", "key": "F1", "extra": 1}, {"label": "B", "key": "F2"}],
                        [seg[0], 5]):
            with self.subTest(seg=seg_bad):
                bad(self, free(dict(b, segment=seg_bad)))
        for extra in ({"key": "F1"}, {"macro": [{"key": "F1"}]}, {"page": "p"}, {"open": "https://x.de/"},
                      {"states": [{"label": "A", "key": "F1"}, {"label": "B", "key": "F2"}]},
                      {"slider": {"up": "F1", "down": "F2", "steps": 4}},
                      {"mode": "toggle"}, {"mode": "double"}, {"mode": "hold-confirm"}, {"hold": True}):
            with self.subTest(extra=extra):
                bad(self, free(dict(b, **extra)))

    def test_segment_press_and_keys(self):
        b = {"id": "s", "label": "Z", "segment": [{"label": "A", "key": "F1"}, {"label": "B", "key": "F2"}]}
        self.assertEqual(button_for_press(b, {"seg": 1})["key"], "F2")
        self.assertEqual(button_for_press(b, {"seg": 0})["id"], "s")
        for m in ({}, {"seg": 2}, {"seg": -1}, {"seg": "0"}, {"seg": True}, {"state": 0}):
            self.assertIsNone(button_for_press(b, m), m)
        self.assertEqual(needed_keys(b), ["F1", "F2"])

    def test_section(self):
        lay = {"pages": [{"id": "a", "title": "A", "section": "Flug", "buttons": []},
                         {"id": "b", "title": "B", "section": "x" * 20, "buttons": []},
                         {"id": "c", "title": "C", "buttons": []}]}
        validate_layout(lay)
        for sec in ("", "  ", "x" * 21, 3, None):
            with self.subTest(sec=sec):
                bad(self, {"pages": [{"id": "a", "title": "A", "section": sec, "buttons": []}]})

    def test_plain_free_keys_unchanged(self):
        buttons = validate_layout(free(key(), key(id="b", x=2)))
        self.assertEqual(sorted(buttons), ["a", "b"])

    def test_demo_panel_is_valid(self):
        f = ROOT / "docs" / "beispiele" / "cockpit-demo.json"
        layout = json.loads(f.read_text(encoding="utf-8"))
        buttons = validate_layout(layout)
        self.assertTrue(buttons)
        every = [b for p in layout["pages"] for b in p["buttons"]]
        self.assertTrue({"big", "arrow", "pill"} <= {b.get("look") for b in every})
        self.assertTrue({"double", "hold-confirm"} <= {b.get("mode") for b in every})
        self.assertTrue({"frame", "text"} <= {b.get("kind") for b in every})
        self.assertTrue(any("segment" in b for b in every))
        self.assertTrue(any(p.get("section") for p in layout["pages"]))


if __name__ == "__main__":
    unittest.main()
