"""Unit-Tests für bridge/dashboard.py (Laden, Prüfen, Liste) und scripts/mobro_import.py (MoBro -> Hub-Format).

Aufruf: python -m unittest tests.test_dashboard
"""
import copy
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

from bridge import dashboard
from bridge.sensors.mapping import DEFAULTS

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("mobro_import", ROOT / "scripts" / "mobro_import.py")
mobro_import = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mobro_import)


def good():
    return {"title": "Test", "width": 800, "height": 400, "background": "#323232", "widgets": [
        {"type": "value", "x": 0, "y": 0, "w": 100, "h": 20, "sensor": "cpu.load", "label": "CPU", "unit": "%",
         "decimals": 0, "color": "#0fff6b", "size": 15, "gap": 10, "font": "mono"},
        {"type": "gauge", "x": 0, "y": 20, "w": 100, "h": 100, "sensor": "gpu.temp", "min": 0, "max": 98,
         "zones": [{"from": 0.75, "color": "#ff9a00"}]},
        {"type": "bar", "x": 0, "y": 120, "w": 100, "h": 10, "sensor": "ram.used"},
        {"type": "line", "x": 0, "y": 130, "w": 100, "h": 50, "sensor": "cpu.load", "seconds": 60},
        {"type": "text", "x": 0, "y": 180, "w": 100, "h": 20, "text": "Hallo", "align": "center"},
        {"type": "clock", "x": 0, "y": 200, "w": 100, "h": 20, "format": "HH:mm:ss"},
        {"type": "date", "x": 0, "y": 220, "w": 100, "h": 20, "format": "DD-MM-YYYY"},
        {"type": "rect", "x": 0, "y": 240, "w": 10, "h": 10, "fill": "rgba(0,0,0,0.5)", "stroke": "none",
         "stroke_width": 2},
        {"type": "hline", "x": 0, "y": 250, "w": 100, "h": 3, "color": "#00c0bc", "thickness": 3},
    ]}


