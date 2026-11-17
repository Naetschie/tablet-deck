"""Auto-Layout: semantische Vorlage (Bereiche, Gruppen, Aktionen - ohne Koordinaten) -> Panel-Layout.

Semantische Vorlage:
  {"title": "...", "holdMs": 1000 (optional), "sections": [
     {"title": "Flug & Kampf", "areas": [
        {"title": "Energie", "items": [ITEM, ...], "shield": {"front": TASTE, "back": ..., "left": ..., "right": ...,
                                                             "reset": ...} (optional)}]}]}
  TASTE = {"label": "...", "sc" | "action": "<Spielaktion>", "key" (Rückfall, optional), "style", "mode", "hold"}
  ITEM  = TASTE + "size": m (Standard, 2 x 2 Felder) | l (breit, 4 x 2) | xl (groß, 4 x 4, look big) | pill
          (schmale Leiste 4 x 1), optional "look": "arrow" + "dir"
        | {"pair": [TASTE, TASTE], "label"?} - Pfeilpaar ▼▲ (zwei Tasten, dirs ["down", "up"] oder eigene "dirs")

Darstellung (style):
  "areas": jede Section wird eine freie Seite 24 x 16 mit Rahmen je Bereich (Cockpit-Stil). Bereiche werden in
           Reihen gepackt, Breiten so gewählt, dass möglichst wenig Fläche frei bleibt; übriger Platz macht die
           Tasten größer. Passt eine Section nicht auf eine Seite, wird sie auf mehrere Seiten verteilt.
  "grid":  jede Section wird eine Kachel-Seite (type grid), Bereiche sind Gruppen; Schilde eigene Seite.
"""
import itertools
import re
import time

from .layout import validate_layout

COLS, ROWS = 24, 16
SIZES = {"m": (2, 2), "l": (4, 2), "xl": (4, 4), "pill": (4, 1)}
INNER_WIDTHS = (4, 6, 8, 10, 12, 14, 22)   # Innenbreite eines Bereichs (gerade, Rand je 1 Feld)
SHIELD_W, SHIELD_H = 10, 7
TASTE_FIELDS = ("label", "sc", "action", "key", "style", "mode", "hold", "look", "dir", "press_ms")
MAX_COMBOS = 50000
MAX_SECTIONS, MAX_AREAS, MAX_ITEMS = 12, 12, 60   # Obergrenzen (Vorlagen und KI-Ausgaben)
TIME_BUDGET_S = 0.5   # Suche je Anordnung; danach gilt die beste bisher gefundene


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
               .replace("ß", "ss")).strip("-")
    return s[:30] or "x"


class _Ids:
    def __init__(self):
        self.used = set()

    def take(self, base):
        base = _slug(base)
        i, n = base, 2
        while i in self.used:
            i, n = f"{base}-{n}", n + 1
        self.used.add(i)
        return i


def _button(t, ids, prefix):
    b = {k: t[k] for k in TASTE_FIELDS if k in t}
    b["id"] = ids.take(prefix + "-" + (t.get("sc") or t.get("action") or t.get("label", "")))
    return b


def _check_spec(spec):
    """Aufbau prüfen und Fehler mit Ort melden (statt Python-Interna); Obergrenzen gegen lange Rechenzeiten."""
    secs = spec.get("sections")
    if not isinstance(secs, list) or not secs or len(secs) > MAX_SECTIONS:
        raise ValueError(f"Vorlage braucht 1-{MAX_SECTIONS} sections")
    for si, s in enumerate(secs):
        if not isinstance(s, dict) or not isinstance(s.get("title"), str) or not s["title"].strip():
            raise ValueError(f"Section {si + 1}: title fehlt")
        areas = s.get("areas")
        if not isinstance(areas, list) or len(areas) > MAX_AREAS:
            raise ValueError(f"{s['title']!r}: areas muss eine Liste mit höchstens {MAX_AREAS} Bereichen sein")
        for a in areas:
            if not isinstance(a, dict):
                raise ValueError(f"{s['title']!r}: Bereich muss ein Objekt sein")
            where = f"{s['title']!r} / {a.get('title')!r}"
            items = a.get("items", [])
            if not isinstance(items, list) or len(items) > MAX_ITEMS:
                raise ValueError(f"{where}: items muss eine Liste mit höchstens {MAX_ITEMS} Einträgen sein")
            for it in items:
                if not isinstance(it, dict):
                    raise ValueError(f"{where}: jeder Eintrag in items muss ein Objekt sein")
                for tt in (it["pair"] if isinstance(it.get("pair"), list) else [it]):
                    if not isinstance(tt, dict):
                        raise ValueError(f"{where}: Taste im Paar muss ein Objekt sein")
            sh = a.get("shield")
            if sh is not None and not (isinstance(sh, dict) and sh and all(isinstance(v, dict) for v in sh.values())):
                raise ValueError(f"{where}: shield muss Zonen mit Tasten enthalten")


