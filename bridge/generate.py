"""Panel automatisch erzeugen: Spielvorlage + eigene Tastenbelegung -> Panel-Entwurf.

Vorlagen: templates/<spiel>/<vorlage>.json im Panel-Format (title, pages, buttons) oder semantisch (title,
sections -> areas -> items, ohne Koordinaten; siehe autolayout.py), dann ordnet das Auto-Layout an - als
Bereiche im Raster ("areas") oder als Kacheln ("grid"). Tasten nennen ihre Spielaktion in "sc" (Star Citizen)
bzw. "action" und dürfen eine Standardtaste "key" mitbringen.

Reihenfolge für die Taste: eigene Belegung (Adapter) > Taste aus der Vorlage > keine (Taste bleibt
unbelegt, mit Vorschlag einer freien Kombination). Gespeichert wird erst im Editor.
"""
import copy
import json
import logging
import re
from pathlib import Path

from . import bindings
from .autolayout import build as auto_build, is_semantic
from .layout import validate_layout

STYLES = ("areas", "grid")   # Darstellung semantischer Vorlagen

log = logging.getLogger("generate")
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


_LIST_CACHE = {}   # (Datei, Änderungszeit) -> Eintrag: semantische Vorlagen nicht bei jedem Auflisten anordnen


def list_templates(root, game):
    """[{id, title, pages}] der Vorlagen eines Spiels (fehlerhafte Dateien werden übersprungen)."""
    d = Path(root) / "templates" / game
    if not ID.fullmatch(game or "") or not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        if not ID.fullmatch(f.stem):
            continue
        try:
            ck = (str(f), f.stat().st_mtime_ns)
            if ck in _LIST_CACHE:
                out.append(_LIST_CACHE[ck])
                continue
            t = json.loads(f.read_text(encoding="utf-8"))
            semantic = is_semantic(t)
            lay = auto_build(t) if semantic else t
            validate_layout(lay)
            # semantisch: Auswahl nach Bereichen (die Seiten entstehen erst je nach Darstellung)
            pages = ([{"id": s["title"], "title": s["title"]} for s in t["sections"]] if semantic
                     else [{"id": p["id"], "title": p["title"]} for p in lay["pages"]])
            entry = {"id": f.stem, "title": t.get("title", f.stem), "semantic": semantic, "pages": pages}
            _LIST_CACHE[ck] = entry
            out.append(entry)
        except (ValueError, OSError) as e:
            log.error("Vorlage %s/%s fehlerhaft: %s", game, f.stem, e)
    return out


def read_template(root, game, tid):
    """Vorlage roh (Panel-Format oder semantisch)."""
    if not (ID.fullmatch(game or "") and ID.fullmatch(tid or "")):
        raise ValueError("ungültige Vorlage")
    f = Path(root) / "templates" / game / f"{tid}.json"
    if not f.is_file():
        raise ValueError("Vorlage nicht gefunden")
    return json.loads(f.read_text(encoding="utf-8"))


def load_template(root, game, tid, style="areas"):
    """Vorlage als Panel-Layout; semantische Vorlagen ordnet das Auto-Layout im gewählten Stil an."""
    if not isinstance(style, str) or style not in STYLES:
        raise ValueError("Darstellung muss areas oder grid sein")
    t = read_template(root, game, tid)
    if is_semantic(t):
        return auto_build(t, style)
    validate_layout(t)
    return t


def _act(t):
    return t.get("sc") or t.get("action") if isinstance(t, dict) else None


