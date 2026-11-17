"""KI-Vorlage: für ein Spiel ohne handgemachte Vorlage erzeugt Claude eine Panel-Vorlage.

Ergebnis ist eine semantische Vorlage (title, sections -> areas -> items, siehe autolayout.py); Anordnung und
Tasten setzt das Programm (Auto-Layout, Belegung des Spielers) - die KI erfindet keine Tasten.
Der API-Schlüssel liegt in secrets/anthropic.key (nie loggen, nie in Meldungen).
"""
import json
import logging
import os
import re
from pathlib import Path


log = logging.getLogger("ai_template")

MODEL = "claude-opus-5-5"
BETAS = ["server-side-fallback-2026-07-01"]
KEY_FILE = Path("secrets") / "anthropic.key"
MAX_HINT = 2000

# Fester Teil des Prompts („muss so sein“): Format und Ehrlichkeit. Der Nutzer sieht ihn, kann ihn aber nicht ändern.
FIXED_PROMPT = """Du entwirfst ein Tasten-Panel für ein Touch-Tablet, das neben dem Spiel liegt.
Jede Taste löst eine Spielaktion aus; die Tastenkombination setzt das Programm später aus der Belegung des
Spielers ein. Du gibst nur die Gliederung aus, keine Koordinaten - die Anordnung macht das Programm.
Feste Regeln:
- Gliederung: sections (Seiten, höchstens 4) -> areas (Bereiche mit Überschrift, höchstens 8 je Seite) ->
  items (Tasten, höchstens 16 je Bereich).
- Gibt es eine Liste vorgegebener Aktionen, nutze NUR diese Aktionen, Namen exakt übernehmen. Erfinde keine
  Aktionen und gib nie Tasten aus. Ohne Liste: action ist eine kurze Beschreibung der Spielfunktion.
- Gefährliche oder nicht rückgängig zu machende Aktionen (Selbstzerstörung, Schnellladen, Auflösen, Verkaufen):
  style "danger" und guard "hold" oder "double".
- Keine Maus- und Achsenaktionen.
- kind "pair": zwei gegensätzliche Aktionen (weniger/mehr, zurück/weiter) in action und action2 - erst die
  „weniger/zurück“-Aktion.
- Beschriftung (label) deutsch, kurz (höchstens 22 Zeichen); Überschriften höchstens 20 Zeichen."""

# Änderbarer Teil (Voreinstellung): Gestaltung. Der Nutzer kann ihn im Editor anpassen.
DEFAULT_STYLE_PROMPT = """Gestaltung:
- Seiten nach Spielphasen oder Tätigkeiten (z. B. Kampf, Reisen, Bauen, Menüs), Bereiche nach Thema.
- Was man im Spiel ständig braucht, kommt auf die erste Seite; Seltenes auf spätere Seiten.
- size: "m" normal; "l" breit für wichtige Tasten; "xl" groß für die eine Hauptaktion einer Seite (höchstens
  eine je Seite); "pill" schmale Leiste für Nebensächliches.
- Gegensätze (mehr/weniger, vor/zurück) als kind "pair".
- Wichtige Aktionen style "accent", sonst "".
- Lieber weniger, dafür sinnvolle Tasten: keine Bewegungstasten (WASD), nichts, was man ohnehin blind auf der
  Tastatur drückt."""
MAX_STYLE_PROMPT = 4000

_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "label", "action", "action2", "size", "style", "guard"],
    "properties": {
        "kind": {"type": "string", "enum": ["key", "pair"]},
        "label": {"type": "string"},
        "action": {"type": "string"},
        "action2": {"type": ["string", "null"], "description": "Nur bei kind pair: die zweite Aktion."},
        "size": {"type": "string", "enum": ["m", "l", "xl", "pill"]},
        "style": {"type": "string", "enum": ["", "accent", "danger"]},
        "guard": {"type": "string", "enum": ["none", "hold", "double"]},
    },
}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "sections"],
    "properties": {
        "title": {"type": "string"},
        "sections": {
            "type": "array",
            "description": "Höchstens 4 Seiten.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "areas"],
                "properties": {
                    "title": {"type": "string"},
                    "areas": {
                        "type": "array",
                        "description": "Höchstens 8 Bereiche je Seite.",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["title", "items"],
                            "properties": {
                                "title": {"type": "string"},
                                "items": {"type": "array", "description": "Höchstens 16 Tasten je Bereich.",
                                          "items": _ITEM},
                            },
                        },
                    },
                },
            },
        },
    },
}