def _area_items(area):
    """Bereich -> Liste von Bausteinen (w, h, [Tasten mit Zusatz])."""
    out = []
    for it in area.get("items", []):
        if "pair" in it:
            if not (isinstance(it["pair"], list) and len(it["pair"]) == 2):
                raise ValueError(f"{area.get('title')!r}: pair braucht genau zwei Tasten")
            dirs = it.get("dirs", ["down", "up"])
            if not (isinstance(dirs, list) and len(dirs) == 2):
                raise ValueError(f"{area.get('title')!r}: dirs braucht genau zwei Richtungen")
            out.append(("pair", [dict(t, look="arrow", dir=d) for t, d in zip(it["pair"], dirs)]))
        else:
            size = it.get("size", "m")
            if size not in SIZES:
                raise ValueError(f"{area.get('title')!r}: size muss {sorted(SIZES)} sein")
            t = dict(it)
            t.pop("size", None)
            if size == "xl" and "look" not in t:
                t["look"] = "big"
            if size == "pill" and "look" not in t:
                t["look"] = "pill"
            out.append((size, [t]))
    return out


def _unit_size(kind):
    return (4, 2) if kind == "pair" else SIZES[kind]


def _pack_area(items, inner):
    """Regalpacken der Bausteine in die Innenbreite: [(Reihe: [(kind, tasten, x, w, h)], Reihenhöhe)] oder None."""
    rows, cur, x = [], [], 0
    for kind, ts in items:
        w, h = _unit_size(kind)
        if w > inner:
            return None
        # Pfeilpaare nie zu zweit in einer Zeile (sonst liest man „Waffen ▼▲ Schilde ▼▲“ als eine Gruppe)
        if x + w > inner or (kind == "pair" and any(u[0] == "pair" for u in cur)):
            rows.append(cur)
            cur, x = [], 0
        cur.append([kind, ts, x, w, h])
        x += w
    if cur:
        rows.append(cur)
    return [(r, max(u[4] for u in r)) for r in rows]


def _area_box(area, inner):
    """(Rahmenbreite, Rahmenhöhe, gepackte Reihen) für eine Innenbreite; None wenn unpassend."""
    items = _area_items(area)
    shield = area.get("shield")
    if shield and inner + 2 < SHIELD_W:
        return None
    rows = _pack_area(items, inner) if items else []
    if rows is None:
        return None
    h = sum(rh for _, rh in rows) + (SHIELD_H if shield else 0)
    return inner + 2, h + 2, rows


def _skyline(boxes):
    """Bereiche der Reihe nach an die niedrigste freie Stelle (dann links) setzen: [(x, y)] oder None."""
    sky, pos = [0] * COLS, []
    for bw, bh, _ in boxes:
        best = None
        for x in range(0, COLS - bw + 1):
            y = max(sky[x:x + bw])
            if y + bh <= ROWS and (best is None or (y, x) < best):
                best = (y, x)
        if best is None:
            return None
        y, x = best
        pos.append((x, y))
        for c in range(x, x + bw):
            sky[c] = y + bh
    return pos


def _expand(rects):
    """Rahmen in freie Flächen dehnen (nach rechts, dann nach unten), bis nichts mehr frei ist."""
    occ = [[-1] * COLS for _ in range(ROWS)]
    for i, (x, y, w, h) in enumerate(rects):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                occ[yy][xx] = i
    rects = [list(r) for r in rects]
    changed = True
    while changed:
        changed = False
        for i, r in enumerate(rects):
            x, y, w, h = r
            if x + w < COLS and all(occ[yy][x + w] == -1 for yy in range(y, y + h)):
                for yy in range(y, y + h):
                    occ[yy][x + w] = i
                r[2] += 1
                changed = True
            x, y, w, h = r
            if y + h < ROWS and all(occ[y + h][xx] == -1 for xx in range(x, x + w)):
                for xx in range(x, x + w):
                    occ[y + h][xx] = i
                r[3] += 1
                changed = True
    holes = sum(row.count(-1) for row in occ)
    return [tuple(r) for r in rects], holes