def filter_spec(spec, sections=None, skip=frozenset()):
    """Semantische Vorlage einschränken: nur die genannten Bereiche (Section-Titel), ohne Aktionen in skip
    (schon auf Joystick/Gamepad). Ein Pfeilpaar fällt nur weg, wenn beide Aktionen dort liegen; die
    Schiffsansicht bleibt immer. Rückgabe (Vorlage, weggelassen [{page, label, action}])."""
    out, dropped = copy.deepcopy(spec), []
    if sections is not None:
        want = set(sections)
        out["sections"] = [s for s in out["sections"] if s.get("title") in want]
    for s in out["sections"]:
        for a in s.get("areas", []):
            keep = []
            for it in a.get("items", []):
                acts = [_act(x) for x in it["pair"]] if isinstance(it.get("pair"), list) else [_act(it)]
                if skip and acts and all(x in skip for x in acts):
                    for x, lab in zip(acts, it["pair"] if "pair" in it else [it]):
                        dropped.append({"page": s["title"], "label": lab.get("label", ""), "action": x})
                    continue
                keep.append(it)
            a["items"] = keep
        s["areas"] = [a for a in s.get("areas", []) if a.get("items") or a.get("shield")]
    out["sections"] = [s for s in out["sections"] if s["areas"]]
    if not out["sections"]:
        raise ValueError("nichts übrig – keine Seite gewählt oder alles liegt schon auf dem Eingabegerät")
    return out, dropped


def generate(template, result=None, pages=None):
    """Entwurf erzeugen. result: bindings.Result oder None (nur Vorlagentasten). pages: Seiten-ids, die
    übernommen werden (None = alle). Gibt (layout, bericht) zurück; der Bericht hat eine Zeile pro Taste."""
    layout = copy.deepcopy(template)
    if pages is not None:
        layout["pages"] = [p for p in layout["pages"] if p["id"] in set(pages)]
        if not layout["pages"]:
            raise ValueError("keine Seite ausgewählt")
    free = list(result.free) if result else []
    report = []
    for page in layout["pages"]:
        for b in page["buttons"]:
            if "kind" in b:
                continue   # Rahmen, Beschriftung, Schiffsansicht: keine Tasten
            act = b.get("sc") or b.get("action")
            row = {"id": b["id"], "label": b["label"], "page": page["title"], "page_id": page["id"], "action": act or "",
                   "key": b.get("key", ""), "source": "Vorlage" if b.get("key") else "", "note": ""}
            if "macro" in b or "open" in b:
                row["source"] = "Makro" if "macro" in b else "Öffnen"
            elif act and result is not None:
                bd = result.bindings.get(act)
                if bd is None:
                    row["note"] = "Aktion gibt es im Spiel nicht" + (" – Taste aus der Vorlage" if b.get("key") else "")
                elif bd.key:
                    b["key"] = row["key"] = bd.key
                    row["source"] = "Belegung"
                    if bd.hold:
                        b["hold"] = True
                    if bd.min_ms:
                        b["press_ms"] = bd.min_ms   # Spiel wertet erst lange Drücke (delayed_press)
                else:
                    b.pop("key", None)
                    row["key"], row["source"], row["note"] = "", "", bd.note
            if not b.get("key") and "macro" not in b and "open" not in b:
                row["source"] = "fehlt"
                if free:
                    row["suggest"] = free.pop(0)
            report.append(row)
    validate_layout(layout)
    return layout, report


MAX_AI_ACTIONS = 600


