"""Map Genie fuer Bibliotheksspiele: einmal pruefen, ob https://mapgenie.io/<slug> existiert, und die einzelnen
Karten der Spielseite auslesen (Links /<slug>/maps/<karte>). Ergebnis 30 Tage im Zwischenspeicher
mapgenie_cache.json: {"<slug>": {"maps": [{"name", "url"}], "t": Zeitpunkt}}. Leere Liste = gibt es nicht.
Eintraege im alten Format (nur "url") gelten als abgelaufen und werden neu geprueft.

lookup() ist blockierend - im Executor aufrufen; cached() liest nur den Zwischenspeicher (kein Netz)."""
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / "mapgenie_cache.json"
TTL_S = 30 * 86400
MAX_MAPS = 20
MAX_BODY = 2 * 1024 * 1024
HOSTS = ("mapgenie.io", "www.mapgenie.io")
MAP_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


def slug(name):
    s = str(name).lower().replace("'", "").replace("’", "")
    s = re.sub(r"(?<=[a-z0-9])\.(?=[a-z0-9])", "", s)   # S.T.A.L.K.E.R. -> stalker
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def title(map_id):
    """Anzeigename aus der Karten-id: "the-lands-between" -> "The Lands Between"."""
    return " ".join(w[:1].upper() + w[1:] for w in map_id.split("-") if w)


def map_url(sl, map_id):
    return f"https://mapgenie.io/{sl}/maps/{map_id}"


def parse_maps(sl, html):
    """Karten-ids aus der Spielseite (Links auf /<slug>/maps/<karte>, relativ oder absolut), Reihenfolge wie auf
    der Seite, ohne Doppelte."""
    pat = re.compile(r"""href\s*=\s*["'](?:https?://(?:www\.)?mapgenie\.io)?/""" + re.escape(sl)
                     + r"""/maps/([a-z0-9][a-z0-9-]{0,79})/?(?:[?#][^"']*)?["']""", re.I)
    out = []
    for m in pat.finditer(html or ""):
        mid = m.group(1).lower()
        if mid not in out:
            out.append(mid)
        if len(out) >= MAX_MAPS:
            break
    return out


def _load(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _valid_maps(sl, maps):
    """Karten aus dem Zwischenspeicher nur übernehmen, wenn sie zu diesem Spiel gehören (Datei ist von Hand
    änderbar): Spielseite oder /<slug>/maps/<id>."""
    if not isinstance(maps, list):
        return None
    out = []
    for m in maps[:MAX_MAPS]:
        if not (isinstance(m, dict) and isinstance(m.get("name"), str) and 0 < len(m["name"]) <= 60
                and isinstance(m.get("url"), str)):
            return None
        u = m["url"]
        if u != f"https://mapgenie.io/{sl}" and not (u.startswith(f"https://mapgenie.io/{sl}/maps/")
                                                    and MAP_ID.fullmatch(u.rsplit("/", 1)[1])):
            return None
        out.append({"name": m["name"], "url": u})
    return out


def cached(name, cache_path=CACHE, now=time.time):
    """Karten aus dem Zwischenspeicher: Liste (leer = gibt es nicht) oder None (unbekannt/abgelaufen)."""
    sl = slug(name)
    if not sl:
        return []
    hit = _load(cache_path).get(sl)
    if not (isinstance(hit, dict) and isinstance(hit.get("t"), (int, float)) and 0 <= now() - hit["t"] < TTL_S):
        return None
    return _valid_maps(sl, hit.get("maps"))


def lookup(name, cache_path=CACHE, urlopen=urllib.request.urlopen, now=time.time):
    """Karten des Spiels bei Map Genie: [{"name", "url"}] - je Karte ein Direktlink, ohne erkennbare Karten die
    Spielseite; leer = gibt es nicht. Netzwerkfehler (ausser 404) werfen und werden nicht gemerkt."""
    sl = slug(name)
    if not sl:
        return []
    hit = cached(name, cache_path, now)
    if hit is not None:
        return hit
    url = f"https://mapgenie.io/{sl}"
    found = []
    try:
        r = urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=5)
        try:
            final = r.geturl() or url
            body = r.read(MAX_BODY) if hasattr(r, "read") else b""
        finally:
            r.close()
        u = urlparse(final)
        path = u.path.lower().rstrip("/")
        # Umleitung auf Startseite/anderes Spiel = nicht vorhanden
        if (u.hostname or "").lower() in HOSTS and (path == "/" + sl or path.startswith("/" + sl + "/")):
            ids = []
            direct = re.fullmatch("/" + re.escape(sl) + r"/maps/([a-z0-9][a-z0-9-]{0,79})", path)
            if direct:
                ids.append(direct.group(1))
            text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else ""
            ids += [m for m in parse_maps(sl, text) if m not in ids]
            found = ([{"name": title(m), "url": map_url(sl, m)} for m in ids[:MAX_MAPS]]
                     or [{"name": "Map Genie", "url": url}])
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    cache = _load(cache_path)
    cache[sl] = {"maps": found, "t": now()}
    try:
        _save(cache_path, cache)
    except OSError:
        pass
    return found