def _best_arrangement(areas, first=False):
    """Innenbreiten je Bereich so wählen, dass alles auf eine Seite passt und wenig frei bleibt; None = passt nicht."""
    options = []
    for a in areas:
        opts, last_h = [], None
        for inner in INNER_WIDTHS:
            box = _area_box(a, inner)
            # nur Breiten, die den Bereich niedriger machen (breiter ohne Gewinn erledigt das Dehnen)
            if box and (last_h is None or box[1] < last_h):
                opts.append((inner, box))
                last_h = box[1]
        if not opts:
            return None
        options.append(opts)
    # passt rechnerisch gar nicht (schon die kleinsten Bereiche zu groß): Suche sparen
    if sum(min(box[0] * box[1] for _, box in opts) for opts in options) > COLS * ROWS:
        return None
    best, n, start = None, 0, time.monotonic()
    idx = list(range(len(areas)))
    for combo in itertools.product(*options):
        n += 1
        # Zeitbudget immer: ohne Fund bis dahin gilt "passt nicht" (Bereich kommt auf die nächste Seite)
        if n > MAX_COMBOS or time.monotonic() - start > TIME_BUDGET_S:
            break
        boxes = [box for _, box in combo]
        # Packreihenfolge: wie vorgegeben, sonst hohe/breite/große Bereiche zuerst (Skyline hängt davon ab)
        orders = [idx, sorted(idx, key=lambda i: -boxes[i][1]), sorted(idx, key=lambda i: -boxes[i][0]),
                  sorted(idx, key=lambda i: -boxes[i][0] * boxes[i][1])]
        for oi, order in enumerate(orders):
            pos = _skyline([boxes[i] for i in order])
            if pos is None:
                continue
            placed = [None] * len(boxes)
            for i, (x, y) in zip(order, pos):
                placed[i] = (x, y, boxes[i][0], boxes[i][1])
            rects, holes = _expand(placed)
            # Dehnung = Fläche, die Tasten nur größer macht; möglichst wenig, keine Löcher, vorgegebene Reihenfolge
            stretch = sum(w * h for _, _, w, h in rects) - sum(bw * bh for bw, bh, _ in boxes)
            score = (holes, stretch, oi)
            if best is None or score < best[0]:
                best = (score, combo, rects)
            break   # erste passende Reihenfolge genügt
        if first and best:
            return best   # nur die Frage „passt es?“ (Aufteilen auf Seiten)
    return best


def _place_section(section, areas, ids, page_id):
    best = _best_arrangement(areas)
    if best is None:
        return None
    _, combo, rects = best
    buttons = []
    for area, (inner, (bw, bh, rows)), (x, y, w, h) in zip(areas, combo, rects):
        buttons.extend(_place_area(area, rows, x, y, w, h, ids, page_id))
    return {"id": page_id, "title": section["title"], "section": section["title"], "type": "free",
            "cols": COLS, "rows": ROWS, "buttons": buttons}


def _grow(sizes, extra, cap=None):
    """extra Felder reihum auf die Bausteine verteilen (größer machen statt Lücke); cap: Höchstgröße je Baustein.
    Gibt (Größen, nicht verteilter Rest) zurück."""
    sizes = list(sizes)
    caps = cap or [10 ** 6] * len(sizes)
    while extra > 0 and any(s < c for s, c in zip(sizes, caps)):
        for i in range(len(sizes)):
            if extra > 0 and sizes[i] < caps[i]:
                sizes[i] += 1
                extra -= 1
    return sizes, extra


