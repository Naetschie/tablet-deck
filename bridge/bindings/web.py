"""Standardtasten eines Spiels aus einer Steuerungs-Seite im Netz (Ratgeberseiten wie Magic Game World, Shacknews).

Nach außen geht nur der Spielname (Suche) bzw. die vom Nutzer genannte Adresse. Gelesen wird generisch:
Tabellen „Aktion | Taste“ und Zeilen „Taste: Aktion“ / „Aktion – Taste“; welche Seite die Taste ist, entscheidet
das Tastenwörterbuch (keynames.py). Mehrdeutiges (WASD, „W, A, S, D“, „Left / Right“, Maus, „1-9“) bleibt weg -
nie geraten. Überschriften der Seite werden Bereiche. Ergebnis ist eine semantische Vorlage mit Quelle (Adresse,
Seite, Datum); gespeichert wird sie erst nach Bestätigung im Editor, lokal unter templates/<spiel>/web-*.json.

Abruf: nur http(s) auf Port 80/443 an öffentliche Adressen; die IP wird einmal aufgelöst, geprüft und genau sie
verbunden (kein DNS-Rebinding), kein Proxy, Weiterleitungen werden vor dem Folgen geprüft (höchstens 3), Größe
und Gesamtzeit begrenzt. Gelesen wird linear (html.parser) - präparierte Seiten können den Hub nicht aufhalten.
"""
import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.parse
from html.parser import HTMLParser

from . import keynames as kn

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TabletDeck/1.0"
MAX_PAGE = 2 * 1024 * 1024
TIMEOUT = 15          # je Verbindung/Lesevorgang
TOTAL = 30            # Gesamtfrist für einen Abruf
MAX_REDIRECTS = 3
MGW_HOST = "www.magicgameworld.com"
MGW_SEARCH = f"https://{MGW_HOST}/wp-json/wp/v2/search?per_page=10&search="
GUIDE_WORDS = re.compile(r"(controls?|keybind|key bindings|keyboard|hotkeys?|shortcuts?)", re.I)
MAX_ITEMS = 16


# ---------------------------------------------------------------- Abruf
def _check_url(url):
    """(schema, host, port, pfad) einer erlaubten Adresse; sonst ValueError."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("nur http(s)-Adressen")
    port = u.port or (443 if u.scheme == "https" else 80)
    if port not in (80, 443):
        raise ValueError("nur Standard-Ports")
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    return u.scheme, u.hostname, port, path


def _public_ip(host, port):
    """Host einmal auflösen; alle Adressen müssen öffentlich sein. -> erste Adresse."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError("Adresse nicht erreichbar") from None
    ips = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
    if not ips:
        raise ValueError("Adresse nicht erreichbar")
    for ip in ips:
        mapped = getattr(ip, "ipv4_mapped", None) or (ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
                                                       if ip.version == 6 and ip in ipaddress.ip_network("64:ff9b::/96")
                                                       else None)
        if not ip.is_global or (mapped and not mapped.is_global):
            raise ValueError("nur öffentliche Adressen")
    return str(ips[0])


def _public_url(url):
    """Prüft Schema, Port und dass der Host nur öffentliche Adressen hat (für Tests und Vorprüfung)."""
    _scheme, host, port, _path = _check_url(url)
    _public_ip(host, port)
    return url


def _get(url, deadline):
    scheme, host, port, path = _check_url(url)
    ip = _public_ip(host, port)
    left = max(1.0, deadline - time.monotonic())
    sock = socket.create_connection((ip, port), timeout=min(TIMEOUT, left))   # genau die geprüfte Adresse
    if scheme == "https":
        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    conn = http.client.HTTPConnection(host, port, timeout=min(TIMEOUT, left))
    conn.sock = sock
    try:
        conn.request("GET", path, headers={"Host": host, "User-Agent": UA, "Accept-Encoding": "identity",
                                           "Accept": "text/html,application/json"})
        r = conn.getresponse()
        if r.status in (301, 302, 303, 307, 308):
            return None, urllib.parse.urljoin(url, r.getheader("Location") or "")
        if r.status != 200:
            raise ValueError(f"Seite antwortet mit {r.status}")
        chunks, size = [], 0
        while size < MAX_PAGE:
            if time.monotonic() > deadline:
                raise ValueError("Seite lädt zu langsam")
            c = r.read(65536)
            if not c:
                break
            chunks.append(c)
            size += len(c)
        return b"".join(chunks)[:MAX_PAGE].decode("utf-8", errors="replace"), None
    finally:
        conn.close()