class ValidateTest(unittest.TestCase):
    def test_good(self):
        self.assertEqual(dashboard.validate(good())["title"], "Test")

    def bad(self, mutate, part):
        d = good()
        mutate(d)
        with self.assertRaises(ValueError) as cm:
            dashboard.validate(d)
        self.assertIn(part, str(cm.exception))

    def test_top_level(self):
        self.bad(lambda d: d.pop("title"), "title")
        self.bad(lambda d: d.update(width=5), "width")
        self.bad(lambda d: d.update(height="400"), "height")
        self.bad(lambda d: d.update(background="red; x"), "background")
        self.bad(lambda d: d.update(widgets={}), "widgets")
        self.bad(lambda d: d.update(widgets=[{"type": "text", "x": 0, "y": 0, "w": 1, "h": 1, "text": "x"}] * 501),
                 "widgets")
        with self.assertRaises(ValueError):
            dashboard.validate([])

    def test_widgets(self):
        self.bad(lambda d: d["widgets"][0].update(type="pie"), "unbekannte Art")
        self.bad(lambda d: d["widgets"][0].pop("x"), "x fehlt")
        self.bad(lambda d: d["widgets"][0].pop("sensor"), "sensor fehlt")
        self.bad(lambda d: d["widgets"][0].update(sensor="CPU Load; drop"), "sensor ungültig")
        self.bad(lambda d: d["widgets"][0].update(w=0), "w ungültig")
        self.bad(lambda d: d["widgets"][0].update(x=True), "x ungültig")
        self.bad(lambda d: d["widgets"][0].update(color="url(javascript:1)"), "color ungültig")
        self.bad(lambda d: d["widgets"][0].update(font="Comic"), "font ungültig")
        self.bad(lambda d: d["widgets"][0].update(decimals=1.5), "decimals ungültig")
        self.bad(lambda d: d["widgets"][0].update(size=float("nan")), "size ungültig")
        self.bad(lambda d: d["widgets"][1].update(zones=[{"from": 2, "color": "#fff"}]), "zones ungültig")
        self.bad(lambda d: d["widgets"][1].update(min=10, max=10), "min muss kleiner")
        self.bad(lambda d: d["widgets"][4].pop("text"), "text fehlt")
        self.bad(lambda d: d["widgets"][4].update(text="x" * 201), "text ungültig")
        self.bad(lambda d: d["widgets"].append("x"), "Objekt erwartet")
        self.bad(lambda d: d["widgets"][1].update(zones=[{"from": .85, "color": "#f00"},
                                                         {"from": .6, "color": "#ff0"}]), "zones ungültig")
        self.bad(lambda d: d["widgets"][2].update(radius=-1), "radius ungültig")
        self.bad(lambda d: d["widgets"][3].update(area="red;x"), "area ungültig")
        self.bad(lambda d: d["widgets"][1].update(ring="nein"), "ring ungültig")
        self.bad(lambda d: d["widgets"][3].update(axis=1), "axis ungültig")
        self.bad(lambda d: d["widgets"][0].update(weight=950), "weight ungültig")
        self.bad(lambda d: d["widgets"][0].update(weight=True), "weight ungültig")
        self.bad(lambda d: d["widgets"][0].update(weight=650.5), "weight ungültig")

    def test_new_fields_ok(self):
        d = good()
        d["widgets"][0].update(weight=700.0, label_color="#9aa0a6")
        d["widgets"][1].update(ring=False)
        d["widgets"][2].update(radius=4)
        d["widgets"][3].update(area="#0fff6b33", axis=True)
        dashboard.validate(d)

    def test_cores_and_fans(self):
        d = good()
        d["widgets"] += [
            {"type": "cores", "x": 0, "y": 0, "w": 300, "h": 100, "columns": 6, "size": 15, "label_size": 12,
             "scale": 0.001, "decimals": 1, "min": 0, "max": 5500, "color": "#4FB3FF", "color_e": "#8AC9FF",
             "track": "#28313B", "label_color": "#9AA6B2", "text_color": "#fff", "weight": 600, "row_h": 52},
            {"type": "fans", "x": 0, "y": 0, "w": 180, "h": 200, "size": 18, "label_size": 13, "row_h": 48,
             "color": "#fff", "label_color": "#9AA6B2", "separator": "#2B343E", "unit": "U/min"}]
        dashboard.validate(d)                              # ohne sensor: die Widgets suchen sich ihre IDs selbst
        for key, val in (("columns", 0), ("columns", 17), ("columns", 2.5), ("row_h", 2), ("color_e", "red;x"),
                         ("separator", "x"), ("text_color", "x"), ("label_size", 1)):
            for i in (-2, -1):
                e = good()
                e["widgets"] += copy.deepcopy(d["widgets"][-2:])
                e["widgets"][i][key] = val
                with self.assertRaises(ValueError, msg=(key, val)):
                    dashboard.validate(e)
        e = good()
        e["widgets"].append({"type": "cores", "x": 0, "y": 0, "w": 10})
        with self.assertRaises(ValueError):
            dashboard.validate(e)                          # h fehlt

    def test_colors(self):
        for c in ("#fff", "#0fff6b", "#0fff6b80", "rgba(0,0,0,0.5)", "rgb(1, 2, 3)", "none", "transparent"):
            d = good()
            d["background"] = c
            dashboard.validate(d)

    def test_shipped_dashboard_is_valid_and_uses_known_ids(self):
        d = dashboard.load(ROOT / "dashboards", "mobro")
        self.assertEqual((d["width"], d["height"]), (1382, 794))
        self.assertEqual(len(d["widgets"]), 54)      # 55 MoBro-Widgets ohne das Hintergrundbild
        for w in d["widgets"]:
            if "sensor" in w:
                self.assertIn(w["sensor"], DEFAULTS, w)


class DeckDashboardTest(unittest.TestCase):
    def test_deck_uses_cores_and_fans_and_known_ids(self):
        d = dashboard.load(ROOT / "dashboards", "deck")
        types = [w["type"] for w in d["widgets"]]
        self.assertEqual((types.count("cores"), types.count("fans")), (1, 1))
        for w in d["widgets"]:
            if "sensor" in w:
                self.assertIn(w["sensor"], DEFAULTS, w)
            self.assertNotRegex(w.get("sensor", ""), r"^(cpu\.clock|fan)\.")      # feste Kern-/Lüfter-IDs sind weg
        # das Raster passt in seine Karte (CPU-Karte 80 bis 488)
        c = next(w for w in d["widgets"] if w["type"] == "cores")
        self.assertLessEqual(c["y"] + c["h"], 80 + 408)


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_and_list(self):
        (self.d / "a.json").write_text(json.dumps(good()), encoding="utf-8")
        (self.d / "kaputt.json").write_text("{", encoding="utf-8")
        bad = good()
        bad["widgets"][0]["type"] = "pie"
        (self.d / "ungueltig.json").write_text(json.dumps(bad), encoding="utf-8")
        (self.d / "Gross.json").write_text(json.dumps(good()), encoding="utf-8")   # Name nicht erlaubt
        self.assertEqual(dashboard.load(self.d, "a")["title"], "Test")
        self.assertEqual(dashboard.list_dashboards(self.d), [{"name": "a", "title": "Test"}])
        with self.assertRaises(ValueError):
            dashboard.load(self.d, "kaputt")
        with self.assertRaises(ValueError):
            dashboard.load(self.d, "ungueltig")

    def test_names_cannot_escape(self):
        (self.d / "a.json").write_text(json.dumps(good()), encoding="utf-8")
        for n in ("../a", "a/../a", "a.json", "A", "", None, "a\\b", "..", "a%2f"):
            with self.assertRaises(FileNotFoundError, msg=n):
                dashboard.load(self.d, n)
        with self.assertRaises(FileNotFoundError):
            dashboard.load(self.d, "fehlt")

    def test_list_without_folder(self):
        self.assertEqual(dashboard.list_dashboards(self.d / "gibt-es-nicht"), [])


