"""KI-Vorlage: für ein Spiel ohne handgemachte Vorlage erzeugt Claude eine Panel-Vorlage.

Ergebnis im Layout-Format (title, holdMs, pages, buttons), geprüft mit layout.validate_layout.
Der API-Schlüssel liegt in secrets/anthropic.key (nie loggen, nie in Meldungen).
"""
import json
import logging
import os
import re
from pathlib import Path

from . import keys
from .layout import validate_layout

log = logging.getLogger("ai_template")

MODEL = "claude-opus-5-5"
BETAS = ["server-side-fallback-2026-07-01"]
KEY_FILE = Path("secrets") / "anthropic.key"
MAX_HINT = 2000

SYSTEM_PROMPT = """Du entwirfst ein Tasten-Panel für ein Touch-Tablet, das neben dem Spiel liegt.
Jede Taste löst eine Tastenkombination im Spiel aus.
Regeln:
- Beschriftung (label) GROSS geschrieben, kurz (höchstens 22 Zeichen), deutsch.
- Sinnvolle Seiten (höchstens 4) und Gruppen (group); höchstens 24 Tasten je Seite.
- Gefährliche oder nicht rückgängig zu machende Aktionen (Schnellladen, Selbstzerstörung, Auflösen):
  mode "hold-confirm" und style "danger".
- Umschalter (Licht, Fahrwerk): mode "toggle". Sonst mode "tap".
- Wichtige Aktionen: style "accent". Sonst style "" (leer).
- Keine Maus- und Achsenaktionen.
- Tasten im Format wie "LALT+F", "NUMPAD8", "F5", "CTRL+S".
- Gibt es eine Liste vorgegebener Aktionen, nutze NUR diese Aktionen und Tasten (Taste unverändert übernehmen,
  Aktion ohne Taste: key null).
- Ohne Liste: Standardbelegung des Spiels nach bestem Wissen; bei unsicherer Taste key null, lieber null als raten.
- hold true nur für Tasten, die gehalten werden sollen, sonst false."""

_STR_OR_NULL = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "pages"],
    "properties": {
        "title": {"type": "string"},
        "pages": {
            "type": "array",
            "description": "Höchstens 4 Seiten.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "title", "buttons"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "buttons": {
                        "type": "array",
                        "description": "Höchstens 24 Tasten je Seite.",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["id", "label", "action", "key", "mode", "style", "group", "hold"],
                            "properties": {
                                "id": {"type": "string"},
                                "label": {"type": "string"},
                                "action": {"type": "string"},
                                "key": _STR_OR_NULL,
                                "mode": {"type": "string", "enum": ["tap", "hold-confirm", "toggle"]},
                                "style": {"type": "string", "enum": ["", "accent", "danger"]},
                                "group": _STR_OR_NULL,
                                "hold": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
        },
    },
}


MAX_PAGES, MAX_BUTTONS = 6, 30   # Obergrenzen, falls die KI mehr liefert als verlangt


def _read_key(root):
    p = Path(root) / KEY_FILE
    try:
        key = p.read_text(encoding="utf-8").strip()
    except OSError:
        key = ""
    if not key:
        raise ValueError("Kein API-Schlüssel hinterlegt – im Editor unter ⚙ Einstellungen eintragen")
    return key


# ---------------------------------------------------------------- Schlüssel verwalten (Editor, ⚙ Einstellungen)
# Der Schlüssel geht nur in eine Richtung: Editor -> Datei. Er wird nie zurückgeschickt, nie geloggt und taucht
# in keiner Fehlermeldung auf.
KEY_FORMAT = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,250}")


def key_status(root):
    """{"set": bool} - ob ein Schlüssel hinterlegt ist (ohne ihn zu lesen oder zu zeigen)."""
    try:
        return {"set": bool((Path(root) / KEY_FILE).read_text(encoding="utf-8").strip())}
    except (OSError, UnicodeDecodeError):
        return {"set": False}


def save_key(root, key):
    """Schlüssel prüfen (Format) und atomar nach secrets/anthropic.key schreiben."""
    if not isinstance(key, str):
        raise ValueError("Schlüssel fehlt")
    key = key.strip()
    if not KEY_FORMAT.fullmatch(key):
        raise ValueError("Das sieht nicht wie ein Anthropic-API-Schlüssel aus (beginnt mit sk-ant-)")
    p = Path(root) / KEY_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(key + "\n", encoding="utf-8")
        os.replace(tmp, p)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    log.info("KI-Schlüssel gespeichert")


def delete_key(root):
    try:
        (Path(root) / KEY_FILE).unlink()
        log.info("KI-Schlüssel entfernt")
    except FileNotFoundError:
        pass