def ai_draft(root, games_entry, hint="", style_prompt=None, style="areas", skip_device=False):
    """KI-Vorlage (Claude-API) + eigene Belegung -> (layout, bericht, quelle). Mit Belegungsquelle bekommt die KI
    nur Aktionen, die eine Tastaturbelegung haben (begrenzt; mit skip_device ohne die auf Joystick/Gamepad);
    sie liefert eine semantische Vorlage, das Auto-Layout ordnet an (style), generate() setzt die echten Tasten
    ein. Tasten erfindet die KI nie - ohne Belegungsquelle bleiben sie leer."""
    if not isinstance(style, str) or style not in STYLES:
        raise ValueError("Darstellung muss areas oder grid sein")
    try:
        import anthropic
    except ImportError:
        raise ValueError("Paket anthropic fehlt (pip install -r requirements.txt)") from None
    from .ai_template import generate_template
    result, bind_msg = _read_bindings(root, games_entry)[:2]
    actions = None
    if result:
        skip = result.on_device if skip_device else frozenset()
        actions = [{"action": a, "key": b.key} for a, b in sorted(result.bindings.items())
                   if b.key and a not in skip][:MAX_AI_ACTIONS]
    try:
        spec = generate_template(root, games_entry.get("name", games_entry["id"]), actions=actions, hint=hint,
                                 style_prompt=style_prompt)
    except anthropic.AuthenticationError:
        raise ValueError("API-Schlüssel ungültig – im Editor unter ⚙ Einstellungen prüfen") from None
    except anthropic.RateLimitError:
        raise ValueError("API-Limit erreicht – später erneut versuchen") from None
    except anthropic.APIConnectionError:
        raise ValueError("Claude-API nicht erreichbar (Internet?)") from None
    except anthropic.APIStatusError as e:   # Meldungen der API enthalten keinen Schlüssel
        raise ValueError(f"Claude-API-Fehler {e.status_code}") from None
    except anthropic.APIError as e:          # z. B. unerwartete Antwortform
        raise ValueError(f"Claude-API-Fehler ({type(e).__name__})") from None
    except (KeyError, AttributeError, IndexError) as e:
        raise ValueError(f"KI-Antwort unbrauchbar ({type(e).__name__})") from None
    dropped = []
    if skip_device and result:
        # auch was die KI trotz Liste nennt (oder der geänderte Prompt verlangt), fällt weg
        spec, dropped = filter_spec(spec, None, result.on_device)
    layout, report = generate(auto_build(spec, style), result)
    report += [dict(d, id="", key="", page_id="", source="weggelassen", note="liegt schon auf Joystick/Gamepad")
               for d in dropped]
    source = "KI-Vorlage (Claude) + " + (result.source if result else bind_msg)
    if skip_device:
        source += (f" · {len(dropped)} Aktion(en) weggelassen (Joystick/Gamepad)" if result
                   else " · Filter Joystick/Gamepad ohne Belegungsquelle wirkungslos")
    return layout, report, source


def library_entry(games_entry):
    """Eintrag der Spielebibliothek (Steam, Epic, …) zu id oder Name: {name, dir, steam} oder {}."""
    try:
        from . import library
        names = {str(games_entry.get("id", "")).lower(), str(games_entry.get("name", "")).lower()}
        for g in library.scan_library():
            if str(g.get("id", "")).lower() in names or str(g.get("name", "")).lower() in names:
                return g
    except Exception:  # noqa: BLE001 - ohne Bibliothek nur die Benutzerordner durchsuchen
        pass
    return {}


LEARNED_FILE = "bindings_learned.json"   # im Lernmodus gefundene Steuerungsdateien {spiel-id: pfad} (lokal)
_LEARN_LOCK = __import__("threading").Lock()
_FALLBACK_CACHE = {}   # spiel-id -> (zeit, ergebnis): Suche nicht bei jedem Dialog/Entwurf neu
FALLBACK_TTL = 30


def learned_path(root, gid):
    try:
        data = json.loads((Path(root) / LEARNED_FILE).read_text(encoding="utf-8"))
        p = data.get(gid) if isinstance(data, dict) else None
        return p if isinstance(p, str) else None
    except (OSError, ValueError):
        return None


def set_learned(root, gid, path):
    with _LEARN_LOCK:
        _FALLBACK_CACHE.pop(gid, None)
        _set_learned(root, gid, path)


