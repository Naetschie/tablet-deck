"""Map Genie fuer Bibliotheksspiele: einmal pruefen, ob https://mapgenie.io/<slug> existiert (Ergebnis 30 Tage
im Zwischenspeicher mapgenie_cache.json). Blockierend - im Executor aufrufen."""
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
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


def slug(name):
    s = str(name).lower().replace("'", "").replace("’", "")
    s = re.sub(r"(?<=[a-z0-9])\.(?=[a-z0-9])", "", s)   # S.T.A.L.K.E.R. -> stalker
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


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


def lookup(name, cache_path=CACHE, urlopen=urllib.request.urlopen, now=time.time):
    """URL der Map-Genie-Seite oder None (gibt es nicht). Netzwerkfehler (ausser 404) werfen und werden
    nicht gemerkt."""
    sl = slug(name)
    if not sl:
        return None
    cache = _load(cache_path)
    hit = cache.get(sl)
    if isinstance(hit, dict) and isinstance(hit.get("t"), (int, float)) and now() - hit["t"] < TTL_S:
        return hit.get("url") if isinstance(hit.get("url"), str) else None
    url = f"https://mapgenie.io/{sl}"
    found = None
    try:
        r = urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=5)
        try:
            final = r.geturl() or url
        finally:
            r.close()
        u = urlparse(final)
        path = u.path.lower().rstrip("/")
        if (u.hostname or "").lower() in ("mapgenie.io", "www.mapgenie.io") and (path == "/" + sl or path.startswith("/" + sl + "/")):
            found = url                # Umleitung auf Startseite/anderes Spiel = nicht vorhanden
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    cache[sl] = {"url": found, "t": now()}
    try:
        _save(cache_path, cache)
    except OSError:
        pass
    return found
