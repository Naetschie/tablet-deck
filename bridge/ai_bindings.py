"""Standardtasten mit KI-Suche: Claude sucht und liest Steuerungs-Seiten im Netz (Websuche/Seitenabruf bei
Anthropic) und meldet je Zeile Aktion, Taste (wie auf der Seite geschrieben) und die Seite. Der Hub glaubt das
nicht einfach: er ruft jede genannte Seite selbst ab (sicherer Abruf, bindings/web.py) und behält nur Zeilen,
deren Aktion und Tastentext dort wörtlich stehen und deren Taste das Tastenwörterbuch eindeutig kennt.
Kostet API-Guthaben des Nutzers (eigener Schlüssel, secrets/anthropic.key).
"""
import logging
import re
import time
import urllib.parse

from .ai_template import BETAS, MODEL, _read_key
from .bindings import web

log = logging.getLogger("ai_bindings")
MAX_ROUNDS = 3          # pause_turn-Fortsetzungen der serverseitigen Suche (je Runde neue Such-/Abrufkontingente)
TOTAL_S = 240           # Gesamtfrist der KI-Suche
MAX_ROWS = 150
MAX_PAGES = 4

SYSTEM = """Du suchst die Standard-Tastaturbelegung (PC, Tastatur) eines Spiels im Netz.
Vorgehen: mit der Websuche Seiten finden, die die PC-Steuerung als Liste oder Tabelle zeigen (offizielle Seiten,
Handbücher, Wikis, Ratgeberseiten), die besten 1-3 mit dem Seitenabruf lesen.
Regeln:
- Nur Zeilen, die auf einer abgerufenen Seite wirklich stehen. Aktion und Taste genau so übernehmen, wie sie dort
  geschrieben sind (key_text wörtlich, z. B. "Left Shift", "Ctrl + C", "F5"). Nichts ergänzen, nichts raten.
- Je Zeile genau eine Tastatur-Taste oder eine Kombination. Zeilen mit Maus, Controller, mehreren Tasten
  ("W, A, S, D", "1-9", "Q / E") weglassen.
- url ist die Adresse der Seite, auf der die Zeile steht.
- area ist die Überschrift der Seite über der Zeile (z. B. "Combat"), sonst leer.
Zum Schluss genau einmal das Werkzeug report_controls aufrufen. Findest du nichts Verlässliches, rufe es mit
leerer Liste auf."""

REPORT_TOOL = {
    "name": "report_controls",
    "description": "Gefundene Standardtasten melden (Abschluss der Suche).",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["bindings"],
        "properties": {
            "bindings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["area", "action", "key_text", "url"],
                    "properties": {
                        "area": {"type": "string"},
                        "action": {"type": "string"},
                        "key_text": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            },
        },
    },
}


def _ask(client, game):
    """KI-Suche ausführen -> Liste der gemeldeten Zeilen (ungeprüft)."""
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 6},
             REPORT_TOOL]
    messages = [{"role": "user", "content": f"Spiel: {game}\nFinde die PC-Standardtasten."}]
    deadline = time.monotonic() + TOTAL_S
    for _ in range(MAX_ROUNDS):
        if time.monotonic() > deadline:
            break
        resp = client.beta.messages.create(
            model=MODEL, max_tokens=16000, betas=BETAS, fallbacks="default",
            output_config={"effort": "medium"}, system=SYSTEM, tools=tools, messages=messages)
        if resp.stop_reason == "refusal":
            raise ValueError("KI hat die Suche abgelehnt")
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "report_controls":
                rows = block.input.get("bindings") if isinstance(block.input, dict) else None
                return rows if isinstance(rows, list) else []
        if resp.stop_reason == "pause_turn":   # serverseitige Suche läuft noch: fortsetzen, kein neuer Text
            messages = [messages[0], {"role": "assistant", "content": resp.content}]
            continue
        raise ValueError("KI hat keine Liste gemeldet")
    raise ValueError("KI-Suche hat zu lange gedauert")


def _norm(s):
    return re.sub(r"\s+", " ", str(s).lower().replace(" ", " ")).strip()


def _page_pairs(page):
    """Was der strukturelle Seitenleser (derselbe wie bei „Suchen“) auf der Seite findet: {aktion: (bereich, taste,
    halten)} - jede Zeile einzeln (Tabellenzeile, Listenpunkt), Taste über das Tastenwörterbuch."""
    return {_norm(a): (area, k, h) for area, a, k, h in web.parse_page(page)}