def fetch(url):
    deadline = time.monotonic() + TOTAL
    for _ in range(MAX_REDIRECTS + 1):
        body, nxt = _get(url, deadline)   # jede Weiterleitung wird vor dem Abruf geprüft (_check_url/_public_ip)
        if body is not None:
            return body
        url = nxt
    raise ValueError("zu viele Weiterleitungen")


# ---------------------------------------------------------------- Suche
def name_variants(*names):
    """Suchnamen: Abkürzungen mit Punkten zusammenziehen („S.T.A.L.K.E.R. 2“ -> „STALKER 2“), Zeichen wie ™ weg,
    dazu ohne Untertitel (vor „:“ / „ - “). Reihenfolge: genau zuerst."""
    out = []
    for n in names:
        if not n:
            continue
        n = re.sub(r"\b((?:[A-Za-z]\.){2,}[A-Za-z]?\.?)", lambda m: m.group(1).replace(".", ""), str(n))
        n = re.sub(r"[®™©]", "", n)
        for v in (n, re.split(r"\s*(?::|\s[-–]\s)\s*", n)[0]):
            v = re.sub(r"\s+", " ", re.sub(r"[^\w\s'&]", " ", v)).strip()
            if v and v.lower() not in [o.lower() for o in out]:
                out.append(v)
    return out


def _search_one(game):
    q = urllib.parse.quote(f"{game} keyboard controls")
    try:
        data = json.loads(fetch(MGW_SEARCH + q))
    except (ValueError, OSError):
        return []
    want = {t for t in re.findall(r"[a-z0-9]+", game.lower()) if len(t) >= 3 and t not in ("the", "and")}
    out = []
    for d in data if isinstance(data, list) else []:
        title = html.unescape(str(d.get("title", "")))
        url = str(d.get("url", ""))
        words = set(re.findall(r"[a-z0-9]+", title.lower()))
        if (urllib.parse.urlparse(url).hostname == MGW_HOST and GUIDE_WORDS.search(title)
                and want and want <= words):
            out.append({"title": title, "url": url, "site": "Magic Game World"})
    out.sort(key=lambda x: len(set(re.findall(r"[a-z0-9]+", x["title"].lower())) - want))   # genauer Titel zuerst
    return out


def search(game, *more_names):
    """Steuerungs-Seiten zu einem Spiel: [{title, url, site}]; probiert mehrere Schreibweisen des Namens."""
    for name in name_variants(game, *more_names):
        found = _search_one(name)
        if found:
            return found
    return []


# ---------------------------------------------------------------- Seite lesen
_PAREN = re.compile(r"\(([^)]*)\)")
_MULTI = re.compile(r"\s*(?:/|\bor\b|\boder\b|,|&|\band\b)\s*", re.I)


def page_key(text):
    """Taste aus Seitentext: 'Space Bar', 'Left Ctrl + C', 'E (hold)', 'Hold F' -> (taste, halten).
    Mehrere Tasten in einer Zelle ('W, A, S, D', 'Left / Right', 'F1 / F2'), Maus, WASD, '1-9' -> (None, False)."""
    t = text.strip().strip(".").strip()
    hold = bool(re.search(r"\b(hold|halten|gedrückt)\b", t, re.I))
    t = _PAREN.sub("", t)
    t = re.sub(r"^\s*(hold|press|tap|halten|drücken)\s+", "", t, flags=re.I).strip()
    if not t or len(t) > 30 or re.search(r"mouse|maus|wheel|lmb|rmb|mmb|arrow keys|wasd|\d\s*-\s*\d", t, re.I):
        return None, False
    if len([p for p in _MULTI.split(t) if p.strip()]) > 1:
        return None, False   # mehrere Tasten: welche für diese Aktion gilt, ist nicht eindeutig
    if "+" in t:
        k = kn.combo([p.replace(" ", "") for p in re.split(r"\s*\+\s*", t)], kn.text_key)
    else:
        k = kn.text_key(t.replace(" ", ""))
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


_SEP = re.compile(r"\s*(?::|\s[–—-]\s)\s*")
_BLOCKS = {"h1", "h2", "h3", "h4", "li", "p", "tr"}