def _set_learned(root, gid, path):
    f = Path(root) / LEARNED_FILE
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    if path:
        data[gid] = str(path)
    else:
        data.pop(gid, None)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def _fallback(root, games_entry):
    import time as _t
    gid = games_entry.get("id")
    hit = _FALLBACK_CACHE.get(gid)
    if hit and _t.monotonic() - hit[0] < FALLBACK_TTL:
        return hit[1]
    lib = library_entry(games_entry)
    name = lib.get("name") or games_entry.get("name") or gid
    res = bindings.find_fallback(name, lib.get("dir"), lib.get("steam"), learned_path(root, gid))
    _FALLBACK_CACHE[gid] = (_t.monotonic(), res)
    return res


def _read_bindings(root, games_entry, with_state=False):
    """Belegung des Spiels (games.json-Eintrag oder Bibliothekseintrag) lesen -> (Result oder None, Quelle).
    Ohne eigenen Adapter: generische Suche in den Spielordnern (bindings/scan.py; Unlesbares wird gemeldet)."""
    cfg = games_entry.get("bindings")
    if not cfg:
        try:
            res, msg, state = _fallback(root, games_entry)
        except Exception as e:  # noqa: BLE001
            log.warning("Belegungssuche %s: %s", games_entry.get("id"), type(e).__name__)
            res, msg, state = None, "Belegungssuche fehlgeschlagen – Tasten bleiben leer", "none"
        return (res, msg, state) if with_state else (res, msg)
    try:
        result = bindings.read(cfg, root)
        return (result, result.source, "read") if with_state else (result, result.source)
    except (OSError, ValueError, Exception) as e:  # noqa: BLE001 - kaputte XML o. Ä.: mit Vorlage weiter
        log.warning("Belegung %s: %s", games_entry["id"], e)
        msg = f"Belegung nicht lesbar ({type(e).__name__}) – nur Vorlagentasten"
        return (None, msg, "unreadable") if with_state else (None, msg)


def binding_status(root, games_entry):
    """Für den Editor vor dem Erzeugen: {ok, state, source, count, learned} - woher die Tasten kommen (oder warum
    keine). state: read | recognized | only_changes | unreadable | unknown | none (siehe bindings/scan.py)."""
    result, source, state = _read_bindings(root, games_entry, with_state=True)
    n = sum(1 for b in result.bindings.values() if b.key) if result else 0
    return {"ok": bool(result and n), "state": state, "source": source, "count": n,
            "learned": bool(learned_path(root, games_entry.get("id"))), "adapter": bool(games_entry.get("bindings"))}


def learn_snapshot(games_entry):
    """Lernmodus Schritt 1: Zustand der Dateien des Spiels merken (nur Spiele aus games.json oder der Bibliothek)."""
    from .bindings import scan
    lib = library_entry(games_entry)
    if not lib and not games_entry.get("exe"):
        raise ValueError("Spiel nicht in der Bibliothek gefunden")
    return scan.snapshot(lib.get("name") or games_entry.get("name") or games_entry.get("id"), lib.get("dir"),
                         lib.get("steam"))


def learn_finish(root, games_entry, snap):
    """Lernmodus Schritt 2: geänderte Dateien prüfen, die erste lesbare merken. -> {found, changed, state, msg}"""
    from .bindings import scan
    from .bindings.containers import open_bytes
    from .bindings.readers import read_content
    lib = library_entry(games_entry)
    name = lib.get("name") or games_entry.get("name") or games_entry.get("id")
    files = scan.changed(snap, name, lib.get("dir"), lib.get("steam"))
    shown = [scan._shown(f) for f in files[:8]]
    if not files:
        return {"found": False, "changed": [], "state": "none",
                "msg": "keine geänderte Datei gefunden – im Spiel eine Taste ändern und die Einstellungen speichern"}
    unreadable = 0
    for f in files[:20]:
        try:
            kind, content = open_bytes(Path(f).read_bytes()[:scan.MAX_FILE])
        except OSError:
            continue
        r = read_content(kind, content)
        if r and r.count:
            set_learned(root, games_entry["id"], f)
            return {"found": True, "changed": shown, "state": "read" if r.method == "exact" else "recognized",
                    "msg": f"Steuerungsdatei gefunden: {scan._shown(f)} ({r.count} Tasten) – wird ab jetzt verwendet"}
        if kind in ("encrypted", "binary"):
            unreadable += 1
    if unreadable:
        return {"found": False, "changed": shown, "state": "unreadable",
                "msg": "geänderte Datei(en) gefunden, aber nicht lesbar (verschlüsselt/binär) – Tasten bitte im Editor eintragen"}
    return {"found": False, "changed": shown, "state": "unknown",
            "msg": "geänderte Datei(en) gefunden, Format aber nicht erkannt"}


