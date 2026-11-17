"""KI-Anbieter für „Mit KI erstellen“ und „Mit KI suchen“: Anthropic (Claude, Standard) oder OpenAI.

Schlüssel je Anbieter unter secrets/<anbieter>.key (nie geloggt, nie zurückgeschickt, nie in Fehlertexten).
Die Wahl des Anbieters und das OpenAI-Modell stehen in ai_settings.json (lokal, kein Geheimnis).
OpenAI wird ohne Zusatzpaket über die Responses-API angesprochen (POST /v1/responses, json_schema-Ausgabe,
Werkzeug web_search). Die Prüfung der Ergebnisse (Aufbereitung, Seitenleser-Gegenprüfung) ist anbieterunabhängig.
"""
import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("ai_providers")

PROVIDERS = {
    "anthropic": {"name": "Anthropic (Claude)", "file": Path("secrets") / "anthropic.key",
                  "format": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,250}"), "hint": "beginnt mit sk-ant-"},
    "openai": {"name": "OpenAI", "file": Path("secrets") / "openai.key",
               "format": re.compile(r"sk-[A-Za-z0-9_\-]{20,300}"), "hint": "beginnt mit sk-"},
}
SETTINGS_FILE = "ai_settings.json"
DEFAULT_OPENAI_MODEL = "gpt-6-astra"   # aus den OpenAI-Beispielen (Stand 11/2026); im Editor änderbar
OPENAI_URL = "https://api.openai.com/v1"
MODEL_FORMAT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{1,80}")


