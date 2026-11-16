"""Panel-Layout (layout.json): Prüfung und atomares Speichern.

Button-Felder:
  id, label (Pflicht) · key ("LALT+F") · mode: tap | hold-confirm | toggle · style: accent | danger
  hold: true = Taste so lange halten wie der Finger (sonst kurzer Impuls, passend zu "tap"-Aktionen)
  sc: Name der Star-Citizen-Aktion (scripts/sc_bindings.py leitet daraus key ab)
  group · wide · zone (Schild-Seite) · macro: Liste von Schritten (statt key):
      {"key": "LALT+1"}  {"text": "o7"}  {"wait": 200}  {"media": "playpause"}
  open: URL (http/https) oder absoluter Pfad (Programm, Datei, Ordner) - wird am PC geöffnet (statt key).
      Nur über den Editor am PC bzw. die Datei am PC festlegbar; das Tablet schickt nur die Tasten-ID.
  page: Seiten-id - Seiten-Link, wechselt am Tablet die Seite (statt key; sendet nichts an den PC)
  states: Mehrfach-Schalter, 2-6 Zustände [{"label": "FIX", "key": "LALT+G"}, ...]; jeder Tipp schaltet weiter.
      key je Zustand optional, wenn die Taste selbst ein key hat (Rückfall). Nur mode tap.
  slider: Regler {"up": "KEY", "down": "KEY", "steps": 10} (steps 2-20); jede Stufe sendet einen Tipp auf up/down.
      Ohne key/macro/open/page/states, mode tap.

  segment: Auswahlleiste [{"label": "ALLE", "key": "5"}, ...], 2-6 Teile nebeneinander; jeder Teil sendet seine
      eigene Taste (kein gemerkter Zustand). Ohne key/macro/open/page/states/slider, mode tap, ohne hold.
      Das Tablet schickt {"seg": Index}; label der Taste ist die optionale Überschrift.
  mode double: gesicherte Taste - erst der zweite Tipp innerhalb von 400 ms löst aus (entscheidet das Tablet,
      der Hub sieht nur den Tastendruck). Wie hold-confirm gedacht für style danger (zeigt Schloss und Warnstreifen).
  look: nur Optik, Verhalten unverändert: switch (Kippschalter, zeigt nie An/Aus), big (großer Hauptknopf),
      arrow (Pfeilsymbol, dazu dir: up | down | left | right | up2 | down2), pill (schmale Leiste).
      Ohne look: normale Kachel. Nicht mit slider/states/segment kombinierbar.

Seiten-Typen: grid (Tasten fließen nach Gruppen), shield (Zonen), free (Raster mit cols x rows Zellen,
Standard 12 x 8, bis 24 x 16; jede Taste mit x, y, w, h in Zellen).
Seiten-Feld section (optional, Text 1-20 Zeichen): Seitengruppe. Gibt es Abschnitte, zeigt das Tablet sie als
obere Reiter und darunter die Seiten des gewählten Abschnitts; Seiten ohne section kommen unter "Weitere".

Nicht-interaktive Elemente (nur auf free-Seiten, in buttons[], erkennbar an kind; ohne key/mode/...; sie zählen
nicht als Tasten, der Hub kennt sie nicht):
  {"kind": "frame", "id", "label" (Titel, optional, bis 40 Zeichen), "x", "y", "w", "h"} - Bereich mit Rahmen und
      Titel oben; liegt hinter den Tasten.
  {"kind": "text", "id", "label" (1-120 Zeichen), "x", "y", "w", "h", "align": left|center|right, "size": s|m|l}
"""
import re
import json
import os
import tempfile
import time

from . import keys

