"""Standardtasten eines Spiels aus einer Steuerungs-Seite im Netz (Ratgeberseiten wie Magic Game World, Shacknews).

Nach außen geht nur der Spielname (Suche) bzw. die vom Nutzer genannte Adresse. Gelesen wird generisch:
Tabellen „Aktion | Taste“ und Zeilen „Taste: Aktion“ / „Aktion – Taste“; welche Seite die Taste ist, entscheidet
das Tastenwörterbuch (keynames.py). Mehrdeutiges (WASD, Maus, „1-9“) bleibt weg - nie geraten. Überschriften der
Seite werden Bereiche. Ergebnis ist eine semantische Vorlage mit Quelle (Adresse, Seite, Datum); gespeichert wird
sie erst nach Bestätigung im Editor, lokal unter templates/<spiel>/web-<seite>.json (nicht im Git).
"""
import html
import ipaddress
import json
import re
import socket
import time
import urllib.parse
import urllib.request

from . import keynames as kn

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TabletDeck/1.0"
MAX_PAGE = 3 * 1024 * 1024
TIMEOUT = 20
MGW_SEARCH = "https://www.magicgameworld.com/wp-json/wp/v2/search?per_page=10&search="
GUIDE_WORDS = re.compile(r"(controls?|keybind|key bindings|keyboard|hotkeys?|shortcuts?)", re.I)
MAX_ITEMS = 16