# ---------------------------------------------------------------- Einstellungen
def settings(root):
    """{"provider": "anthropic"|"openai", "openai_model": str}"""
    out = {"provider": "anthropic", "openai_model": DEFAULT_OPENAI_MODEL}
    try:
        data = json.loads((Path(root) / SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if isinstance(data, dict):
        if isinstance(data.get("provider"), str) and data["provider"] in PROVIDERS:
            out["provider"] = data["provider"]
        if isinstance(data.get("openai_model"), str) and MODEL_FORMAT.fullmatch(data["openai_model"]):
            out["openai_model"] = data["openai_model"]
    return out


def save_settings(root, provider=None, openai_model=None):
    cur = settings(root)
    if provider is not None:
        if provider not in PROVIDERS:
            raise ValueError("unbekannter Anbieter")
        cur["provider"] = provider
    if openai_model is not None:
        if not isinstance(openai_model, str) or not MODEL_FORMAT.fullmatch(openai_model.strip()):
            raise ValueError("ungültiger Modellname")
        cur["openai_model"] = openai_model.strip()
    p = Path(root) / SETTINGS_FILE
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return cur


def active(root):
    return settings(root)["provider"]


# ---------------------------------------------------------------- Schlüssel
def _prov(provider):
    if provider not in PROVIDERS:
        raise ValueError("unbekannter Anbieter")
    return PROVIDERS[provider]


def read_key(root, provider):
    p = Path(root) / _prov(provider)["file"]
    try:
        key = p.read_text(encoding="utf-8").strip()
    except OSError:
        key = ""
    if not key:
        raise ValueError(f"Kein API-Schlüssel für {_prov(provider)['name']} hinterlegt – im Editor unter "
                         "⚙ Einstellungen eintragen")
    return key


def key_status(root, provider):
    try:
        return {"set": bool((Path(root) / _prov(provider)["file"]).read_text(encoding="utf-8").strip())}
    except (OSError, UnicodeDecodeError):
        return {"set": False}


def save_key(root, provider, key):
    pr = _prov(provider)
    if not isinstance(key, str):
        raise ValueError("Schlüssel fehlt")
    key = key.strip()
    if provider == "openai" and key.startswith("sk-ant-"):
        raise ValueError("Das ist ein Anthropic-Schlüssel – oben Anthropic wählen")
    if not pr["format"].fullmatch(key):
        raise ValueError(f"Das sieht nicht wie ein {pr['name']}-API-Schlüssel aus ({pr['hint']})")
    p = Path(root) / pr["file"]
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
    log.info("KI-Schlüssel gespeichert (%s)", provider)


def delete_key(root, provider):
    try:
        (Path(root) / _prov(provider)["file"]).unlink()
        log.info("KI-Schlüssel entfernt (%s)", provider)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------- OpenAI (Responses-API, ohne Zusatzpaket)
def _openai(key, method, path, body=None, timeout=180, opener=None):
    req = urllib.request.Request(OPENAI_URL + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Meldungen nennen nur die Art, nie den Schlüssel (der Antworttext könnte ihn teilweise spiegeln)
        if e.code == 401:
            raise ValueError("OpenAI-Schlüssel ungültig – im Editor unter ⚙ Einstellungen prüfen") from None
        if e.code == 429:
            raise ValueError("OpenAI-Limit erreicht oder kein Guthaben – später erneut versuchen") from None
        if e.code == 404:
            raise ValueError("OpenAI-Modell nicht gefunden – Modellname unter ⚙ Einstellungen prüfen") from None
        detail = ""
        try:   # nur Fehlercode/-art aus dem JSON, nie den Freitext (könnte Teile des Schlüssels spiegeln)
            err = json.loads(e.read(65536).decode("utf-8")).get("error") or {}
            detail = ", ".join(str(err[k])[:60] for k in ("code", "type", "param") if isinstance(err.get(k), str)
                               and re.fullmatch(r"[\w.\-]{1,60}", err[k]))
        except (ValueError, OSError, AttributeError):
            pass
        raise ValueError(f"OpenAI-API-Fehler {e.code}" + (f" ({detail})" if detail else "")) from None
    except (urllib.error.URLError, OSError):
        raise ValueError("OpenAI-API nicht erreichbar (Internet?)") from None
    except ValueError:
        raise ValueError("OpenAI-Antwort unbrauchbar") from None


def _output_text(resp):
    """Text der Antwort (message -> output_text); Ablehnung/abgebrochen -> ValueError."""
    if resp.get("status") == "incomplete":
        raise ValueError("Antwort zu lang" if (resp.get("incomplete_details") or {}).get("reason")
                         == "max_output_tokens" else "KI-Antwort unvollständig")
    if resp.get("status") == "failed":
        raise ValueError("OpenAI-Anfrage fehlgeschlagen")
    parts = []
    for item in resp.get("output") or []:
        if item.get("type") != "message":
            continue
        for c in item.get("content") or []:
            if c.get("type") == "refusal":
                raise ValueError("KI hat abgelehnt")
            if c.get("type") == "output_text":
                parts.append(c.get("text") or "")
    if not parts:
        raise ValueError("KI-Antwort ohne Text")
    return "".join(parts)


def _json_from_text(text, want="bindings"):
    """Erstes JSON-Objekt im Freitext, das den Schlüssel want hat (auch mehrere Blöcke, Prosa mit Klammern)."""
    dec, first = json.JSONDecoder(), None
    text, pos, tries = text[:200_000], 0, 0          # begrenzt: kein quadratisches Hängen bei vielen „{“
    while tries < 300:
        i = text.find("{", pos)
        if i < 0:
            break
        tries += 1
        try:
            obj, end = dec.raw_decode(text, i)
        except (ValueError, RecursionError):
            pos = i + 1
            continue
        pos = end                                    # hinter dem Objekt weitersuchen, nicht hinein
        if isinstance(obj, dict):
            if want in obj:
                return obj
            first = first or obj
    if first is not None and not want:
        return first
    raise ValueError("KI-Antwort ist kein gültiges JSON")


def openai_json(root, system, user, schema, name="antwort", opener=None):
    """Strukturierte Antwort (json_schema, strict) -> dict."""
    st = settings(root)
    body = {"model": st["openai_model"], "instructions": system, "input": user, "max_output_tokens": 16000,
            "text": {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}}
    resp = _openai(read_key(root, "openai"), "POST", "/responses", body, opener=opener)
    try:
        return json.loads(_output_text(resp))
    except json.JSONDecodeError:
        raise ValueError("KI-Antwort ist kein gültiges JSON") from None


def openai_web_json(root, system, user, opener=None):
    """Antwort mit Websuche (Werkzeug web_search); das JSON steht im Text -> dict."""
    st = settings(root)
    body = {"model": st["openai_model"], "instructions": system, "input": user, "max_output_tokens": 16000,
            "tools": [{"type": "web_search"}]}
    resp = _openai(read_key(root, "openai"), "POST", "/responses", body, timeout=300, opener=opener)
    return _json_from_text(_output_text(resp))


def check_openai(root, opener=None):
    """Schlüssel kostenlos prüfen (Modellliste)."""
    try:
        _openai(read_key(root, "openai"), "GET", "/models", timeout=20, opener=opener)
    except ValueError as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": True, "msg": "Schlüssel gültig"}