MODES = {"tap", "hold-confirm", "toggle", "double"}
STYLES = {"", "accent", "danger"}
PAGE_TYPES = {"grid", "shield", "free"}
GRID_COLS, GRID_ROWS = (2, 24), (2, 16)   # erlaubte Rastergrößen freier Seiten
ZONES = {"front", "back", "left", "right", "top", "bottom", "reset"}
MAX_MACRO = 50
STATE_COUNT = (2, 6)
STATE_LABEL_MAX = 20
SLIDER_STEPS = (2, 20)
SEGMENT_COUNT = (2, 6)
LOOKS = {"switch", "big", "arrow", "pill"}
ARROW_DIRS = {"up", "down", "left", "right", "up2", "down2"}
KINDS = {"frame", "text"}
KIND_FIELDS = {"frame": {"kind", "id", "label", "x", "y", "w", "h"},
               "text": {"kind", "id", "label", "x", "y", "w", "h", "align", "size"}}
KIND_LABEL_MAX = {"frame": 40, "text": 120}
TEXT_ALIGN = {"left", "center", "right"}
TEXT_SIZE = {"s", "m", "l"}
SECTION_MAX = 20


def _check_key(text, where):
    try:
        keys.parse_combo(str(text))
    except KeyError as e:
        _err(f"{where}: unbekannte Taste {e}")


def validate_states(b, where):
    st = b["states"]
    if not isinstance(st, list) or not STATE_COUNT[0] <= len(st) <= STATE_COUNT[1]:
        _err(f"{where}: states muss eine Liste mit {STATE_COUNT[0]}-{STATE_COUNT[1]} Zuständen sein")
    for i, s in enumerate(st):
        w = f"{where}: Zustand {i + 1}"
        if not isinstance(s, dict) or not set(s) <= {"label", "key"}:
            _err(f"{w} muss {{label, key}} sein")
        if not isinstance(s.get("label"), str) or not 1 <= len(s["label"]) <= STATE_LABEL_MAX:
            _err(f"{w}: label 1-{STATE_LABEL_MAX} Zeichen")
        if s.get("key") not in (None, ""):
            if not isinstance(s["key"], str):
                _err(f"{w}: key muss Text sein")
            _check_key(s["key"], w)
    if any(k in b for k in ("macro", "open", "page", "slider")):
        _err(f"{where}: states nicht mit macro/open/page/slider kombinierbar")
    if b.get("mode", "tap") != "tap":
        _err(f"{where}: states nur mit mode tap")
    if not (b.get("key") or all(s.get("key") for s in st)):
        _err(f"{where}: states braucht key an der Taste oder an jedem Zustand")


def validate_segment(b, where):
    sg = b["segment"]
    if not isinstance(sg, list) or not SEGMENT_COUNT[0] <= len(sg) <= SEGMENT_COUNT[1]:
        _err(f"{where}: segment muss eine Liste mit {SEGMENT_COUNT[0]}-{SEGMENT_COUNT[1]} Teilen sein")
    for i, s in enumerate(sg):
        w = f"{where}: Teil {i + 1}"
        if not isinstance(s, dict) or set(s) != {"label", "key"}:
            _err(f"{w} muss {{label, key}} sein")
        if not isinstance(s["label"], str) or not 1 <= len(s["label"]) <= STATE_LABEL_MAX:
            _err(f"{w}: label 1-{STATE_LABEL_MAX} Zeichen")
        if not isinstance(s["key"], str) or not s["key"]:
            _err(f"{w}: key braucht eine Taste")
        _check_key(s["key"], w)
    if any(k in b for k in ("macro", "open", "page", "states", "slider")) or b.get("key") not in (None, ""):
        _err(f"{where}: segment ohne key/macro/open/page/states/slider")
    if b.get("mode", "tap") != "tap" or b.get("hold"):
        _err(f"{where}: segment nur mit mode tap, ohne hold")


def validate_look(b, where):
    look = b.get("look")
    if "look" in b and look not in LOOKS:
        _err(f"{where}: look muss {sorted(LOOKS)} sein")
    if "look" in b and any(k in b for k in ("slider", "states", "segment")):
        _err(f"{where}: look nicht mit slider/states/segment kombinierbar")
    if look == "arrow":
        if b.get("dir") not in ARROW_DIRS:
            _err(f"{where}: look arrow braucht dir {sorted(ARROW_DIRS)}")
    elif "dir" in b:
        _err(f"{where}: dir nur mit look arrow")