def hexc(h, a=1):
    return {"hex": h, "alpha": a}


def mobro_sample():
    """Kleines Beispiel im Aufbau der MoBro-Datei (erfundene IDs und Werte)."""
    def metric(i):
        return {"metric": {"id": i}}

    def widget(sub, x, y, w, h, order, **data):
        return {"type": "widget", "subtype": "@modbros_x/" + sub, "x": x, "y": y, "width": w, "height": h,
                "order": order, "rotation": 0, "data": data}

    items = {
        "g1": {"type": "group", "x": -100, "y": -100, "width": 200, "height": 200, "order": 9},
        "img": widget("image", -18, -91, 1400, 880, 70, image=[]),
        "bg": widget("rectangle", 0, 600, 1000, 100, 69, background_color=hexc("#323232")),
        "v1": widget("single_value", 10, 10, 200, 24, 5, font_color=hexc("#0fff6b"), font_size=15, gap=16,
                     **metric("plug.a")),
        "v2": widget("single_value", 10, 40, 200, 24, 4, font_color=hexc("#aeff00"), font_size=25, gap=5,
                     small_unit=True, **metric("plug.b")),
        "v3": widget("single_value", 10, 70, 200, 24, 3, **metric("plug.unbekannt")),
        "ga": widget("gauge", 300, 10, 189, 187, 2, max=98, **metric("plug.gt")),
        "gv": widget("single_value", 340, 70, 112, 47, 1, space_between=False, hide_label=True, font_size=45,
                     **metric("plug.gt")),
        "ba": widget("bar_chart", 10, 200, 223, 33, 6, max=65536, **metric("plug.ram")),
        "li": widget("line_chart", 10, 240, 474, 146, 7, yaxis_label_color=hexc("#0fff6b"),
                     yaxis_label_font_size=20, **metric("plug.cpu")),
        "tx": widget("text", 8, 7, 1377, 53, 8, text="Titel", font_size=40, text_color=hexc("#0fff6b")),
        "ck": widget("digital-clock", 45, 696, 200, 56, 10, format="24h", font_size=40),
        "dt": widget("digital-date", 45, 737, 200, 36, 11, format="D-M-Y", font_size=20),
        "re": widget("rectangle", 429, 216, 615, 287, 12, background_color=hexc("#000000", 0),
                     border_color=hexc("#000000", 0.8), border_thickness=5),
        "ln": widget("line", 15, 509, 1349, 5, 13, line_thickness=5, line_color=hexc("#00c0bc")),
    }
    info = {"metrics": {
        "plug.a": {"label": "P-core 3 Clock", "type": {"id": "frequency"}},
        "plug.b": {"label": "+12V", "type": {"id": "electricpotential"}},
        "plug.unbekannt": {"label": "Irgendwas", "type": {"id": "usage"}},
        "plug.gt": {"label": "GPU Core", "type": {"id": "temperature"}},
        "plug.ram": {"label": "Memory Used", "type": {"id": "data"}},
        "plug.cpu": {"label": "CPU Total", "type": {"id": "usage"}},
    }}
    return {"general": {"backgroundColor": hexc("#323232")}, "items": items}, info


