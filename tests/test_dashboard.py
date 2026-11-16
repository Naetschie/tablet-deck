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


class ManageTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name) / "dashboards"
        self.d.mkdir()
        for n in ("deck", "mobro"):
            (self.d / f"{n}.json").write_text(json.dumps(dict(good(), title=n.upper())), encoding="utf-8")
        self.cfg_path = Path(self._t.name) / "config.json"
        self.cfg_path.write_text(json.dumps({"port": 8765}), encoding="utf-8")
        self.cfg = {"port": 8765}
        self.m = dashboard.Dashboards(self.d, self.cfg, self.cfg_path)

    def tearDown(self):
        self._t.cleanup()

    def test_auflisten_mit_herkunft(self):
        self.m.create("deck")
        l = self.m.list()
        self.assertEqual([(x["name"], x["origin"]) for x in l],
                         [("deck", "mitgeliefert"), ("mobro", "mitgeliefert"), ("deck-eigen", "eigen")])
        self.assertEqual(l[0]["title"], "DECK")

    def test_review_nan_standard_verdeckt(self):
        name, d = self.m.create("deck")
        bad = dict(d, extra=float("nan"))           # unbekannter Schlüssel mit NaN: Datei wäre kein gültiges JSON
        with self.assertRaises(ValueError):
            self.m.save(name, bad)
        # Standard nachziehen scheitert (config.json weg): Löschen gilt trotzdem, Standard fällt auf deck
        self.m.set_default(name)
        self.cfg_path.unlink()
        with self.assertLogs("dashboard", "WARNING"):
            self.m.delete(name)
        self.assertEqual(self.m.get_default(), "deck")
        # eigenes Dashboard, das später ein mitgeliefertes gleichen Namens verdeckt: Warnung (einmal)
        (self.d / "eigene").mkdir(exist_ok=True)
        (self.d / "eigene" / "mobro.json").write_text(json.dumps(good()), encoding="utf-8")
        with self.assertLogs("dashboard", "WARNING"):
            self.m.list()

    def test_raw_ids_benutzte_rohwerte(self):
        self.assertEqual(self.m.raw_ids(), frozenset())
        name, d = self.m.create("deck")
        d["widgets"][0]["sensor"] = "lhm.nvme.0.temperature.0"
        self.m.save(name, d)                                     # Speichern leert den Zwischenspeicher
        self.assertEqual(self.m.raw_ids(), frozenset({"lhm.nvme.0.temperature.0"}))
        self.m.delete(name)
        self.assertEqual(self.m.raw_ids(), frozenset())

    def test_mitgelieferte_schreibgeschuetzt(self):
        for fn in (lambda: self.m.save("deck", good()), lambda: self.m.rename("deck", "x"),
                   lambda: self.m.delete("deck")):
            with self.assertRaises(ValueError) as c:
                fn()
            self.assertIn("schreibgeschützt", str(c.exception))
        self.assertTrue((self.d / "deck.json").is_file())

    def test_kopie_freier_name(self):
        self.assertEqual(self.m.create("deck")[0], "deck-eigen")
        self.assertEqual(self.m.create("deck")[0], "deck-eigen-2")
        self.assertEqual(self.m.create("deck-eigen")[0], "deck-eigen-3")      # Kopie einer Kopie: Endung nicht stapeln
        name, d = self.m.create("mobro", title="Mein Titel")
        self.assertEqual(d["title"], "Mein Titel")
        self.assertEqual(self.m.load(name)[1], "eigen")
        self.assertEqual(self.m.load(name)[0]["widgets"], good()["widgets"])
        self.assertEqual(self.m.load("deck-eigen")[0]["title"], "DECK (eigen)")
        with self.assertRaises(FileNotFoundError):
            self.m.create("gibtsnicht")

    def test_leeres_dashboard(self):
        name, d = self.m.create()
        self.assertEqual((d["width"], d["height"], d["widgets"]), (1152, 800, []))
        self.assertEqual(self.m.load(name)[0], d)
        self.assertEqual(self.m.create()[0], "neu-2")

    def test_eigener_name_nicht_wie_mitgelieferter(self):
        self.m.create("deck")
        with self.assertRaises(ValueError):
            self.m.rename("deck-eigen", "mobro")
        (self.d / "eigene" / "deck.json").write_text(json.dumps(good()), encoding="utf-8")   # von Hand eingeschleust
        self.assertEqual([x["origin"] for x in self.m.list() if x["name"] == "deck"], ["mitgeliefert"])
        self.assertEqual(self.m.origin("deck"), "mitgeliefert")

    def test_speichern_pruefen_atomar(self):
        name = self.m.create("deck")[0]
        d = good()
        d["title"] = "Neu"
        self.m.save(name, d)
        self.assertEqual(self.m.load(name)[0]["title"], "Neu")
        bad = copy.deepcopy(d)
        bad["widgets"][0]["size"] = 1
        with self.assertRaises(ValueError) as c:
            self.m.save(name, bad)
        self.assertIn("size", str(c.exception))
        self.assertEqual(self.m.load(name)[0]["title"], "Neu")                 # unverändert
        self.assertEqual(list((self.d / "eigene").glob("*.tmp")), [])
        with self.assertRaises(ValueError):
            self.m.save("gibtsnicht", d)

    def test_umbenennen_loeschen_papierkorb(self):
        name = self.m.create("deck")[0]
        self.m.rename(name, "mein_dash")
        self.assertIsNone(self.m.origin("deck-eigen"))
        self.assertEqual(self.m.origin("mein_dash"), "eigen")
        self.m.delete("mein_dash")
        self.assertIsNone(self.m.origin("mein_dash"))
        trash = self.d / "eigene" / ".papierkorb"
        self.assertEqual([p.name for p in trash.iterdir()], ["mein_dash-1.json"])
        self.m.create("deck")
        self.m.rename("deck-eigen", "mein_dash")
        self.m.delete("mein_dash")
        self.assertEqual(sorted(p.name for p in trash.iterdir()), ["mein_dash-1.json", "mein_dash-2.json"])
        with self.assertRaises(ValueError):
            self.m.delete("mein_dash")

    def test_namensregeln_und_traversal(self):
        name = self.m.create("deck")[0]
        for bad in ("", "A", "a b", "../x", "..\\x", "a/b", "x" * 41, "default", "con", "nul", "deck.json", None, 5,
                    "ä"):
            self.assertFalse(dashboard.valid_name(bad), bad)
            self.assertIsNone(self.m.origin(bad), bad)
            with self.assertRaises(ValueError):
                self.m.rename(name, bad)
            with self.assertRaises(FileNotFoundError):
                self.m.load(bad)
        with self.assertRaises(ValueError):
            self.m.save("../deck", good())
        with self.assertRaises(ValueError):
            self.m.delete("../deck")
        self.assertTrue(dashboard.valid_name("a_b-9") and dashboard.valid_name("x" * 40))

    def test_standard_setzen_und_rueckfall(self):
        self.assertEqual(self.m.get_default(), "deck")
        name = self.m.create("deck")[0]
        self.m.set_default(name)
        self.assertEqual(self.m.get_default(), name)
        self.assertEqual(json.loads(self.cfg_path.read_text(encoding="utf-8")),
                         {"port": 8765, "stats_dashboard": name})               # übrige Einstellungen bleiben
        self.assertEqual(self.cfg["stats_dashboard"], name)                     # ohne Neustart wirksam
        self.assertEqual(list(self.cfg_path.parent.glob("*.tmp")), [])
        with self.assertRaises(ValueError):
            self.m.set_default("gibtsnicht")
        self.m.rename(name, "neuer")                                            # Standard folgt der Umbenennung
        self.assertEqual(self.m.get_default(), "neuer")
        self.m.delete("neuer")                                                  # gelöscht: zurück auf deck
        self.assertEqual(self.m.get_default(), "deck")
        self.assertNotIn("stats_dashboard", json.loads(self.cfg_path.read_text(encoding="utf-8")))
        self.cfg["stats_dashboard"] = "verschwunden"                            # von Hand gesetzt, Datei fehlt
        self.assertEqual(self.m.get_default(), "deck")
        self.m.set_default("mobro")
        self.m.set_default(None)                                                # "Zurück zum Standard"
        self.assertEqual(self.m.get_default(), "deck")

    def test_editor_nachrichten(self):
        h = self.m.handle
        r = h({"t": "dash_list"})
        self.assertEqual((r["t"], r["default"], len(r["dashboards"])), ("dash_list", "deck", 2))
        r = h({"t": "dash_get", "name": "deck"})
        self.assertEqual((r["origin"], r["dashboard"]["title"]), ("mitgeliefert", "DECK"))
        with self.assertRaises(ValueError):
            h({"t": "dash_get", "name": "../x"})
        r = h({"t": "dash_create", "from": "deck", "title": "Kopie"})
        n = r["name"]
        self.assertEqual((r["t"], n, r["origin"], r["dashboard"]["title"]),
                         ("dash_created", "deck-eigen", "eigen", "Kopie"))
        d = r["dashboard"]
        d["background"] = "#000"
        self.assertEqual(h({"t": "dash_save", "name": n, "dashboard": d})["t"], "dash_saved")
        d["background"] = "rot"
        with self.assertRaises(ValueError) as c:
            h({"t": "dash_save", "name": n, "dashboard": d})
        self.assertIn("background", str(c.exception))
        with self.assertRaises(ValueError):
            h({"t": "dash_save", "name": "deck", "dashboard": good()})
        self.assertEqual(h({"t": "dash_default", "name": n})["default"], n)
        r = h({"t": "dash_rename", "name": n, "to": "x1"})
        self.assertEqual((r["name"], r["default"]), ("x1", "x1"))
        r = h({"t": "dash_delete", "name": "x1"})
        self.assertEqual((r["t"], r["default"]), ("dash_deleted", "deck"))
        self.assertEqual(h({"t": "dash_schema"})["schema"]["types"].keys(), dashboard.schema()["types"].keys())
        with self.assertRaises(ValueError):
            h({"t": "dash_create", "from": 5})
        with self.assertRaises(ValueError):
            h({"t": "dash_unbekannt"})

    def test_sensorliste(self):
        out = dashboard.sensor_list({"b.x": 2.5, "a.y": 1}, {"a.y": {"name": "Alpha", "unit": "%"}})
        self.assertEqual(out, [{"id": "a.y", "name": "Alpha", "unit": "%", "value": 1},
                               {"id": "b.x", "name": "b.x", "unit": "", "value": 2.5}])
        # Skalengrenzen des Sensors werden mitgegeben (nur Zahlen)
        out = dashboard.sensor_list({"c.z": 5}, {"c.z": {"name": "Z", "unit": "MHz", "min": 0, "max": 5500.5}})
        self.assertEqual(out, [{"id": "c.z", "name": "Z", "unit": "MHz", "value": 5, "min": 0, "max": 5500.5}])
        out = dashboard.sensor_list({"c.z": 5}, {"c.z": {"name": "Z", "unit": "", "min": None, "max": True}})
        self.assertNotIn("min", out[0])
        self.assertNotIn("max", out[0])

    def test_mitgelieferte_im_repo(self):
        m = dashboard.Dashboards(ROOT / "dashboards")
        names = {x["name"] for x in m.list() if x["origin"] == "mitgeliefert"}
        self.assertTrue({"deck", "mobro"} <= names)
        self.assertEqual(m.get_default(), "deck")


