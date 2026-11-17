"""Auto-Layout: semantische Vorlagen (ohne Koordinaten) -> Panel-Layout (Bereiche im Raster oder Kacheln)."""
import json
import unittest
from pathlib import Path

from bridge.autolayout import COLS, ROWS, build, is_semantic

ROOT = Path(__file__).resolve().parent.parent
COCKPIT = ROOT / "templates" / "star-citizen" / "cockpit.json"


def cockpit():
    return json.loads(COCKPIT.read_text(encoding="utf-8"))


def cells(b):
    return {(x, y) for x in range(b["x"], b["x"] + b["w"]) for y in range(b["y"], b["y"] + b["h"])}


def keys(n, size="m"):
    return [{"label": f"T{i}", "action": f"a{i}", "size": size} for i in range(n)]


class AutoLayoutTest(unittest.TestCase):
    def check_page(self, page):
        """Rahmen füllen die Seite lückenlos ohne Überlappung; Tasten liegen in ihrem Rahmen, überlappen nie."""
        frames = [b for b in page["buttons"] if b.get("kind") == "frame"]
        seen = set()
        for f in frames:
            c = cells(f)
            self.assertFalse(c & seen, f["label"])
            seen |= c
        self.assertEqual(len(seen), COLS * ROWS)
        taken = set()
        for b in page["buttons"]:
            if b.get("kind") == "frame" or "zone" in b:
                continue
            c = cells(b)
            self.assertFalse(c & taken, b["id"])
            taken |= c
            self.assertTrue(any(c <= cells(f) for f in frames), b["id"])

    def test_cockpit_areas_one_page_per_section(self):
        spec = cockpit()
        self.assertTrue(is_semantic(spec))
        lay = build(spec, "areas")
        self.assertEqual([p["title"] for p in lay["pages"]], [s["title"] for s in spec["sections"]])
        for p in lay["pages"]:
            self.check_page(p)
        shields = [b for b in lay["pages"][0]["buttons"] if b.get("kind") == "shield"]
        self.assertEqual(len(shields), 1)
        self.assertEqual({b["zone"] for b in lay["pages"][0]["buttons"] if "zone" in b},
                         {"front", "back", "left", "right", "reset"})

    def test_cockpit_grid(self):
        lay = build(cockpit(), "grid")
        types = [p.get("type", "grid") for p in lay["pages"]]
        self.assertEqual(types, ["grid", "shield", "grid"])        # Schildseite hinter ihrem Bereich
        groups = {b.get("group") for b in lay["pages"][0]["buttons"]}
        self.assertIn("Energie", groups)

    def test_pairs_never_share_a_row(self):
        pair = lambda n: {"pair": [{"label": n, "action": n + "-"}, {"label": n, "action": n + "+"}]}
        spec = {"sections": [{"title": "S", "areas": [{"title": "E", "items": [pair("a"), pair("b"), pair("c")]}]}]}
        page = build(spec)["pages"][0]
        ys = {}
        for b in page["buttons"]:
            if b.get("look") == "arrow":
                ys.setdefault(b["y"], set()).add(b["label"])
        self.assertTrue(all(len(v) == 1 for v in ys.values()), ys)
        self.check_page(page)

    def test_single_key_grows_at_most_double(self):
        spec = {"sections": [{"title": "S", "areas": [{"title": "A", "items": keys(1)}]}]}
        b = [b for b in build(spec)["pages"][0]["buttons"] if "kind" not in b][0]
        self.assertLessEqual(b["w"], 4)

    def test_too_much_splits_into_pages(self):
        spec = {"sections": [{"title": "Viel", "areas": [{"title": f"B{i}", "items": keys(12)} for i in range(6)]}]}
        lay = build(spec)
        self.assertGreater(len(lay["pages"]), 1)
        self.assertTrue(all(p["section"] == "Viel" for p in lay["pages"]))
        for p in lay["pages"]:
            self.check_page(p)

    def test_two_shields_on_separate_pages(self):
        z = {"front": {"label": "V", "action": "f"}, "back": {"label": "H", "action": "b"}}
        spec = {"sections": [{"title": "S", "areas": [{"title": "A", "shield": z}, {"title": "B", "shield": z}]}]}
        lay = build(spec)
        self.assertEqual(len(lay["pages"]), 2)

    def test_limits_and_types(self):
        many = {"sections": [{"title": "S", "areas": [{"title": f"B{i}", "items": keys(2)} for i in range(13)]}]}
        for bad in (many,
                    {"sections": [{"title": "S", "areas": [{"title": "A", "items": keys(61)}]}]},
                    {"sections": [{"title": "S", "areas": [{"title": "A", "items": None}]}]},
                    {"sections": [{"title": "S", "areas": [{"title": "A", "items": ["x"]}]}]},
                    {"sections": [{"title": "S", "areas": {"a": 1}}]},
                    {"sections": [{"title": 5, "areas": []}]},
                    {"sections": [{"title": "S", "areas": [{"title": "A", "shield": "vorn"}]}]},
                    {"sections": [{"title": "S", "areas": [{"title": "A", "items": [
                        {"pair": [{"label": "a", "action": "a"}, {"label": "b", "action": "b"}], "dirs": ["up"]}]}]}]}):
            with self.assertRaises(ValueError) as cm:
                build(bad)
            self.assertNotIn("NoneType", str(cm.exception))
        for style in ([], 5, None):
            with self.assertRaises(ValueError):
                build(cockpit(), style)

    def test_invalid(self):
        for bad in ({}, {"sections": []}, {"pages": []}, {"sections": [{"title": "S", "areas": [
                {"title": "A", "items": [{"label": "x", "action": "a", "size": "riesig"}]}]}]},
                {"sections": [{"title": "S", "areas": [{"title": "A", "items": [{"pair": [{"label": "x"}]}]}]}]},
                {"sections": [{"areas": []}]}):
            with self.assertRaises(ValueError):
                build(bad)
        with self.assertRaises(ValueError):
            build(cockpit(), "bunt")


if __name__ == "__main__":
    unittest.main()