class ImportTest(unittest.TestCase):
    def setUp(self):
        dash, info = mobro_sample()
        self.out, self.report = mobro_import.convert(dash, info)
        self.by_type = {}
        for w in self.out["widgets"]:
            self.by_type.setdefault(w["type"], []).append(w)

    def test_result_is_valid_and_counts(self):
        dashboard.validate(self.out)
        # 15 Elemente: Gruppe, Bild und "Irgendwas" (nicht zugeordnet) fallen weg
        self.assertEqual(len(self.out["widgets"]), 12)
        self.assertEqual((self.out["width"], self.out["height"]), (1364, 773))   # Ausdehnung ohne Text
        self.assertEqual(self.out["background"], "#323232")

    def test_report(self):
        txt = "\n".join(self.report)
        self.assertIn("plug.unbekannt", txt)
        self.assertIn("Irgendwas", txt)
        self.assertIn("(Bild)", txt)
        self.assertIn("geschätzt", txt)

    def test_z_order_back_to_front(self):
        # größtes "order" liegt hinten: das Rechteck mit order 69 kommt zuerst, order 1 (Zeigerwert) zuletzt
        self.assertEqual(self.out["widgets"][0]["type"], "rect")
        self.assertEqual(self.out["widgets"][0]["y"], 600)
        self.assertEqual(self.out["widgets"][-1]["type"], "value")
        self.assertEqual(self.out["widgets"][-1]["sensor"], "gpu.temp")

    def test_values(self):
        vals = {w["sensor"]: w for w in self.by_type["value"]}
        w = vals["cpu.clock.p3"]
        self.assertEqual((w["label"], w["unit"], w["decimals"], w["gap"], w["size"], w["color"]),
                         ("P-core 3 Clock", "MHz", 0, 16, 15, "#0fff6b"))
        v = vals["volt.12v"]
        self.assertEqual((v["unit"], v["decimals"], v["small_unit"]), ("V", 3, True))
        g = vals["gpu.temp"]
        self.assertNotIn("label", g)
        self.assertEqual(g["align"], "center")

    def test_other_widgets(self):
        gauge = self.by_type["gauge"][0]
        self.assertEqual((gauge["sensor"], gauge["max"], gauge["min"]), ("gpu.temp", 98, 0))
        bar = self.by_type["bar"][0]
        self.assertEqual((bar["sensor"], bar["max"]), ("ram.used", 65536))
        line = self.by_type["line"][0]
        self.assertEqual((line["sensor"], line["label_color"], line["size"]), ("cpu.load", "#0fff6b", 20))
        self.assertEqual(self.by_type["text"][0]["text"], "Titel")
        self.assertEqual(self.by_type["clock"][0]["format"], "HH:mm:ss")
        self.assertEqual(self.by_type["date"][0]["format"], "DD-MM-YYYY")
        fills = {w["fill"]: w for w in self.by_type["rect"]}
        self.assertEqual(set(fills), {"#323232", "none"})          # Alpha 0 -> keine Füllung
        self.assertEqual(fills["none"]["stroke"], "rgba(0,0,0,0.8)")
        hl = self.by_type["hline"][0]
        self.assertEqual((hl["thickness"], hl["h"], hl["color"]), (5, 5, "#00c0bc"))

    def test_color_and_lookup(self):
        self.assertEqual(mobro_import.color(hexc("#0FFF6B")), "#0fff6b")
        self.assertEqual(mobro_import.color(hexc("#000000", 0.5)), "rgba(0,0,0,0.5)")
        self.assertEqual(mobro_import.color(hexc("#000000", 0)), "none")
        self.assertEqual(mobro_import.color(None, "#111111"), "#111111")
        self.assertEqual(mobro_import.color({"hex": "red"}, "#222222"), "#222222")
        self.assertEqual(mobro_import.lookup("E-core 10 Clock", "frequency")[0], "cpu.clock.e10")
        self.assertIsNone(mobro_import.lookup("E-core 12 Clock", "frequency"))
        self.assertIsNone(mobro_import.lookup("GPU Core", "usage"))       # Typ muss passen
        self.assertEqual(mobro_import.lookup("GPU Core", "frequency")[0], "gpu.clock.core")

    def test_table_ids_exist(self):
        """Jede Ziel-ID der Tabelle gibt es im Sensor-Helfer."""
        for _pat, _typ, sid, *_ in mobro_import.METRICS:
            ids = [sid.replace("\\1", str(n)) for n in range(12)] if "\\1" in sid else [sid]
            self.assertTrue(any(i in DEFAULTS for i in ids), sid)

    def test_without_info_nothing_is_mapped(self):
        dash, _ = mobro_sample()
        out, report = mobro_import.convert(dash, {})
        self.assertFalse([w for w in out["widgets"] if "sensor" in w])
        self.assertTrue(any("nicht zugeordnet" in r for r in report))


if __name__ == "__main__":
    unittest.main()