def _public_url(url):
    """Nur http(s) an öffentliche Adressen (kein Heimnetz, kein localhost) - der Hub ruft Adressen aus dem
    Editor ab und darf dabei nichts im lokalen Netz erreichen."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("nur http(s)-Adressen")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except OSError:
        raise ValueError("Adresse nicht erreichbar") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise ValueError("nur öffentliche Adressen")
    return url


def fetch(url):
    _public_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:   # Weiterleitungen: Ziel erneut prüfen
        _public_url(r.geturl())
        return r.read(MAX_PAGE).decode("utf-8", errors="replace")


def search(game):
    """Steuerungs-Seiten zu einem Spiel: [{title, url, site}] (Magic Game World, WordPress-Suche)."""
    q = urllib.parse.quote(f"{game} keyboard controls")
    try:
        data = json.loads(fetch(MGW_SEARCH + q))
    except (ValueError, OSError):
        return []
    want = {t for t in re.findall(r"[a-z0-9]+", game.lower()) if len(t) >= 3 and t not in ("the", "and")}
    out = []
    for d in data if isinstance(data, list) else []:
        title = html.unescape(str(d.get("title", "")))
        words = set(re.findall(r"[a-z0-9]+", title.lower()))
        if GUIDE_WORDS.search(title) and want and want <= words:
            out.append({"title": title, "url": d.get("url"), "site": "Magic Game World"})
    # genauer Titel zuerst („Frostpunk“ vor „Frostpunk 2“)
    out.sort(key=lambda x: len(set(re.findall(r"[a-z0-9]+", x["title"].lower())) - want))
    return out


# ---------------------------------------------------------------- Seite lesen
def _clean(fragment):
    t = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


_PAREN = re.compile(r"\(([^)]*)\)")


def page_key(text):
    """Taste aus Seitentext: 'Space Bar', 'Left Ctrl + C', 'E (hold)', 'Hold F', 'F1 / F2' (erste Taste).
    -> (taste, halten) oder (None, False) bei Maus, WASD, Bereichen wie '1-9' oder Unklarem."""
    t = text.strip().strip(".").strip()
    hold = bool(re.search(r"\b(hold|halten|gedrückt)\b", t, re.I))
    t = _PAREN.sub("", t)
    t = re.sub(r"^\s*(hold|press|tap|halten|drücken)\s+", "", t, flags=re.I).strip()
    if not t or len(t) > 30 or re.search(r"mouse|maus|wheel|lmb|rmb|mmb|arrow keys|wasd|\d\s*-\s*\d", t, re.I):
        return None, False
    first = re.split(r"\s*(?:/|\bor\b|\boder\b|,)\s*", t)[0]
    first = re.sub(r"\s*\+\s*", "+", first)
    if " " in first and "+" not in first:
        first = first   # „Page Up“, „Left Shift“, „Space Bar“ - Wörterbuch kennt sie zusammengeschrieben
    k = kn.text_key(first.replace(" ", "")) if "+" not in first else kn.combo(first.split("+"), lambda s: kn.text_key(
        s.replace(" ", "")))
    return k, hold


def _pair(a, b):
    """Zwei Texte -> (aktion, taste, halten) - die Seite mit eindeutiger Taste ist die Taste."""
    ka, ha = page_key(a)
    kb, hb = page_key(b)
    if kb and not ka:
        return a, kb, hb
    if ka and not kb:
        return b, ka, ha
    return None


_BLOCK = re.compile(r"<(h[1-4]|tr|li|p)\b[^>]*>(.*?)</\1>", re.S | re.I)
_SEP = re.compile(r"\s*(?::|\s[–—-]\s)\s*")


def parse_page(page):
    """HTML -> [(bereich, aktion, taste, halten)] in Seitenreihenfolge."""
    m = re.search(r"<(article|main)\b.*?</\1>", page, re.S | re.I)
    body = m.group(0) if m else page
    rows, area = [], ""
    for tag, inner in ((m.group(1).lower(), m.group(2)) for m in _BLOCK.finditer(body)):
        if tag.startswith("h"):
            area = _clean(inner)[:40]
            continue
        if tag == "tr":
            cells = [_clean(c) for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", inner, re.S | re.I)]
            if len(cells) == 1 and cells[0]:
                area = cells[0][:40]   # Zwischenüberschrift in der Tabelle
                continue
            if len(cells) >= 2:
                p = _pair(cells[0], cells[1])
                if p:
                    rows.append((area,) + p)
            continue
        text = _clean(inner)
        if not text or len(text) > 140:
            continue
        parts = _SEP.split(text, maxsplit=1)
        if len(parts) == 2:
            p = _pair(parts[0], parts[1])
            if p:
                rows.append((area,) + p)
    # doppelte Aktionen: erste gilt
    seen, out = set(), []
    for r in rows:
        if r[1].lower() not in seen and 1 < len(r[1]) <= 60:
            seen.add(r[1].lower())
            out.append(r)
    return out


def _title(page):
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    return _clean(m.group(1))[:120] if m else ""


def to_template(game, rows, url, site, title):
    """Gelesene Zeilen -> semantische Vorlage mit Quelle; Bereiche nach Überschriften (je höchstens 16 Tasten)."""
    areas, index = [], {}
    for area, action, key, hold in rows:
        name = (area or "Steuerung")[:40]
        if name not in index or len(areas[index[name]]["items"]) >= MAX_ITEMS:
            index[name] = len(areas)
            areas.append({"title": name, "items": []})
        it = {"label": action[:40], "action": action[:120], "key": key}
        if hold:
            it["hold"] = True
        areas[index[name]]["items"].append(it)
    sections, cur = [], None
    for a in areas:   # höchstens 6 Bereiche je Seite
        if cur is None or len(cur["areas"]) >= 6:
            cur = {"title": f"Steuerung {len(sections) + 1}" if sections else "Steuerung", "areas": []}
            sections.append(cur)
        cur["areas"].append(a)
    return {"title": f"{game} (Netz)"[:40], "source": {"site": site, "url": url, "title": title,
                                                         "date": time.strftime("%Y-%m-%d")},
            "sections": sections[:12]}


def lookup(game, url=None):
    """Seite suchen (oder die genannte Adresse nehmen), lesen -> {url, site, title, rows, template} oder Fehler."""
    cands = [] if url else search(game)
    if not url and not cands:
        raise ValueError("keine Steuerungs-Seite gefunden – Adresse einer Seite (z. B. Shacknews) einfügen")
    target = url or cands[0]["url"]
    site = urllib.parse.urlparse(target).hostname or ""
    site = {"www.magicgameworld.com": "Magic Game World", "magicgameworld.com": "Magic Game World",
            "www.shacknews.com": "Shacknews", "shacknews.com": "Shacknews"}.get(site, site)
    page = fetch(target)
    rows = parse_page(page)
    if len(rows) < 3:
        raise ValueError(f"auf der Seite keine Tastentabelle erkannt ({len(rows)} Zeilen)")
    title = _title(page)
    return {"url": target, "site": site, "title": title, "rows": rows,
            "others": [c for c in cands[1:4]], "template": to_template(game, rows, target, site, title)}