def verify(rows, fetch=None):
    """Gemeldete Zeilen gegen die Seiten prüfen -> (geprüfte [(bereich, aktion, taste, halten)], urls, verworfen).
    Eine Zeile gilt nur, wenn der Seitenleser auf derselben Seite genau diese Aktion mit genau dieser Taste findet:
    keine Teilwörter („Ctrl“ aus „Ctrl + C“), keine Kreuzzuordnung mehrerer Aktionen in einem Absatz."""
    urls = []
    for r in rows:
        u = str(r.get("url", "")).strip()
        pu = urllib.parse.urlparse(u)
        # nur einfache Seitenadressen (Links mit Query/Fragment könnten von einer Seite untergeschoben sein)
        if u and u not in urls and pu.scheme in ("http", "https") and not pu.query and not pu.fragment:
            urls.append(u)
    fetch = fetch or web.fetch
    pages = {}
    for u in urls[:MAX_PAGES]:
        try:
            pages[u] = _page_pairs(fetch(u))
        except (ValueError, OSError) as e:
            log.info("Seite nicht prüfbar (%s): %s", urllib.parse.urlparse(u).hostname, type(e).__name__)
    ok, dropped, seen = [], 0, set()
    for r in rows[:MAX_ROWS]:
        u, action, key_text = str(r.get("url", "")), str(r.get("action", "")).strip(), str(r.get("key_text", ""))
        found = pages.get(u, {}).get(_norm(action))
        key, _hold = web.page_key(key_text)
        if not found or not key or found[1] != key or action.lower() in seen:
            dropped += 1
            continue
        seen.add(action.lower())
        area = found[0] or str(r.get("area", ""))
        ok.append((area[:40], action, found[1], found[2]))   # Taste und Halten wie auf der Seite gelesen
    return ok, [u for u in urls if u in pages], dropped


OPENAI_SYSTEM = SYSTEM.replace(
    "Zum Schluss genau einmal das Werkzeug report_controls aufrufen. Findest du nichts Verlässliches, rufe es mit\n"
    "leerer Liste auf.",
    'Antworte zum Schluss NUR mit einem JSON-Objekt: {"bindings": [{"area": "...", "action": "...", "key_text": "...", '
    '"url": "..."}]}. Findest du nichts Verlässliches, mit {"bindings": []}.')


def _ask_openai(root, game):
    from . import ai_providers
    data = ai_providers.openai_web_json(root, OPENAI_SYSTEM, f"Spiel: {game}\nFinde die PC-Standardtasten.")
    rows = data.get("bindings") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def lookup(root, game, client=None):
    """KI-Suche + Gegenprüfung -> Ergebnis wie bindings.web.lookup (url, site, title, rows, others, template).
    Anbieter laut ⚙ Einstellungen (Claude oder OpenAI); die Gegenprüfung ist für beide gleich."""
    from . import ai_providers
    if client is None and ai_providers.active(root) == "openai":
        rows = _ask_openai(root, game)
    else:
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=_read_key(root), max_retries=1, timeout=180)
        rows = _ask(client, game)
    ok, urls, dropped = verify(rows)
    if len(ok) < 3:
        raise ValueError(f"KI-Suche: nur {len(ok)} Taste(n) ließen sich auf den Seiten bestätigen "
                         f"({dropped} verworfen) – Adresse einer Seite selbst einfügen")
    main = urls[0] if urls else ""
    host = urllib.parse.urlparse(main).hostname or ""
    tpl = web.to_template(game, ok, main, f"KI-Suche ({web.SITES.get(host, host)})", "")
    tpl["source"]["note"] = (f"Seiten von der KI gefunden, {len(ok)} Tasten vom Seitenleser bestätigt, "
                             f"{dropped} verworfen - Seiten nicht geprüft vertrauenswürdig, Liste bitte ansehen")
    if len(urls) > 1:
        tpl["source"]["more"] = urls[1:]
    return {"url": main, "site": tpl["source"]["site"], "title": f"{len(ok)} bestätigt, {dropped} verworfen",
            "rows": ok, "others": [{"title": u, "url": u, "site": urllib.parse.urlparse(u).hostname} for u in urls[1:]],
            "template": tpl}