def validate_decor(b, where, ptype, cols, rows):
    """frame/text (kind): nicht-interaktive Elemente, nur auf freien Seiten."""
    kind = b["kind"]
    if kind not in KINDS:
        _err(f"{where}: kind muss {sorted(KINDS)} sein")
    if ptype != "free":
        _err(f"{where}: {kind} nur auf freien Seiten (type free)")
    extra = set(b) - KIND_FIELDS[kind]
    if extra:
        _err(f"{where}: {kind} kennt kein Feld {sorted(extra)}")
    lab, mx = b.get("label"), KIND_LABEL_MAX[kind]
    if lab is None and kind == "frame":
        lab = ""
    if not isinstance(lab, str) or len(lab) > mx or (kind == "text" and not lab.strip()):
        _err(f"{where}: label {0 if kind == 'frame' else 1}-{mx} Zeichen")
    if kind == "text":
        if b.get("align", "left") not in TEXT_ALIGN:
            _err(f"{where}: align muss {sorted(TEXT_ALIGN)} sein")
        if b.get("size", "m") not in TEXT_SIZE:
            _err(f"{where}: size muss {sorted(TEXT_SIZE)} sein")
    _check_cells(b, where, cols, rows)


def _check_cells(b, where, cols, rows):
    x, y, w, h = (b.get(k) for k in ("x", "y", "w", "h"))
    if not all(type(v) is int for v in (x, y, w, h)) or not (
            0 <= x and 0 <= y and w >= 1 and h >= 1 and x + w <= cols and y + h <= rows):
        _err(f"{where}: x, y, w, h müssen ins Raster {cols}x{rows} passen")


def validate_slider(b, where):
    sl = b["slider"]
    if not isinstance(sl, dict) or set(sl) != {"up", "down", "steps"}:
        _err(f"{where}: slider muss {{up, down, steps}} sein")
    if type(sl["steps"]) is not int or not SLIDER_STEPS[0] <= sl["steps"] <= SLIDER_STEPS[1]:
        _err(f"{where}: slider.steps {SLIDER_STEPS[0]}-{SLIDER_STEPS[1]}")
    for d in ("up", "down"):
        if not isinstance(sl[d], str) or not sl[d]:
            _err(f"{where}: slider.{d} braucht eine Taste")
        _check_key(sl[d], where)
    if any(b.get(k) not in (None, "") for k in ("key", "macro", "open", "page", "states"))             or any(k in b for k in ("macro", "open", "page", "states")):
        _err(f"{where}: slider ohne key/macro/open/page/states")
    if b.get("mode", "tap") != "tap" or b.get("hold"):
        _err(f"{where}: slider nur mit mode tap, ohne hold")


def button_for_press(btn, msg):
    """Taste, die ein "down" vom Tablet auslöst (Snapshot-Vorlage), oder None.
    states: msg["state"] wählt den Tastendruck des Zustands (ungültig/ohne key: Taste selbst).
    slider: msg["dir"] up/down wählt slider.up/down; ohne gültiges dir None.
    segment: msg["seg"] (Index) wählt den Teil; ohne gültigen Index None."""
    sg = btn.get("segment")
    if isinstance(sg, list):
        i = msg.get("seg")
        if type(i) is int and 0 <= i < len(sg) and isinstance(sg[i], dict) and sg[i].get("key"):
            return dict(btn, key=sg[i]["key"])
        return None
    sl = btn.get("slider")
    if isinstance(sl, dict):
        d = msg.get("dir")
        k = sl.get(d) if d in ("up", "down") else None
        return dict(btn, key=k) if k else None
    st = btn.get("states")
    if isinstance(st, list):
        i = msg.get("state")
        if type(i) is int and 0 <= i < len(st) and isinstance(st[i], dict) and st[i].get("key"):
            return dict(btn, key=st[i]["key"])
    return dict(btn)


