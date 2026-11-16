"""Dashboards für die Seite /stats/: laden, prüfen, auflisten (dashboards/<name>.json).

Format und Widget-Arten: docs/sensors.md, Abschnitt „Dashboard“. Der Hub liefert die geprüfte Datei über
GET /api/dashboards/<name>; die Liste über GET /api/dashboards.
"""
import json
import logging
import math
import re
from pathlib import Path

log = logging.getLogger("dashboard")

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
SENSOR_ID = re.compile(r"[a-z0-9][a-z0-9_.]{0,63}")
COLOR = re.compile(r"#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})|rgba?\(\s*[0-9., %]{5,40}\)|transparent|none")
TYPES = ("value", "gauge", "bar", "line", "text", "clock", "date", "rect", "hline", "cores", "fans")
SENSOR_TYPES = ("value", "gauge", "bar", "line")
FONTS = ("sans", "mono", "head")
ALIGNS = ("start", "center", "end")
MAX_WIDGETS = 500
MAX_BYTES = 1_000_000
CANVAS = (100, 10000)          # erlaubte Breite/Höhe


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _text(limit):
    return lambda v: isinstance(v, str) and len(v) <= limit


def _color(v):
    return isinstance(v, str) and len(v) <= 60 and bool(COLOR.fullmatch(v))


def _zones(v):
    # aufsteigend: der Renderer nimmt die letzte Zone mit f >= from und baut daraus die Farbverlaufsstopps
    return (isinstance(v, list) and len(v) <= 8 and all(
        isinstance(z, dict) and _num(z.get("from")) and 0 <= z["from"] <= 1 and _color(z.get("color")) for z in v)
        and all(a["from"] <= b["from"] for a, b in zip(v, v[1:])))


# Prüfung je Schlüssel (gilt für alle Widget-Arten; unbekannte Schlüssel werden ignoriert)
CHECKS = {
    "x": _num, "y": _num, "w": lambda v: _num(v) and v > 0, "h": lambda v: _num(v) and v > 0,
    "sensor": lambda v: isinstance(v, str) and bool(SENSOR_ID.fullmatch(v)),
    "label": _text(60), "unit": _text(12), "text": _text(200), "format": _text(40),
    "color": _color, "fill": _color, "stroke": _color, "track": _color, "label_color": _color,
    "min": _num, "max": _num, "scale": lambda v: _num(v) and v != 0,
    "gap": lambda v: _num(v) and v >= 0, "size": lambda v: _num(v) and 4 <= v <= 400,
    "thickness": lambda v: _num(v) and 0 < v <= 200, "stroke_width": lambda v: _num(v) and 0 <= v <= 100,
    "seconds": lambda v: _num(v) and 5 <= v <= 600,
    "decimals": lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 6,
    "font": lambda v: v in FONTS, "align": lambda v: v in ALIGNS,
    "small_unit": lambda v: isinstance(v, bool), "zones": _zones,
    "radius": lambda v: _num(v) and 0 <= v <= 200, "area": _color,
    "ring": lambda v: isinstance(v, bool), "axis": lambda v: isinstance(v, bool),
    "color_e": _color, "text_color": _color, "separator": _color,     # nur cores bzw. fans
    "label_size": lambda v: _num(v) and 4 <= v <= 400,
    "columns": lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 16,
    "row_h": lambda v: _num(v) and 8 <= v <= 400,
    "weight": lambda v: _num(v) and v == int(v) and 100 <= v <= 900,   # 700.0 (Editor/Hand) ist auch gültig
}


def validate(d):
    """Prüft ein Dashboard (geladenes JSON). Ergebnis: das Dashboard selbst; ValueError mit Fundstelle."""
    if not isinstance(d, dict):
        raise ValueError("Objekt erwartet")
    if not isinstance(d.get("title"), str) or not 0 < len(d["title"]) <= 80:
        raise ValueError("title fehlt oder ist zu lang")
    for k in ("width", "height"):
        if not _num(d.get(k)) or not CANVAS[0] <= d[k] <= CANVAS[1]:
            raise ValueError(f"{k} muss eine Zahl von {CANVAS[0]} bis {CANVAS[1]} sein")
    if not _color(d.get("background")):
        raise ValueError("background ist keine Farbe")
    ws = d.get("widgets")
    if not isinstance(ws, list) or len(ws) > MAX_WIDGETS:
        raise ValueError(f"widgets: Liste mit höchstens {MAX_WIDGETS} Einträgen erwartet")
    for i, w in enumerate(ws):
        where = f"widgets[{i}]"
        if not isinstance(w, dict):
            raise ValueError(f"{where}: Objekt erwartet")
        t = w.get("type")
        if t not in TYPES:
            raise ValueError(f"{where}: unbekannte Art {t!r}")
        for k in ("x", "y", "w", "h"):
            if k not in w:
                raise ValueError(f"{where} ({t}): {k} fehlt")
        if t in SENSOR_TYPES and "sensor" not in w:
            raise ValueError(f"{where} ({t}): sensor fehlt")
        if t == "text" and "text" not in w:
            raise ValueError(f"{where} (text): text fehlt")
        for k, v in w.items():
            if k in CHECKS and not CHECKS[k](v):
                raise ValueError(f"{where} ({t}): {k} ungültig")
        if "min" in w and "max" in w and w["min"] >= w["max"]:
            raise ValueError(f"{where} ({t}): min muss kleiner als max sein")
    return d


def load(folder, name):
    """Dashboard dashboards/<name>.json laden und prüfen. FileNotFoundError bei unbekanntem Namen."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise FileNotFoundError(name)
    path = Path(folder) / f"{name}.json"
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise FileNotFoundError(name)
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise ValueError(f"kein gültiges JSON ({e.msg}, Zeile {e.lineno})") from None


def list_dashboards(folder):
    """[{"name", "title"}] der gültigen Dashboards, alphabetisch; fehlerhafte werden geloggt und übergangen."""
    out = []
    for p in sorted(Path(folder).glob("*.json")) if Path(folder).is_dir() else []:
        if not NAME.fullmatch(p.stem):
            continue
        try:
            out.append({"name": p.stem, "title": load(folder, p.stem)["title"]})
        except (ValueError, OSError) as e:
            log.warning("Dashboard %s übergangen: %s", p.name, e)
    return out