def draft(root, games_entry, tid, pages=None, style="areas", skip_device=False):
    """Vorlage + Belegung des Spiels (games.json-Eintrag) -> (layout, bericht, quelle). Semantische Vorlagen:
    pages = Section-Titel, style = Darstellung, skip_device = Aktionen weglassen, die schon auf Joystick/HOTAS
    oder Gamepad liegen (stehen dann mit Quelle "weggelassen" im Bericht)."""
    if not isinstance(style, str) or style not in STYLES:
        raise ValueError("Darstellung muss areas oder grid sein")
    raw = read_template(root, games_entry["id"], tid)
    result, source = _read_bindings(root, games_entry)
    if is_semantic(raw):
        skip = result.on_device if (skip_device and result) else frozenset()
        spec, dropped = filter_spec(raw, pages, skip)
        layout, report = generate(auto_build(spec, style), result)
        report += [dict(d, id="", key="", page_id="", source="weggelassen",
                        note="liegt schon auf Joystick/Gamepad") for d in dropped]
        if skip_device:
            source += f" · {len(dropped)} Aktion(en) weggelassen (Joystick/Gamepad)"
        return layout, report, source
    validate_layout(raw)
    layout, report = generate(raw, result, pages)
    return layout, report, source


# Felder, die nur die Lage einer Taste in einer bestimmten Seite beschreiben - nicht Teil einer Palette-Aktion
_POSITION_FIELDS = ("x", "y", "w", "h", "zone", "wide", "group")


def actions(root, games_entry):
    """Spielaktionen für die Palette des Panel-Editors: alle Tasten der Vorlagen des Spiels, mit der Taste aus der
    eigenen Belegung (dieselbe Quelle und Regeln wie die automatische Erstellung, siehe generate()).
    Rückgabe: (vorlagen, quelle). vorlagen: [{id, title, pages: [{id, title, actions: [{button, group, action,
    key, source, note}]}]}]; button ist eine fertige, gültige Taste ohne Lagefelder (x, y, w, h, zone, wide,
    group), group die Überschrift in der Vorlage. Seiten-Links entfallen (sie zeigen auf Vorlagenseiten)."""
    result, source = _read_bindings(root, games_entry)
    out = []
    for t in list_templates(root, games_entry["id"]):
        layout, report = generate(load_template(root, games_entry["id"], t["id"]), result)
        rows = {(r["page_id"], r["id"]): r for r in report}
        pages = []
        for page in layout["pages"]:
            acts = []
            for b in page["buttons"]:
                if "page" in b or "kind" in b:
                    continue
                r = rows[(page["id"], b["id"])]
                acts.append({"button": {k: v for k, v in b.items() if k not in _POSITION_FIELDS},
                             "group": b.get("group", ""), "action": r["action"], "key": r["key"],
                             "source": r["source"], "note": r["note"]})
            if acts:
                pages.append({"id": page["id"], "title": page["title"], "actions": acts})
        out.append({"id": t["id"], "title": t["title"], "pages": pages})
    return out, source


def actions_message(root, games_entry):
    """Antwort des Hubs auf die Editor-Nachricht {"t": "actions", "game": ...}."""
    templates, source = actions(root, games_entry)
    return {"t": "actions", "game": games_entry["id"], "templates": templates, "source": source,
            "bindings": bool(games_entry.get("bindings"))}