def needed_keys(btn):
    """Alle Tasten, die der Hub für diese Taste (slider/states/segment) braucht; None bei anderen Tasten."""
    sg = btn.get("segment")
    if isinstance(sg, list):
        return [s.get("key") if isinstance(s, dict) else None for s in sg]
    sl = btn.get("slider")
    if isinstance(sl, dict):
        return [sl.get("up"), sl.get("down")]
    st = btn.get("states")
    if isinstance(st, list):
        return [(s.get("key") or btn.get("key")) if isinstance(s, dict) else None for s in st]
    return None


def _err(msg):
    raise ValueError(msg)


def validate_macro(steps, where):
    if not isinstance(steps, list) or not 0 < len(steps) <= MAX_MACRO:
        _err(f"{where}: macro muss eine Liste mit 1-{MAX_MACRO} Schritten sein")
    for i, st in enumerate(steps):
        if not isinstance(st, dict) or len(st) != 1:
            _err(f"{where}: Schritt {i + 1} muss genau ein Feld haben")
        (k, v), = st.items()
        if k == "key":
            try:
                keys.parse_combo(str(v))
            except KeyError as e:
                _err(f"{where}: Schritt {i + 1}: unbekannte Taste {e}")
        elif k == "text":
            if not isinstance(v, str) or not 0 < len(v) <= 500:
                _err(f"{where}: Schritt {i + 1}: text 1-500 Zeichen")
        elif k == "wait":
            if not isinstance(v, int) or not 0 <= v <= 5000:
                _err(f"{where}: Schritt {i + 1}: wait 0-5000 ms")
        elif k == "media":
            if v not in keys.MEDIA_VK:
                _err(f"{where}: Schritt {i + 1}: media muss eins von {sorted(keys.MEDIA_VK)} sein")
        else:
            _err(f"{where}: Schritt {i + 1}: unbekannter Schritt '{k}'")


OPEN_URL = re.compile(r"(?i)^https?://[^\s]+$")
# absolut mit Laufwerk; kein UNC, kein ":" danach (Alternate Data Streams). Verbundene Netzlaufwerke
# (Z:\) sind erlaubt - das Ziel trägt der Benutzer selbst am PC ein. Argumente: per .lnk/.bat.
OPEN_PATH = re.compile(r'^[A-Za-z]:\\[^<>"|?*:\r\n]+$')


def validate_open(target, where):
    if not isinstance(target, str) or len(target) > 1024 or not (
            OPEN_URL.match(target) or OPEN_PATH.match(target)):
        _err(f"{where}: open muss eine http(s)-URL oder ein absoluter Pfad (C:\\...) sein")