MAX_SECTIONS, MAX_AREAS, MAX_ITEMS = 4, 8, 16   # Obergrenzen, falls die KI mehr liefert als verlangt


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
        client = anthropic.Anthropic(api_key=_read_key(root), max_retries=0, timeout=20)   # höchstens 20 s Warten
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


def _text(v, n):
    return v.strip()[:n] if isinstance(v, str) else ""


def clean(data):
    """KI-Antwort -> semantische Vorlage (siehe autolayout.py); wirft ValueError bei unbrauchbarem Ergebnis.
    Tasten (key) werden nie übernommen - die setzt der Generator aus der Belegung ein."""
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        raise ValueError("KI-Antwort ohne Seiten")
    out = {"title": _text(data.get("title"), 40) or "KI-Vorlage", "holdMs": 1000, "sections": []}
    seen = set()
    for si, s in enumerate(data["sections"][:MAX_SECTIONS], 1):
        if not isinstance(s, dict) or not isinstance(s.get("areas"), list):
            continue
        base = _text(s.get("title"), 20) or f"Seite {si}"
        title, n = base, 2
        while title in seen:                 # Seitengruppen brauchen eindeutige Titel (Zähler: endet sicher)
            title = f"{base[:20 - len(str(n)) - 1].rstrip()} {n}"
            n += 1
        areas = []
        for a in s["areas"][:MAX_AREAS]:
            if not isinstance(a, dict) or not isinstance(a.get("items"), list):
                continue
            items = []
            for it in a["items"][:MAX_ITEMS]:
                if not isinstance(it, dict):
                    continue
                label = _text(it.get("label"), 22) or _text(it.get("action"), 22)
                act = _text(it.get("action"), 120)
                if not label or not act:
                    continue
                t = {"label": label, "action": act}
                if it.get("style") in ("accent", "danger"):
                    t["style"] = it["style"]
                if it.get("guard") in ("hold", "double"):
                    t["mode"] = "hold-confirm" if it["guard"] == "hold" else "double"
                act2 = _text(it.get("action2"), 120)
                if it.get("kind") == "pair" and act2 and act2 != act:   # Paar nur aus zwei verschiedenen Aktionen
                    items.append({"pair": [t, dict(t, action=act2)]})
                else:
                    if it.get("size") in ("l", "xl", "pill"):
                        t["size"] = it["size"]
                    items.append(t)
            if items:
                areas.append({"title": _text(a.get("title"), 40), "items": items})
        if areas:
            seen.add(title)
            out["sections"].append({"title": title, "areas": areas})
    if not out["sections"]:
        raise ValueError("KI-Antwort ohne Tasten")
    return out


def prompt_parts():
    """Für den Editor: fester Teil (nur Anzeige) und Voreinstellung des änderbaren Teils."""
    return {"fixed": FIXED_PROMPT, "style": DEFAULT_STYLE_PROMPT, "max_style": MAX_STYLE_PROMPT}


def _user_text(game_name, actions, hint):
    lines = [f"Spiel: {game_name}"]
    if actions:
        lines.append("Vorgegebene Aktionen (nur diese verwenden; in Klammern die Taste des Spielers, nur zur "
                     "Orientierung):")
        for a in actions:
            lines.append(f"- {a.get('action')}" + (f" ({a['key']})" if a.get("key") else ""))
    else:
        lines.append("Keine Aktionsliste vorhanden: action ist eine kurze Beschreibung der Spielfunktion. "
                     "Tasten trägt der Spieler später selbst ein.")
    hint = (hint or "").strip()[:MAX_HINT]
    if hint:
        lines.append("Hinweis des Nutzers:\n" + hint)
    return "\n".join(lines)


def generate_template(root, game_name, actions=None, hint="", client=None, style_prompt=None):
    """Semantische Vorlage per KI erzeugen und bereinigen; client ist für Tests austauschbar.
    style_prompt: änderbarer Teil des Prompts (None = Voreinstellung); der feste Teil gilt immer."""
    style = DEFAULT_STYLE_PROMPT if style_prompt is None else str(style_prompt)[:MAX_STYLE_PROMPT]
    from . import ai_providers
    if client is None and ai_providers.active(root) == "openai":
        system = FIXED_PROMPT + ("\n\n" + style.strip() if style.strip() else "")
        return clean(ai_providers.openai_json(root, system, _user_text(game_name, actions, hint), SCHEMA, "panel"))
    if client is None:
        key = _read_key(root)
        import anthropic
        client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=120)
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=16000, betas=BETAS, fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=FIXED_PROMPT + ("\n\n" + style.strip() if style.strip() else ""),
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
