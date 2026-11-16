"""Panel automatisch erzeugen: Spielvorlage + eigene Tastenbelegung -> Panel-Entwurf.

Vorlagen: templates/<spiel>/<vorlage>.json im Panel-Format (title, pages, buttons). Tasten nennen ihre
Spielaktion in "sc" (Star Citizen) bzw. "action" und dürfen eine Standardtaste "key" mitbringen.

Reihenfolge für die Taste: eigene Belegung (Adapter) > Taste aus der Vorlage > keine (Taste bleibt
unbelegt, mit Vorschlag einer freien Kombination). Gespeichert wird erst im Editor.
"""
import copy
import json
import logging
import re
from pathlib import Path

from . import bindings
from .layout import validate_layout

log = logging.getLogger("generate")
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


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
            t = json.loads(f.read_text(encoding="utf-8"))
            validate_layout(t)
            out.append({"id": f.stem, "title": t.get("title", f.stem),
                        "pages": [{"id": p["id"], "title": p["title"]} for p in t["pages"]]})
        except (ValueError, OSError) as e:
            log.error("Vorlage %s/%s fehlerhaft: %s", game, f.stem, e)
    return out


def load_template(root, game, tid):
    if not (ID.fullmatch(game or "") and ID.fullmatch(tid or "")):
        raise ValueError("ungültige Vorlage")
    f = Path(root) / "templates" / game / f"{tid}.json"
    if not f.is_file():
        raise ValueError("Vorlage nicht gefunden")
    t = json.loads(f.read_text(encoding="utf-8"))
    validate_layout(t)
    return t


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


def ai_draft(root, games_entry, hint=""):
    """KI-Vorlage (Claude-API) + eigene Belegung -> (layout, bericht, quelle). Mit Belegungsquelle bekommt die KI
    nur Aktionen, die eine Tastaturbelegung haben (begrenzt); danach setzt generate() die echten Tasten ein."""
    try:
        import anthropic
    except ImportError:
        raise ValueError("Paket anthropic fehlt (pip install -r requirements.txt)") from None
    from .ai_template import generate_template
    cfg = games_entry.get("bindings")
    result, actions = None, None
    if cfg:
        try:
            result = bindings.read(cfg, root)
            actions = [{"action": a, "key": b.key} for a, b in sorted(result.bindings.items()) if b.key][:MAX_AI_ACTIONS]
        except Exception as e:  # noqa: BLE001 - ohne Belegung weiter (KI nimmt dann die Standardbelegung)
            log.warning("Belegung %s für KI nicht lesbar: %s", games_entry["id"], e)
    try:
        template = generate_template(root, games_entry.get("name", games_entry["id"]), actions=actions, hint=hint)
    except anthropic.AuthenticationError:
        raise ValueError("API-Schlüssel ungültig (secrets/anthropic.key)") from None
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
    layout, report = generate(template, result)
    source = "KI-Vorlage (Claude)" + (" + " + result.source if result else ", Tasten nach Standardbelegung – bitte prüfen")
    return layout, report, source


def _read_bindings(root, games_entry):
    """Belegung des Spiels (games.json-Eintrag) lesen -> (Result oder None, Quellenbeschreibung)."""
    cfg = games_entry.get("bindings")
    if not cfg:
        return None, "nur Vorlage (keine Belegungsquelle hinterlegt)"
    try:
        result = bindings.read(cfg, root)
        return result, result.source
    except (OSError, ValueError, Exception) as e:  # noqa: BLE001 - kaputte XML o. Ä.: mit Vorlage weiter
        log.warning("Belegung %s: %s", games_entry["id"], e)
        return None, f"Belegung nicht lesbar ({e}) – nur Vorlagentasten"


def draft(root, games_entry, tid, pages=None):
    """Vorlage + Belegung des Spiels (games.json-Eintrag) -> (layout, bericht, quelle)."""
    template = load_template(root, games_entry["id"], tid)
    result, source = _read_bindings(root, games_entry)
    layout, report = generate(template, result, pages)
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
                if "page" in b:
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