class _Blocks(HTMLParser):
    """Linearer Durchlauf: Blöcke (Überschrift, Listenpunkt, Absatz, Tabellenzeile mit Zellen) in Reihenfolge.
    Nur innerhalb von <article>/<main>, wenn die Seite so etwas hat."""

    def __init__(self, scoped):
        super().__init__(convert_charrefs=True)
        self.scoped, self.depth, self.out = scoped, 0, []
        self.cur, self.cells, self.cell = None, [], None

    def _inside(self):
        return not self.scoped or self.depth > 0

    def _flush(self):
        if self.cur:
            tag, buf = self.cur
            if tag == "tr":
                if self.cell is not None:
                    self.cells.append("".join(self.cell))
                self.out.append(("tr", [re.sub(r"\s+", " ", c).strip() for c in self.cells]))
            else:
                self.out.append((tag, re.sub(r"\s+", " ", "".join(buf)).strip()))
        self.cur, self.cells, self.cell = None, [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("article", "main"):
            self.depth += 1
            return
        if not self._inside():
            return
        if tag in _BLOCKS:
            self._flush()
            self.cur = (tag, [])
        elif tag in ("td", "th") and self.cur and self.cur[0] == "tr":
            if self.cell is not None:
                self.cells.append("".join(self.cell))
            self.cell = []
        elif tag == "br" and self.cur:
            self.handle_data(" ")

    def handle_endtag(self, tag):
        if tag in ("article", "main"):
            self.depth = max(0, self.depth - 1)
            self._flush()
            return
        if self.cur and tag == self.cur[0]:
            self._flush()

    def handle_data(self, data):
        if not self.cur or not self._inside():
            return
        if self.cur[0] == "tr":
            if self.cell is not None:
                self.cell.append(data)
        else:
            self.cur[1].append(data)


def parse_page(page):
    """HTML -> [(bereich, aktion, taste, halten)] in Seitenreihenfolge."""
    page = page[:MAX_PAGE]
    low = page[:MAX_PAGE].lower()
    p = _Blocks(scoped=("<article" in low or "<main" in low))
    p.feed(page)
    p.close()
    p._flush()
    rows, area = [], ""
    for tag, content in p.out:
        if tag.startswith("h"):
            area = content[:40]
        elif tag == "tr":
            cells = [c for c in content if c]
            if len(cells) == 1:
                area = cells[0][:40]   # Zwischenüberschrift in der Tabelle
            elif len(cells) >= 2:
                pr = _pair(cells[0], cells[1])
                if pr:
                    rows.append((area,) + pr)
        elif content and len(content) <= 140:
            parts = _SEP.split(content, maxsplit=1)
            if len(parts) == 2:
                pr = _pair(parts[0], parts[1])
                if pr:
                    rows.append((area,) + pr)
    seen, out = set(), []
    for r in rows:   # doppelte Aktionen: erste gilt
        if r[1].lower() not in seen and 1 < len(r[1]) <= 60:
            seen.add(r[1].lower())
            out.append(r)
    return out


def _title(page):
    m = re.search(r"<title[^>]*>([^<]{0,300})</title>", page[:200000], re.I)
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()[:120] if m else ""


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


SITES = {"www.magicgameworld.com": "Magic Game World", "magicgameworld.com": "Magic Game World",
         "www.shacknews.com": "Shacknews", "shacknews.com": "Shacknews"}


def lookup(game, url=None, *more_names):
    """Seite suchen (oder die genannte Adresse nehmen), lesen -> {url, site, title, rows, template} oder Fehler."""
    cands = [] if url else search(game, *more_names)
    if not url and not cands:
        raise ValueError("keine Steuerungs-Seite gefunden – Adresse einer Seite (z. B. Shacknews) einfügen")
    target = url or cands[0]["url"]
    host = urllib.parse.urlparse(target).hostname or ""
    site = SITES.get(host, host)
    page = fetch(target)
    rows = parse_page(page)
    if len(rows) < 3:
        raise ValueError(f"auf der Seite keine Tastentabelle erkannt ({len(rows)} Zeilen)")
    title = _title(page)
    return {"url": target, "site": site, "title": title, "rows": rows,
            "others": [c for c in cands[1:4]], "template": to_template(game, rows, target, site, title)}