def check_key(root, client=None):
    """Schlüssel mit einer kostenlosen Abfrage (Modellliste) prüfen. -> {"ok": bool, "msg": Text}.
    Fehlertexte nennen nur die Art des Fehlers, nie den Schlüssel."""
    import anthropic
    if client is None:
        client = anthropic.Anthropic(api_key=_read_key(root), max_retries=1, timeout=20)
    try:
        client.models.list(limit=1)
    except anthropic.AuthenticationError:
        return {"ok": False, "msg": "Schlüssel ungültig oder widerrufen"}
    except anthropic.PermissionDeniedError:
        return {"ok": False, "msg": "Schlüssel hat keine Berechtigung"}
    except anthropic.RateLimitError:
        return {"ok": True, "msg": "Schlüssel gültig (gerade im API-Limit)"}
    except anthropic.APIConnectionError:
        return {"ok": False, "msg": "Keine Verbindung zur Anthropic-API"}
    except anthropic.APIStatusError as e:
        return {"ok": False, "msg": f"API-Fehler {getattr(e, 'status_code', '?')}"}
    return {"ok": True, "msg": "Schlüssel gültig"}


def _slug(text, fallback):
    s = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    return s[:40] or fallback


def _unique(base, used):
    cand, n = base, 2
    while cand in used:
        cand = f"{base}_{n}"
        n += 1
    used.add(cand)
    return cand


def clean(layout):
    """KI-Antwort bereinigen und prüfen; wirft ValueError bei unbrauchbarem Ergebnis."""
    if not isinstance(layout, dict) or not isinstance(layout.get("pages"), list):
        raise ValueError("KI-Antwort ohne Seiten")
    title = layout.get("title")
    hold = layout.get("holdMs")
    out = {"title": (title.strip() if isinstance(title, str) else "")[:40] or "KI-Vorlage",
           "holdMs": min(5000, max(200, hold)) if type(hold) is int else 1000,
           "pages": []}
    page_ids, button_ids = set(), set()
    for pi, page in enumerate(layout["pages"][:MAX_PAGES], 1):
        if not isinstance(page, dict) or not isinstance(page.get("buttons"), list):
            continue
        buttons = []
        for bi, b in enumerate(page["buttons"][:MAX_BUTTONS], 1):
            if not isinstance(b, dict):
                continue
            raw = b.get("label") if isinstance(b.get("label"), str) and b.get("label").strip() else b.get("action")
            label = (raw.strip() if isinstance(raw, str) else "")[:40] or f"TASTE {bi}"
            nb = {"id": _unique(_slug(b.get("id") or label, f"taste_{bi}"), button_ids),
                  "label": label,
                  "mode": b.get("mode") if b.get("mode") in ("tap", "hold-confirm", "toggle") else "tap"}
            if isinstance(b.get("action"), str) and b["action"]:
                nb["action"] = b["action"]
            key = b.get("key")
            if isinstance(key, str) and key.strip():
                key = key.strip().upper().replace(" ", "")
                try:
                    keys.parse_combo(key)
                    nb["key"] = key
                except KeyError:
                    log.info("Ungültige Taste der KI entfernt (%s)", nb["id"])
            if b.get("style") in ("accent", "danger"):
                nb["style"] = b["style"]
            if isinstance(b.get("group"), str) and b["group"].strip():
                nb["group"] = b["group"].strip()
            if b.get("hold") is True:
                nb["hold"] = True
            buttons.append(nb)
        if not buttons:
            continue
        ptitle = str(page.get("title") or "").strip() or f"Seite {pi}"
        out["pages"].append({"id": _unique(_slug(page.get("id") or ptitle, f"seite_{pi}"), page_ids),
                             "title": ptitle[:40], "type": "grid", "buttons": buttons})
    validate_layout(out)
    return out


def _user_text(game_name, actions, hint):
    lines = [f"Spiel: {game_name}"]
    if actions:
        lines.append("Vorgegebene Aktionen (nur diese und ihre Tasten verwenden):")
        for a in actions:
            lines.append(f"- {a.get('action')}: {a.get('key') or '(keine Taste)'}")
    else:
        lines.append("Keine Belegung vorgegeben: Standardbelegung nach bestem Wissen, unsichere Tasten null.")
    hint = (hint or "").strip()[:MAX_HINT]
    if hint:
        lines.append("Hinweis des Nutzers:\n" + hint)
    return "\n".join(lines)


def generate_template(root, game_name, actions=None, hint="", client=None):
    """Vorlage per KI erzeugen und bereinigen; client ist für Tests austauschbar."""
    if client is None:
        key = _read_key(root)
        import anthropic
        client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=120)
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=16000, betas=BETAS, fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _user_text(game_name, actions, hint)}])
    if resp.stop_reason == "refusal":
        raise ValueError("KI hat abgelehnt")
    if resp.stop_reason == "max_tokens":
        raise ValueError("Antwort zu lang")
    text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
    if text is None:
        raise ValueError("KI-Antwort ohne Text")
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError("KI-Antwort ist kein gültiges JSON") from None
    return clean(data)