def _place_area(area, rows, fx, fy, fw, fh, ids, page_id):
    out = [{"kind": "frame", "id": ids.take(f"f-{page_id}-{area.get('title', '')}"), "label": area.get("title", ""),
            "x": fx, "y": fy, "w": fw, "h": fh}]
    inner_w, y = fw - 2, fy + 1
    content_h = fh - 2
    if area.get("shield"):
        sh = area["shield"]
        out.append({"kind": "shield", "id": ids.take(f"sh-{page_id}"), "x": fx, "y": y, "w": fw, "h": SHIELD_H})
        for zone in ("front", "back", "left", "right", "reset"):
            if zone in sh:
                out.append(dict(_button(sh[zone], ids, page_id), zone=zone))
        y += SHIELD_H
        content_h -= SHIELD_H
    if not rows:
        return out
    # freie Zeilen: Reihen mit normalen Tasten werden höher (Leisten bleiben schmal)
    base = [rh for _, rh in rows]
    extra = content_h - sum(base)
    growable = [i for i, (r, _) in enumerate(rows) if any(u[0] != "pill" for u in r)]
    add = [0] * len(rows)
    for k in range(max(0, extra)):
        if growable:
            add[growable[k % len(growable)]] += 1
    for (row, rh), plus in zip(rows, add):
        # freie Spalten: Bausteine der Reihe breiter
        used = sum(u[3] for u in row)
        # breiter, aber höchstens doppelt so breit wie vorgesehen; Rest bleibt links/rechts frei (zentriert)
        widths, rest = _grow([u[3] for u in row], inner_w - used, [2 * u[3] for u in row])
        x = fx + 1 + rest // 2
        for (kind, ts, _, _, h), w in zip(row, widths):
            hh = rh + plus if kind != "pill" else h
            if kind == "pair":
                w1 = w // 2
                for t, (bx, bwid) in zip(ts, ((x, w1), (x + w1, w - w1))):
                    out.append(dict(_button(t, ids, page_id), x=bx, y=y, w=bwid, h=hh))
            else:
                out.append(dict(_button(ts[0], ids, page_id), x=x, y=y, w=w, h=hh))
            x += w
        y += rh + plus
    return out


def _split_areas(areas):
    """Bereiche auf Seiten verteilen: so viele wie passen, Rest auf die nächste Seite."""
    pages, cur = [], []
    for a in areas:
        # höchstens eine Schiffsansicht je Seite (Zonen sind je Seite eindeutig)
        two_shields = a.get("shield") and any(c.get("shield") for c in cur)
        if cur and (two_shields or _best_arrangement(cur + [a], first=True) is None):
            pages.append(cur)
            cur = []
        cur.append(a)
    if cur:
        pages.append(cur)
    return pages


def layout_areas(spec):
    ids, pages = _Ids(), []
    for si, section in enumerate(spec["sections"]):
        groups = _split_areas(section.get("areas", []))
        for gi, areas in enumerate(groups):
            pid = ids.take(section["title"] + (f"-{gi + 1}" if gi else ""))
            page = _place_section(section, areas, ids, pid)
            if page is None:
                raise ValueError(f"Bereich passt nicht auf eine Seite: {areas[0].get('title')!r}")
            if len(groups) > 1:
                page["title"] = f"{section['title']} {gi + 1}"
            pages.append(page)
    return pages


def layout_grid(spec):
    ids, pages = _Ids(), []
    for section in spec["sections"]:
        pid = ids.take(section["title"])
        buttons, extra = [], []
        for area in section.get("areas", []):
            for kind, ts in _area_items(area):
                for t in ts:
                    b = _button(t, ids, pid)
                    b["group"] = area.get("title", "")
                    if kind in ("l", "xl"):
                        b["wide"] = True
                    if b.get("look") == "pill":
                        del b["look"]
                    buttons.append(b)
            if area.get("shield"):
                sid = ids.take(pid + "-schilde")
                extra.append({"id": sid, "title": area.get("title") or "Schilde", "section": section["title"],
                              "type": "shield", "buttons": [dict(_button(t, ids, sid), zone=z)
                                                            for z, t in area["shield"].items()]})
        if buttons:
            pages.append({"id": pid, "title": section["title"], "section": section["title"], "buttons": buttons})
        pages.extend(extra)   # Schildseiten hinter die Seite ihres Bereichs
    return pages


def build(spec, style="areas"):
    """Semantische Vorlage -> geprüftes Panel-Layout."""
    if not isinstance(spec, dict):
        raise ValueError("Vorlage muss ein Objekt sein")
    if not isinstance(style, str) or style not in ("areas", "grid"):
        raise ValueError("Darstellung muss areas oder grid sein")
    _check_spec(spec)
    try:
        pages = layout_areas(spec) if style == "areas" else layout_grid(spec)
    except (KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"Vorlage fehlerhaft ({type(e).__name__}: {e})") from None
    out = {"title": spec.get("title", "Panel"), "pages": pages}
    if "holdMs" in spec:
        out["holdMs"] = spec["holdMs"]
    validate_layout(out)
    return out


def is_semantic(t):
    return isinstance(t, dict) and "sections" in t and "pages" not in t