class SchemaTest(unittest.TestCase):
    def test_vollstaendig(self):
        s = json.loads(json.dumps(dashboard.schema()))                           # JSON-fähig
        self.assertEqual(set(s["types"]), set(dashboard.TYPES))
        self.assertEqual(set(s["fields"]), set(dashboard.CHECKS))
        used = set()
        for t, info in s["types"].items():
            self.assertTrue(set(info["fields"]) <= set(s["fields"]), t)
            self.assertTrue(set(info["required"]) <= set(info["fields"]), t)     # auch sensor (Eingabefeld im Editor)
            used |= set(info["fields"])
        self.assertEqual(used | {"sensor"}, set(s["fields"]))
        self.assertEqual(s["types"]["gauge"]["required"], ["x", "y", "w", "h", "sensor"])
        self.assertEqual(s["types"]["text"]["required"], ["x", "y", "w", "h", "text"])
        self.assertEqual(s["types"]["clock"]["required"], ["x", "y", "w", "h"])
        self.assertEqual(s["fields"]["font"]["values"], ["sans", "mono", "head"])
        self.assertEqual((s["fields"]["size"]["min"], s["fields"]["size"]["max"]), (4, 400))

    def test_schema_und_pruefung_stimmen_ueberein(self):
        # jede Grenze der Beschreibung ist gültig, knapp daneben ungültig
        for k, sp in dashboard.SPEC.items():
            if sp["kind"] not in ("number", "int"):
                continue
            chk = dashboard.CHECKS[k]
            if "min" in sp:
                self.assertTrue(chk(sp["min"]), k)
                self.assertFalse(chk(sp["min"] - 1), k)
            if "max" in sp:
                self.assertTrue(chk(sp["max"]), k)
                self.assertFalse(chk(sp["max"] + 1), k)
            if "gt" in sp:
                self.assertFalse(chk(sp["gt"]), k)

    def test_group_feld(self):
        d = good()
        d["widgets"][0]["group"] = "cpu-1_a"
        dashboard.validate(d)
        for bad in ("", "A", "a b", "x" * 21, 5, None, "../x"):
            d["widgets"][0]["group"] = bad
            with self.assertRaises(ValueError, msg=repr(bad)):
                dashboard.validate(d)


if __name__ == "__main__":
    unittest.main()
