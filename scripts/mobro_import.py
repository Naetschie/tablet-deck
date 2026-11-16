"""Wandelt ein MoBro-Dashboard (MoBro-Datenordner, dashboards/<uuid>.json) in das Dashboard-Format des Hubs.

Aufruf (einmalig):
    python scripts/mobro_import.py [DASHBOARD.json] [--info METRIC-INFORMATION.json] [--out dashboards/mobro.json]

Ohne Angaben: das einzige Dashboard in %APPDATA%\\mobro-data\\dashboards, Ausgabe dashboards/mobro.json.

Die Metrik-IDs von MoBro (modbros_hwinfo.m_4026532608_0_100663296) sagen nichts. Die zugehörige Datei
dashboards-metadata/<uuid>.metric-information.json nennt zu jeder ID Beschriftung und Typ („P-core 0 Clock“,
frequency). Die Zuordnung zu den Sensor-IDs des Hubs (docs/sensors.md) geschieht über genau dieses Paar
(Beschriftung, Typ), siehe METRICS. Was dort nicht steht, wird gemeldet und nicht übernommen.

Nicht übernommen: Bild-Widgets (Hintergrundbild) und Gruppen (sie ordnen nur; die Positionen der Widgets sind
absolut).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# MoBro-Standardfarben, soweit die Datei nichts angibt (aus dem Screenshot des Dashboards abgelesen)
TEAL = "#00c0bc"            # Linie, Balken, Zeigerbogen
TRACK = "#1d1e22"           # Balken- und Zeigerhintergrund
TEXT = "#cfcfcf"            # Text ohne Farbangabe (MoBro zeigt ihn dunkel auf dunklem Grund - hier lesbar)
GAUGE_ZONES = [{"from": 0.75, "color": "#ff9a00"}, {"from": 0.93, "color": "#e03000"}]   # geschätzt

# (Beschriftung als regulärer Ausdruck, MoBro-Typ, Sensor-ID, Einheit, Skalierung, Nachkommastellen)
# \1 in der ID = erste Gruppe der Beschriftung. Die Werte des Hubs sind schon in MHz, MB, KB/s usw.
METRICS = [
    (r"CPU Total", "usage", "cpu.load", "%", None, 0),
    (r"P-core ([0-7]) Clock", "frequency", r"cpu.clock.p\1", "MHz", None, 0),
    (r"E-core (8|9|10|11) Clock", "frequency", r"cpu.clock.e\1", "MHz", None, 0),
    (r"CPU Package", "temperature", "cpu.temp.package", "°C", None, 0),
    (r"Core Max", "temperature", "cpu.temp.core_max", "°C", None, 0),
    (r"CPU Package Power", "power", "cpu.power.package", "W", None, 0),
    (r"Memory Used", "data", "ram.used", "MB", None, 0),
    (r"CPU", "rotation", "fan.cpu", "rpm", None, 0),
    (r"System ([123])", "rotation", r"fan.sys\1", "rpm", None, 0),
    (r"\+12V", "electricpotential", "volt.12v", "V", None, 3),
    (r"\+5V", "electricpotential", "volt.5v", "V", None, 3),
    (r"\+3\.3V", "electricpotential", "volt.3v3", "V", None, 3),
    (r"DRAM", "electricpotential", "volt.dram", "V", None, 3),
    (r"Current DL rate", "dataflow", "net.down", "KB/s", None, 0),
    (r"Current UP rate", "dataflow", "net.up", "KB/s", None, 0),
    (r"Total DL", "data", "net.total_down", "MB", None, 0),
    (r"GPU Core", "temperature", "gpu.temp", "°C", None, 0),
    (r"GPU Core", "frequency", "gpu.clock.core", "MHz", None, 0),
    (r"GPU Memory", "frequency", "gpu.clock.mem", "MHz", None, 0),
    # RTX 5080: kein Hot Spot - Ersatz ist die Speichertemperatur (Beschriftung siehe LABELS)
    (r"GPU Hot Spot", "temperature", "gpu.temp.mem", "°C", None, 0),
    (r"GPU Fan ([12])", "rotation", r"gpu.fan\1", "rpm", None, 0),
    (r"GPU PCIe Rx", "dataflow", "gpu.pcie.rx", "KB/s", None, 0),
    (r"GPU Package", "power", "gpu.power", "W", None, 0),
    (r"GPU Memory Used", "data", "gpu.vram.used", "MB", None, 0),
    (r"GPU Memory Controller", "usage", "gpu.load.memctl", "%", None, 0),
    (r"Framerate \(Displayed\)", "numeric", "fps.displayed", "", None, 0),
    (r"Frame Time", "duration", "fps.frametime", "ms", None, 1),
]
LABELS = {"gpu.temp.mem": "GPU Mem Temp"}      # abweichende Beschriftung (Ersatzsensor)


def color(c, default=None):
    """MoBro-Farbe {"hex": "#0fff6b", "alpha": 1} -> "#0fff6b" bzw. "rgba(r,g,b,a)" bzw. "none" (alpha 0)."""
    if not isinstance(c, dict) or not re.fullmatch(r"#[0-9a-fA-F]{6}", str(c.get("hex", ""))):
        return default
    a = c.get("alpha", 1)
    a = 1 if not isinstance(a, (int, float)) or isinstance(a, bool) else max(0, min(1, a))
    if a == 0:
        return "none"
    if a == 1:
        return c["hex"].lower()
    h = c["hex"]
    return "rgba(%d,%d,%d,%g)" % (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16), a)


def lookup(label, mtype):
    """(Sensor-ID, Einheit, Skalierung, Nachkommastellen) zu (Beschriftung, MoBro-Typ) oder None."""
    for pat, typ, sid, unit, scale, dec in METRICS:
        if typ == mtype and re.fullmatch(pat, label or ""):
            return re.sub(pat, sid, label), unit, scale, dec
    return None


def _font(name):
    return "mono" if isinstance(name, str) and "cascadia" in name.lower() else None


def _put(w, key, val):
    if val is not None:
        w[key] = val


def convert(dash, info):
    """MoBro-Dashboard (dict) + Metrikinformation (dict mit "metrics") -> (Dashboard des Hubs, Bericht).
    Der Bericht ist eine Liste von Textzeilen über alles, was nicht übernommen wurde bzw. geschätzt ist."""
    general = dash.get("general") or {}
    items = list((dash.get("items") or {}).values())
    metrics = (info or {}).get("metrics") or {}
    report, out = [], []
    # MoBro zeichnet Elemente mit größerem "order" weiter hinten
    for it in sorted(enumerate(items), key=lambda p: (-(p[1].get("order") or 0), p[0])):
        it = it[1]
        if it.get("type") != "widget":
            continue
        sub = str(it.get("subtype", "")).rsplit("/", 1)[-1]
        data = it.get("data") or {}
        w = {"x": round(it["x"]), "y": round(it["y"]), "w": round(it["width"]), "h": round(it["height"])}
        where = f"{sub} bei ({w['x']},{w['y']})"
        if it.get("rotation"):
            report.append(f"Drehung ignoriert: {where}")
        sensor = None
        mid = (data.get("metric") or {}).get("id")
        if sub in ("single_value", "gauge", "bar_chart", "line_chart"):
            m = metrics.get(mid) or {}
            label, mtype = m.get("label"), (m.get("type") or {}).get("id")
            hit = lookup(label, mtype)
            if hit is None:
                report.append(f"nicht zugeordnet: {where}, MoBro-ID {mid}, Beschriftung {label!r}, Typ {mtype!r}")
                continue
            sensor, unit, scale, dec = hit
        if sub == "single_value":
            w.update(type="value", sensor=sensor, unit=unit, decimals=dec)
            if not data.get("hide_label"):
                w["label"] = LABELS.get(sensor, label)
                _put(w, "gap", data.get("gap"))
            else:
                w["align"] = "center" if "space_between" in data else "start"   # Zeigerwert: mittig
            _put(w, "scale", scale)
            _put(w, "color", color(data.get("font_color"), "#ffffff"))
            _put(w, "size", data.get("font_size"))
            _put(w, "font", _font(data.get("font")))
            if data.get("small_unit"):
                w["small_unit"] = True
        elif sub == "gauge":
            w.update(type="gauge", sensor=sensor, min=0, max=data.get("max", 100), color=TEAL, track=TRACK,
                     zones=GAUGE_ZONES)
            report.append(f"Zeiger-Zonen (Orange/Rot) und Farben geschätzt: {where}")
        elif sub == "bar_chart":
            w.update(type="bar", sensor=sensor, min=0, max=data.get("max", 100), color=TEAL, track=TRACK)
        elif sub == "line_chart":
            w.update(type="line", sensor=sensor, color=TEAL, seconds=60)
            _put(w, "label_color", color(data.get("yaxis_label_color")))
            _put(w, "size", data.get("yaxis_label_font_size"))
        elif sub == "text":
            w.update(type="text", text=str(data.get("text", "")), color=color(data.get("text_color"), TEXT),
                     size=data.get("font_size", 20))
            _put(w, "font", _font(data.get("font")))
            if data.get("align_horizontal") in (None, "flex-start"):
                w["align"] = "start"
            elif data.get("align_horizontal") == "center":
                w["align"] = "center"
            else:
                w["align"] = "end"
        elif sub == "digital-clock":
            fmt = {"24h": "HH:mm:ss"}.get(data.get("format"))
            if fmt is None:
                report.append(f"Uhrformat {data.get('format')!r} unbekannt, 24h genommen: {where}")
            w.update(type="clock", format=fmt or "HH:mm:ss", color=color(data.get("text_color"), "#ffffff"),
                     size=data.get("font_size", 40))
        elif sub == "digital-date":
            fmt = {"D-M-Y": "DD-MM-YYYY"}.get(data.get("format"))
            if fmt is None:
                report.append(f"Datumsformat {data.get('format')!r} unbekannt, DD-MM-YYYY genommen: {where}")
            w.update(type="date", format=fmt or "DD-MM-YYYY", color=color(data.get("text_color"), "#ffffff"),
                     size=data.get("font_size", 20))
        elif sub == "rectangle":
            w.update(type="rect", fill=color(data.get("background_color"), "#000000"),
                     stroke=color(data.get("border_color"), "#000000"),
                     stroke_width=data.get("border_thickness", 0) or 0)
        elif sub == "line":
            th = data.get("line_thickness") or 2
            w.update(type="hline", color=color(data.get("line_color"), "#ffffff"), thickness=th, h=max(1, th))
        else:
            report.append(f"nicht übernommen: {where}" + (" (Bild)" if sub == "image" else ""))
            continue
        out.append(w)
    bg = color(general.get("backgroundColor"), "#323232")
    # Fläche = Ausdehnung der Nicht-Text-Widgets (Texte dürfen überstehen; MoBro schneidet sie ab)
    shapes = [w for w in out if w["type"] != "text"] or out
    right = max((w["x"] + w["w"] for w in shapes), default=0)
    bottom = max((w["y"] + w["h"] for w in shapes), default=0)
    dashboard = {"title": "MoBro-Nachbau", "width": right, "height": bottom, "background": bg, "widgets": out}
    return dashboard, report


def default_paths():
    base = Path(os.path.expandvars(r"%APPDATA%\mobro-data"))
    files = sorted((base / "dashboards").glob("*.json"))
    return files[0] if len(files) == 1 else None, base


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dashboard", nargs="?", type=Path, help="MoBro-Dashboard (dashboards/<uuid>.json)")
    ap.add_argument("--info", type=Path, help="<uuid>.metric-information.json (Standard: neben dem Dashboard)")
    ap.add_argument("--out", type=Path, default=ROOT / "dashboards" / "mobro.json")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    src, base = (a.dashboard, None) if a.dashboard else default_paths()
    if src is None:
        sys.exit("Dashboard angeben (in %APPDATA%\\mobro-data\\dashboards liegt nicht genau eines).")
    info_path = a.info or src.parent.parent / "dashboards-metadata" / f"{src.stem}.metric-information.json"
    dash = json.loads(src.read_text(encoding="utf-8"))
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except OSError:
        sys.exit(f"Metrikinformation fehlt: {info_path} (mit --info angeben)")
    out, report = convert(dash, info)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(out['widgets'])} Widgets -> {a.out}")
    for line in report:
        print("  " + line)


if __name__ == "__main__":
    main()
