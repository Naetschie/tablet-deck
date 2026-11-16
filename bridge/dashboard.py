"""Dashboards für die Seite /stats/: laden, prüfen, auflisten (dashboards/<name>.json).

Format und Widget-Arten: docs/sensors.md, Abschnitt „Dashboard“. Der Hub liefert die geprüfte Datei über
GET /api/dashboards/<name>; die Liste über GET /api/dashboards.
"""
import copy
import json
import logging
import math
import os
import re
import shutil
from pathlib import Path

log = logging.getLogger("dashboard")

NAME = re.compile(r"[a-z0-9_-]{1,40}")
GROUP = re.compile(r"[a-z0-9_-]{1,20}")
SENSOR_ID = re.compile(r"[a-z0-9][a-z0-9_.]{0,63}")
COLOR = re.compile(r"#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})|rgba?\(\s*[0-9., %]{5,40}\)|transparent|none")
TYPES = ("value", "gauge", "bar", "line", "text", "clock", "date", "rect", "hline", "cores", "fans")
SENSOR_TYPES = ("value", "gauge", "bar", "line")
FONTS = ("sans", "mono", "head")
ALIGNS = ("start", "center", "end")
MAX_WIDGETS = 500
MAX_BYTES = 1_000_000
TITLE_MAX = 80
FALLBACK = "deck"      # Standard, wenn nichts gesetzt oder das gesetzte Dashboard verschwunden ist
RESERVED = {"default", "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
CANVAS = (100, 10000)          # erlaubte Breite/Höhe


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _color(v):
    return isinstance(v, str) and len(v) <= 60 and bool(COLOR.fullmatch(v))


def _zones(v):
    # aufsteigend: der Renderer nimmt die letzte Zone mit f >= from und baut daraus die Farbverlaufsstopps
    return (isinstance(v, list) and len(v) <= 8 and all(
        isinstance(z, dict) and _num(z.get("from")) and 0 <= z["from"] <= 1 and _color(z.get("color")) for z in v)
        and all(a["from"] <= b["from"] for a, b in zip(v, v[1:])))


# Feldbeschreibungen: EINE Quelle für die Prüfung (CHECKS) und den Export für den Editor (schema()).
#   number: min/max (einschließlich), gt (echt größer), nonzero, integral (ganzzahliger Wert, auch 700.0)
#   int: wie number, aber nur echte ganze Zahlen (kein bool)      text: max_len      color / bool / zones
#   enum: values      sensor: Sensor-ID
def _n(**kw):
    return dict(kind="number", **kw)


def _i(**kw):
    return dict(kind="int", **kw)


SPEC = {
    "x": _n(), "y": _n(), "w": _n(gt=0), "h": _n(gt=0),
    "sensor": dict(kind="sensor"),
    "label": dict(kind="text", max_len=60), "unit": dict(kind="text", max_len=12),
    "text": dict(kind="text", max_len=200), "format": dict(kind="text", max_len=40),
    "color": dict(kind="color"), "fill": dict(kind="color"), "stroke": dict(kind="color"),
    "track": dict(kind="color"), "label_color": dict(kind="color"),
    "min": _n(), "max": _n(), "scale": _n(nonzero=True),
    "gap": _n(min=0), "size": _n(min=4, max=400),
    "thickness": _n(gt=0, max=200), "stroke_width": _n(min=0, max=100),
    "seconds": _n(min=5, max=600),
    "decimals": _i(min=0, max=6),
    "font": dict(kind="enum", values=list(FONTS)), "align": dict(kind="enum", values=list(ALIGNS)),
    "small_unit": dict(kind="bool"), "zones": dict(kind="zones", max_items=8),
    "radius": _n(min=0, max=200), "area": dict(kind="color"),
    "ring": dict(kind="bool"), "axis": dict(kind="bool"),
    "color_e": dict(kind="color"), "text_color": dict(kind="color"), "separator": dict(kind="color"),   # cores/fans
    "label_size": _n(min=4, max=400),
    "columns": _i(min=1, max=16),
    "row_h": _n(min=8, max=400),
    "weight": _n(min=100, max=900, integral=True),   # 700.0 (Editor/Hand) ist auch gültig
    "group": dict(kind="text", pattern=GROUP.pattern),   # Gruppenname für den Editor
}

# Felder je Widget-Art (zusätzlich zu x, y, w, h, group); docs/sensors.md, Abschnitt „Dashboard“
TYPE_FIELDS = {
    "value": ["label", "label_color", "unit", "scale", "decimals", "gap", "size", "color", "font", "weight",
              "small_unit", "align"],
    "gauge": ["min", "max", "color", "track", "thickness", "zones", "ring"],
    "bar": ["min", "max", "color", "track", "radius"],
    "line": ["seconds", "min", "max", "color", "area", "axis", "label_color", "size", "thickness", "unit",
             "decimals"],
    "text": ["text", "color", "size", "font", "weight", "align"],
    "clock": ["format", "color", "size", "font", "align"],
    "date": ["format", "color", "size", "font", "align"],
    "rect": ["fill", "stroke", "stroke_width", "radius"],
    "hline": ["color", "thickness"],
    "cores": ["columns", "row_h", "gap", "size", "label_size", "scale", "decimals", "unit", "min", "max", "color",
              "color_e", "track", "label_color", "text_color", "weight"],
    "fans": ["row_h", "size", "label_size", "unit", "decimals", "color", "label_color", "separator", "weight"],
}
COMMON_FIELDS = ["x", "y", "w", "h", "group"]


def _make_check(sp):
    k = sp["kind"]
    if k in ("number", "int"):
        def check(v):
            if k == "int":
                if not isinstance(v, int) or isinstance(v, bool):
                    return False
            elif not _num(v):
                return False
            if sp.get("integral") and v != int(v):
                return False
            return ((sp.get("min") is None or v >= sp["min"]) and (sp.get("max") is None or v <= sp["max"])
                    and (sp.get("gt") is None or v > sp["gt"]) and not (sp.get("nonzero") and v == 0))
        return check
    if k == "text":
        pat = re.compile(sp["pattern"]) if sp.get("pattern") else None
        lim = sp.get("max_len", 200)
        return lambda v: isinstance(v, str) and len(v) <= lim and (pat is None or bool(pat.fullmatch(v)))
    if k == "sensor":
        return lambda v: isinstance(v, str) and bool(SENSOR_ID.fullmatch(v))
    if k == "color":
        return _color
    if k == "bool":
        return lambda v: isinstance(v, bool)
    if k == "enum":
        return lambda v: v in sp["values"]
    if k == "zones":
        return _zones
    raise ValueError(k)


# Prüfung je Schlüssel (gilt für alle Widget-Arten; unbekannte Schlüssel werden ignoriert)
CHECKS = {k: _make_check(sp) for k, sp in SPEC.items()}


def schema():
    """Feldbeschreibung als JSON-fähiges Dict für den Editor (Eingabefelder; gleiche Quelle wie die Prüfung)."""
    types = {}
    for t in TYPES:
        types[t] = {"fields": COMMON_FIELDS + (["sensor"] if t in SENSOR_TYPES else []) + TYPE_FIELDS[t],
                    "required": ["x", "y", "w", "h"] + (["sensor"] if t in SENSOR_TYPES else [])
                    + (["text"] if t == "text" else [])}
    return {"types": types, "fields": copy.deepcopy(SPEC), "name_pattern": NAME.pattern,
            "group_pattern": GROUP.pattern, "canvas": {"min": CANVAS[0], "max": CANVAS[1]},
            "max_widgets": MAX_WIDGETS, "sensor_pattern": SENSOR_ID.pattern, "color_pattern": COLOR.pattern,
            "rules": ["min < max, wenn beide angegeben"], "title_max": TITLE_MAX}


def validate(d):
    """Prüft ein Dashboard (geladenes JSON). Ergebnis: das Dashboard selbst; ValueError mit Fundstelle."""
    if not isinstance(d, dict):
        raise ValueError("Objekt erwartet")
    if not isinstance(d.get("title"), str) or not 0 < len(d["title"]) <= TITLE_MAX:
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


# ---------------------------------------------------------------------------------------------------------
# Verwaltung: mitgelieferte Dashboards (dashboards/, Git) und eigene (dashboards/eigene/, nicht im Git/Paket)
# ---------------------------------------------------------------------------------------------------------
BUNDLED, OWN = "mitgeliefert", "eigen"
OWN_DIR = "eigene"


def valid_name(name):
    """Namensregel für alle Dashboards (nie ein Pfad aus der Anfrage verwenden)."""
    return isinstance(name, str) and bool(NAME.fullmatch(name)) and name not in RESERVED


def _atomic_write(path, text):
    tmp = Path(f"{path}.{os.getpid()}.tmp")   # eindeutig: kein Zusammenstoß mit anderen Schreibern
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


class Dashboards:
    """Dashboards des Hubs. Namen sind über beide Ablagen eindeutig; mitgelieferte sind schreibgeschützt.

    cfg/cfg_path: Einstellungen (config.json) für den gewählten Standard `stats_dashboard`.
    """

    def __init__(self, bundled_dir, cfg=None, cfg_path=None):
        self.bundled = Path(bundled_dir)
        self.own = self.bundled / OWN_DIR
        self.cfg = cfg if cfg is not None else {}
        self.cfg_path = cfg_path
        self._warned_hidden = set()   # verdeckte eigene Dashboards nur einmal melden

    # ---- Lesen ----
    def origin(self, name):
        """"mitgeliefert", "eigen" oder None (unbekannt/ungültiger Name)."""
        if not valid_name(name):
            return None
        if (self.bundled / f"{name}.json").is_file():
            return BUNDLED
        if (self.own / f"{name}.json").is_file():
            return OWN
        return None

    def _folder(self, origin):
        return self.bundled if origin == BUNDLED else self.own

    def list(self):
        """[{"name", "title", "origin"}]: erst mitgelieferte, dann eigene, je alphabetisch."""
        out = []
        for origin in (BUNDLED, OWN):
            for d in list_dashboards(self._folder(origin)):
                hidden = origin == OWN and (self.bundled / f"{d['name']}.json").is_file()
                if hidden and d["name"] not in self._warned_hidden:
                    self._warned_hidden.add(d["name"])
                    log.warning("Eigenes Dashboard %r wird von einem mitgelieferten gleichen Namens verdeckt - "
                                "in dashboards/eigene/ umbenennen", d["name"])
                if valid_name(d["name"]) and not hidden:
                    out.append(dict(d, origin=origin))
        return out

    def load(self, name):
        """(Dashboard, Herkunft). FileNotFoundError bei unbekanntem Namen, ValueError bei ungültiger Datei."""
        origin = self.origin(name)
        if origin is None:
            raise FileNotFoundError(name)
        return load(self._folder(origin), name), origin

    # ---- Schreiben (nur eigene) ----
    def _own_path(self, name):
        origin = self.origin(name)
        if origin == BUNDLED:
            raise ValueError("Mitgeliefertes Dashboard ist schreibgeschützt - bitte zuerst eine Kopie anlegen")
        if origin is None:
            raise ValueError("Dashboard nicht gefunden")
        return self.own / f"{name}.json"

    def save(self, name, d):
        path = self._own_path(name)
        try:
            validate(d)
        except ValueError as e:
            raise ValueError(f"Dashboard ungültig: {e}") from None
        try:
            text = json.dumps(d, indent=1, ensure_ascii=False, allow_nan=False) + "\n"
        except ValueError:
            raise ValueError("Dashboard ungültig: NaN/Unendlich in einem Feld") from None
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise ValueError("Dashboard ist zu groß")
        _atomic_write(path, text)

    def free_name(self, base):
        base = (re.sub(r"[^a-z0-9_-]", "-", str(base).lower()).strip("-") or "dashboard")[:40]
        cand, n = base, 1
        while not valid_name(cand) or self.origin(cand):
            n += 1
            suffix = f"-{n}"
            cand = base[:40 - len(suffix)] + suffix
        return cand

    def create(self, from_name=None, title=None):
        """Neues eigenes Dashboard: leer (1152x800) oder Kopie von from_name. Ergebnis: (Name, Dashboard)."""
        if from_name is None:
            d = {"title": "Neues Dashboard", "width": 1152, "height": 800, "background": "#0E1114", "widgets": []}
            base = "neu"
        else:
            d = copy.deepcopy(self.load(from_name)[0])
            base = re.sub(r"(-eigen(-\d+)?)+$", "", from_name) + "-eigen"
            d["title"] = d["title"] if d["title"].endswith("(eigen)") else d["title"][:TITLE_MAX - 8] + " (eigen)"
        if title is not None:
            if not isinstance(title, str) or not title.strip():
                raise ValueError("Titel fehlt")
            d["title"] = title.strip()[:TITLE_MAX]
        name = self.free_name(base)
        self.own.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.own / f"{name}.json", json.dumps(validate(d), indent=1, ensure_ascii=False) + "\n")
        return name, d

    def rename(self, name, to):
        src = self._own_path(name)
        if not valid_name(to):
            raise ValueError("Name: 1 bis 40 Zeichen aus a-z, 0-9, _ und -")
        if to == name:
            return
        if self.origin(to):
            raise ValueError("Name ist schon vergeben")
        os.replace(src, self.own / f"{to}.json")
        if self.cfg.get("stats_dashboard") == name:
            self._follow_default(to)

    def delete(self, name):
        """Eigenes Dashboard in dashboards/eigene/.papierkorb/ verschieben (wiederherstellbar)."""
        src = self._own_path(name)
        trash = self.own / ".papierkorb"
        trash.mkdir(exist_ok=True)
        n = 1
        while (trash / f"{name}-{n}.json").exists():
            n += 1
        shutil.move(str(src), str(trash / f"{name}-{n}.json"))
        if self.cfg.get("stats_dashboard") == name:
            self._follow_default(None)

    def _follow_default(self, name):
        """Standard nach Umbenennen/Löschen nachziehen. Scheitert das (config.json gesperrt o. Ä.), ist der
        Vorgang selbst trotzdem erledigt - nur loggen; get_default fällt dann auf deck zurück."""
        try:
            self.set_default(name)
        except (OSError, ValueError) as e:
            log.warning("Standard-Dashboard nicht nachgezogen (%s) - gilt jetzt deck", e.__class__.__name__)

    # ---- Standard für die Kachel „PC-Werte“ ----
    def get_default(self):
        """Gewählter Standard; ohne Wahl oder bei verschwundenem Dashboard `deck`."""
        name = self.cfg.get("stats_dashboard")
        return name if self.origin(name) else FALLBACK

    def set_default(self, name):
        """Standard setzen (None/"" = zurück auf `deck`); schreibt config.json atomar, wirkt ohne Neustart."""
        if name in (None, ""):
            name = None
        elif not self.origin(name):
            raise ValueError("Dashboard nicht gefunden")
        if self.cfg_path:
            with open(self.cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            if name is None:
                cfg.pop("stats_dashboard", None)
            else:
                cfg["stats_dashboard"] = name
            _atomic_write(self.cfg_path, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        if name is None:
            self.cfg.pop("stats_dashboard", None)
        else:
            self.cfg["stats_dashboard"] = name

    # ---- Editor-Kanal ----
    def overview(self):
        return {"dashboards": self.list(), "default": self.get_default()}

    def handle(self, msg):
        """Editor-Nachricht dash_* (ohne dash_sensors) -> Antwort-Dict. ValueError mit Fehlertext bei Problemen."""
        t, name = msg.get("t"), msg.get("name")
        if t == "dash_list":
            return dict(self.overview(), t="dash_list")
        if t == "dash_schema":
            return {"t": "dash_schema", "schema": schema()}
        if t == "dash_get":
            try:
                d, origin = self.load(name)
            except FileNotFoundError:
                raise ValueError("Dashboard nicht gefunden") from None
            return {"t": "dash_get", "name": name, "origin": origin, "dashboard": d}
        if t == "dash_save":
            self.save(name, msg.get("dashboard"))
            log.info("Editor: Dashboard %s gespeichert", name)
            return {"t": "dash_saved", "name": name}
        if t == "dash_create":
            src = msg.get("from")
            if src is not None and not isinstance(src, str):
                raise ValueError("from ungültig")
            try:
                new, d = self.create(src, msg.get("title"))
            except FileNotFoundError:
                raise ValueError("Vorlage nicht gefunden") from None
            log.info("Editor: Dashboard %s angelegt", new)
            return dict(self.overview(), t="dash_created", name=new, origin=OWN, dashboard=d)
        if t == "dash_rename":
            self.rename(name, msg.get("to"))
            log.info("Editor: Dashboard %s -> %s", name, msg.get("to"))
            return dict(self.overview(), t="dash_renamed", name=msg.get("to"))
        if t == "dash_delete":
            self.delete(name)
            log.info("Editor: Dashboard %s in den Papierkorb", name)
            return dict(self.overview(), t="dash_deleted", name=name)
        if t == "dash_default":
            self.set_default(name)
            log.info("Editor: Standard-Dashboard %s", self.get_default())
            return dict(self.overview(), t="dash_default")
        raise ValueError("unbekannte Nachricht")


def sensor_list(values, meta):
    """Werteliste für den Editor aus Stats.sample(): [{"id","name","unit","value"}] nach ID sortiert, dazu "min"/"max"
    (Skalengrenzen des Sensors), wo bekannt - die Vorschau skaliert damit wie die Tablet-Seite."""
    out = []
    for i in sorted(values):
        m = meta.get(i) or {}
        item = {"id": i, "name": m.get("name", i), "unit": m.get("unit", ""), "value": values[i]}
        if isinstance(m.get("group"), str):
            item["group"] = m["group"]
        for k in ("min", "max"):
            if _num(m.get(k)):
                item[k] = m[k]
        out.append(item)
    return out