def validate_layout(layout):
    """Prüft das ganze Layout; gibt {button-id: button} zurück oder wirft ValueError."""
    if not isinstance(layout, dict) or not isinstance(layout.get("pages"), list) or not layout["pages"]:
        _err("Layout braucht eine nicht-leere Liste 'pages'")
    hold = layout.get("holdMs", 1000)
    if not isinstance(hold, int) or not 200 <= hold <= 5000:
        _err("holdMs muss 200-5000 sein")
    buttons, page_ids, links, decor_ids = {}, set(), [], set()
    for page in layout["pages"]:
        pid = page.get("id") if isinstance(page, dict) else None
        if not isinstance(pid, str) or not pid or pid in page_ids:
            _err(f"Seite ohne/mit doppelter id: {pid!r}")
        page_ids.add(pid)
        if not isinstance(page.get("title"), str) or not isinstance(page.get("buttons"), list):
            _err(f"Seite {pid}: title und buttons nötig")
        if page.get("type", "grid") not in PAGE_TYPES:
            _err(f"Seite {pid}: type muss grid, shield oder free sein")
        if "section" in page and not (isinstance(page["section"], str) and page["section"].strip()
                                      and len(page["section"]) <= SECTION_MAX):
            _err(f"Seite {pid}: section 1-{SECTION_MAX} Zeichen")
        cols, rows = page.get("cols", 12), page.get("rows", 8)
        if page.get("type") == "free" and not (
                type(cols) is int and GRID_COLS[0] <= cols <= GRID_COLS[1]
                and type(rows) is int and GRID_ROWS[0] <= rows <= GRID_ROWS[1]):
            _err(f"Seite {pid}: cols {GRID_COLS[0]}-{GRID_COLS[1]}, rows {GRID_ROWS[0]}-{GRID_ROWS[1]}")
        for b in page["buttons"]:
            bid = b.get("id") if isinstance(b, dict) else None
            where = f"Taste {bid!r} (Seite {pid})"
            if not isinstance(bid, str) or not bid:
                _err(f"Seite {pid}: Taste ohne id")
            if bid in buttons or bid in decor_ids:
                _err(f"{where}: id doppelt")
            if "kind" in b:
                validate_decor(b, where, page.get("type"), cols, rows)
                decor_ids.add(bid)
                continue
            if not isinstance(b.get("label"), str):
                _err(f"{where}: label fehlt")
            if b.get("mode", "tap") not in MODES:
                _err(f"{where}: mode muss {sorted(MODES)} sein")
            if "hold" in b and not isinstance(b["hold"], bool):
                _err(f"{where}: hold muss true/false sein")
            if b.get("style", "") not in STYLES:
                _err(f"{where}: style muss accent/danger oder leer sein")
            if "key" in b and b["key"] not in (None, ""):
                try:
                    keys.parse_combo(str(b["key"]))
                except KeyError as e:
                    _err(f"{where}: unbekannte Taste {e}")
            if "states" in b:
                validate_states(b, where)
            if "slider" in b:
                validate_slider(b, where)
            if "segment" in b:
                validate_segment(b, where)
            if "look" in b or "dir" in b:
                validate_look(b, where)
            if "macro" in b:
                validate_macro(b["macro"], where)
            if "open" in b:
                validate_open(b["open"], where)
            if page.get("type") == "shield" and b.get("zone") not in ZONES:
                _err(f"{where}: zone muss {sorted(ZONES)} sein")
            if page.get("type") == "free":
                _check_cells(b, where, cols, rows)
            if "page" in b:
                if not isinstance(b["page"], str) or any(k in b for k in ("key", "macro", "open")) \
                        or b.get("mode", "tap") != "tap" or b.get("hold"):
                    _err(f"{where}: page (Seiten-Link) ohne key/macro/open, mode tap, ohne hold")
                links.append((where, b["page"]))
            buttons[bid] = b
    for where, target in links:
        if target not in page_ids:
            _err(f"{where}: Seiten-Link auf unbekannte Seite {target!r}")
    return buttons


def format_layout(layout):
    """Lesbares JSON: eine Zeile pro Taste (gut von Hand zu bearbeiten und in Git-Diffs)."""
    def one(o):
        return json.dumps(o, ensure_ascii=False, separators=(", ", ": "), allow_nan=False)
    top = {k: v for k, v in layout.items() if k != "pages"}
    lines = ["{"] + [f"  {json.dumps(k)}: {one(v)}," for k, v in top.items()] + ['  "pages": [']
    for pi, page in enumerate(layout["pages"]):
        head = {k: v for k, v in page.items() if k != "buttons"}
        lines.append("    {" + one(head)[1:-1] + ', "buttons": [')
        for bi, b in enumerate(page["buttons"]):
            lines.append("      " + one(b) + ("," if bi < len(page["buttons"]) - 1 else ""))
        lines.append("    ]}" + ("," if pi < len(layout["pages"]) - 1 else ""))
    lines += ["  ]", "}"]
    text = "\n".join(lines) + "\n"
    if json.loads(text) != layout:   # Formatierung darf den Inhalt nie verändern
        raise ValueError("Layout lässt sich nicht verlustfrei speichern")
    return text


def save_layout(path, layout):
    """Prüfen, dann atomar schreiben (temporäre Datei + Umbenennen) - nie eine halbe Datei."""
    validate_layout(layout)
    data = format_layout(layout)
    fd, tmp = tempfile.mkstemp(prefix=".layout-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
        for attempt in range(5):   # Virenscanner/Indexer halten die Datei manchmal kurz offen
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
