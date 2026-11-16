"""Startseite der Web-Kachel: Lesezeichen, vom PC gesendete Seiten, Verlauf.

Liegt am PC (nicht im Git): bookmarks.json (Lesezeichen, auch von Hand bearbeitbar) und web_history.json
(gesendet + Verlauf). Nur http(s)-Adressen; was die Web-Kachel tatsächlich laden darf, prüft der Launcher
(Heimnetz gesperrt).
"""
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

log = logging.getLogger("web")
URL = re.compile(r"(?i)https?://[^\s/]+[^\s]*")
MAX_URL, MAX_TITLE = 2048, 120
MAX_BOOKMARKS, MAX_SENT, MAX_HISTORY = 100, 30, 100


def clean_url(url):
    if not isinstance(url, str):
        return None
    url = url.strip()
    return url if len(url) <= MAX_URL and URL.fullmatch(url) else None


def _title(t):
    return t.strip()[:MAX_TITLE] if isinstance(t, str) else ""


def _save(path, data):
    """Atomar schreiben; Fehler (volle/gesperrte Platte) nur loggen - die Startseite ist kein Grund, die
    Steuerverbindung zu verlieren."""
    try:
        _write(path, data)
    except OSError as e:
        log.error("%s nicht gespeichert: %s", path.name, e)


def _write(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".web-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class WebHome:
    def __init__(self, root):
        self.bm_path = Path(root) / "bookmarks.json"
        self.hist_path = Path(root) / "web_history.json"
        self.bookmarks, self.sent, self.history = [], [], []
        self.bm_mtime = None
        self._load()

    def _load(self):
        self._load_bookmarks()
        try:
            d = json.loads(self.hist_path.read_text(encoding="utf-8"))
            for key in ("sent", "history"):
                setattr(self, key, [e for e in d.get(key, []) if isinstance(e, dict) and clean_url(e.get("url"))
                                    and isinstance(e.get("time"), (int, float))])
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError) as e:
            log.error("web_history.json fehlerhaft, Verlauf leer: %s", e)

    def _load_bookmarks(self):
        """bookmarks.json (neu) lesen - auch zur Laufzeit, wenn sie von Hand geändert wurde."""
        try:
            self.bm_mtime = self.bm_path.stat().st_mtime
        except OSError:
            self.bm_mtime = None
            return
        try:
            d = json.loads(self.bm_path.read_text(encoding="utf-8"))
            self.bookmarks = [{"title": _title(b.get("title")), "url": clean_url(b.get("url"))}
                              for b in d.get("bookmarks", []) if isinstance(b, dict) and clean_url(b.get("url"))]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError) as e:
            log.error("bookmarks.json fehlerhaft, Lesezeichen leer: %s", e)

    def _check_bookmarks(self):
        try:
            mtime = self.bm_path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != self.bm_mtime:
            self.bookmarks = []
            self._load_bookmarks()

    def data(self):
        self._check_bookmarks()
        return {"bookmarks": self.bookmarks[:MAX_BOOKMARKS], "sent": self.sent[:MAX_SENT],
                "history": self.history[:MAX_HISTORY]}

    def _push(self, lst, url, title, limit):
        """Neuester Eintrag zuerst, jede Adresse nur einmal."""
        lst[:] = [e for e in lst if e["url"] != url]
        lst.insert(0, {"url": url, "title": _title(title), "time": int(time.time())})
        del lst[limit:]
        _save(self.hist_path, {"sent": self.sent, "history": self.history})

    def add_sent(self, url, title=""):
        url = clean_url(url)
        if url:
            self._push(self.sent, url, title, MAX_SENT)
        return bool(url)

    def add_history(self, url, title=""):
        url = clean_url(url)
        if not url:
            return False
        url = url.split("#", 1)[0]   # Sprungmarken nicht als eigene Einträge
        now = time.time()
        # Weiterleitungen / Hin und Her zwischen zwei Seiten: kurz nacheinander (3 s) nicht erneut eintragen
        for e in self.history[:3]:
            if e["url"] == url and now - e["time"] < 3 and e is not self.history[0]:
                return False
        for e in self.sent:   # gesendete Seite bekommt den Titel, sobald sie geladen ist
            if e["url"] == url and not e["title"] and title:
                e["title"] = _title(title)
        if self.history and self.history[0]["url"] == url:
            if title and not self.history[0]["title"]:   # Titel kommt oft erst nach dem Laden
                self.history[0]["title"] = _title(title)
                _save(self.hist_path, {"sent": self.sent, "history": self.history})
                return True
            return False
        self._push(self.history, url, title, MAX_HISTORY)
        return True

    def clear_history(self):
        self.history, self.sent = [], []
        _save(self.hist_path, {"sent": [], "history": []})

    def bookmark(self, url, title="", add=True):
        self._check_bookmarks()   # von Hand geänderte Datei nicht überschreiben
        url = clean_url(url)
        if not url:
            raise ValueError("ungültige Adresse")
        self.bookmarks = [b for b in self.bookmarks if b["url"] != url]
        if add:
            if len(self.bookmarks) >= MAX_BOOKMARKS:
                raise ValueError("zu viele Lesezeichen")
            self.bookmarks.append({"title": _title(title), "url": url})
        _save(self.bm_path, {"bookmarks": self.bookmarks})
        try:
            self.bm_mtime = self.bm_path.stat().st_mtime   # eigene Änderung nicht als "von Hand" werten
        except OSError:
            pass
