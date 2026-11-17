"""Steuerung eines beliebigen Spiels einlesen (Rückfall für Spiele ohne eigenen Adapter) - generisch, nicht je Spiel.

Ablauf: Orte bestimmen (locate.py: Benutzerordner, AppData, Steam-Cloud, Registry, Installationsordner, Unreal-
Projekt, Unity-Hersteller) -> Dateien öffnen (containers.py: Text, gepackt, Unreal-Spielstand, verschlüsselt) ->
lesen (readers.py: Formatleser, sonst allgemeiner Strukturleser) -> beste Quelle wählen und den Zustand melden:
  read          genau gelesen (bekanntes Format)
  recognized    allgemein erkannt - bitte prüfen
  only_changes  Spiel speichert nur geänderte Tasten, keine vorhanden (Standard steckt in den Spieldaten)
  unreadable    Steuerungsdatei gefunden, aber verschlüsselt/binär
  unknown       Steuerungsdatei gefunden, Format unbekannt
  none          nichts gefunden
Lernmodus: snapshot() vor einer Tastenänderung im Spiel, changed() danach -> die geänderte Datei ist die
Steuerungsdatei; sie lässt sich als gelernte Quelle merken (search(learned=...)).
"""
import os
import re
import time
from pathlib import Path

from . import locate
from .containers import open_bytes
from .readers import read_content

MAX_FILE = 2 * 1024 * 1024
MAX_FILES = 4000
STRONG = re.compile(r"(keybind|keymap|key_?bindings?|hotkey|shortcut|actionmap|bindings?|controls?|"
                    r"input|keys|preset|mapping)", re.I)
WEAK = re.compile(r"(setting|config|option|profile|pref)", re.I)
TEXT_EXT = (".ini", ".cfg", ".xml", ".json", ".txt", ".config", ".settings", ".yaml", ".yml", ".conf", ".dat",
            ".sav", ".bin", ".save", ".preset", ".dayzprofile")
SKIP_DIRS = {"logs", "log", "crashes", "crashdumps", "cache", "shadercache", "shaders", "webcache", "screenshots",
             "videos", "movies", "audio", "sound", "textures", "mods", "workshop", "backup", "backups", "dumps"}

STATE_TEXT = {
    "read": "Belegung gelesen",
    "recognized": "Belegung erkannt – bitte prüfen",
    "only_changes": "Spiel speichert nur geänderte Tasten – keine vorhanden; die Standardbelegung steckt in den "
                    "Spieldaten (nicht lesbar). Tasten bitte im Editor eintragen",
    "unreadable": "Steuerungsdatei gefunden, aber nicht lesbar (verschlüsselt/binär) – Tasten bitte im Editor "
                  "eintragen",
    "unknown": "Datei mit Steuerungs-Namen gefunden, Format unbekannt – mit „Belegungsdatei finden“ (Lernmodus) "
               "prüfen oder Tasten im Editor eintragen",
    "none": "keine Steuerungsdatei gefunden – Tasten bitte im Editor eintragen",
}


class Found:
    def __init__(self, state, bindings=None, message="", file=None, method=""):
        self.state, self.bindings, self.message, self.file, self.method = state, bindings or {}, message, file, method

    @property
    def count(self):
        return sum(1 for v in self.bindings.values() if v[0])


def _shown(path):
    """Dateiname ohne vorangestellten Profilnamen ("Spieler.dayz_preset_User.xml" -> "…dayz_preset_User.xml")."""
    name = Path(str(path)).name
    return re.sub(r"^[^.]+\.(?=[^.]+\.[^.]+$)", "…", name)


def _is_link(p):
    try:
        return p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p))
    except OSError:
        return True


def _files(d, limit=MAX_FILES):
    n = 0
    for root, dirs, files in os.walk(d):
        n += 1 + len(dirs)
        dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS and not x.lower().startswith("webcache")
                   and not _is_link(Path(root) / x)]
        for f in files:
            n += 1
            if n > limit:
                return
            yield Path(root) / f


def _wanted(f, user_dir):
    """Benutzerordner: Steuerungs- und Einstellungsdateien; Installationsordner: nur Steuerungs-Namen."""
    low = f.name.lower()
    strong = STRONG.search(low) is not None
    if not low.endswith(TEXT_EXT) and not strong:
        return False
    return strong or (user_dir and WEAK.search(low) is not None)


def _registry_texts(regpath):
    """Unity PlayerPrefs u. ä.: Werte unter HKCU\\<regpath> als Text (REG_BINARY mit Null am Ende)."""
    out = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, regpath) as k:
            for i in range(2000):
                try:
                    _name, val, _typ = winreg.EnumValue(k, i)
                except OSError:
                    break
                if isinstance(val, bytes):
                    kind, content = open_bytes(val.rstrip(b"\x00"))
                    val = content if kind == "text" else None
                if isinstance(val, str) and ("bindings" in val or "<Keyboard>" in val or "Key" in val):
                    out.append(val)
    except (OSError, ImportError):
        pass
    return out


_EMPTY_ENTRY = re.compile(r"^\s*[\w.\-]+\s*[=:]\s*$")
_FILLED_ENTRY = re.compile(r"^\s*[\w.\-]+\s*[=:]\s*\S")


def _empty_mapping(text):
    """Datei mit vielen Einträgen ohne Wert („Inventory =“): das Spiel speichert nur Änderungen, es gibt keine."""
    lines = text.splitlines()
    empty = sum(1 for line in lines if _EMPTY_ENTRY.match(line))
    filled = sum(1 for line in lines if _FILLED_ENTRY.match(line) and "struct.begin" not in line)
    return empty >= 5 and filled <= 1


def _rank(r, user_dir, strong, mtime):
    return (r.count > 0, r.method == "exact", user_dir, strong, r.count, mtime)


def search(name, install_dir=None, appid=None, learned=None):
    """Steuerung suchen -> Found (Zustand, Tasten, Meldung, Datei)."""
    cands, only_changes, unreadable, unknown = [], 0, 0, 0
    if learned and Path(learned).is_file():   # 1. im Lernmodus gefundene Datei
        try:
            kind, content = open_bytes(Path(learned).read_bytes()[:MAX_FILE])
            r = read_content(kind, content)
            if r and r.count:
                cands.append((_rank(r, True, True, 1e18), r, Path(learned), True))
            elif kind in ("encrypted", "binary"):
                return Found("unreadable", message=STATE_TEXT["unreadable"] + " (gelernte Datei)", file=str(learned))
        except OSError:
            pass
    dirs, regs = locate.locations(name, install_dir, appid)
    for reg in regs:                          # 2. Registry (Unity PlayerPrefs)
        for text in _registry_texts(reg):
            try:
                r = read_content("text", text)
            except Exception:  # noqa: BLE001 - ein seltsamer Wert darf die Suche nicht abbrechen
                continue
            if r and r.count:
                cands.append((_rank(r, True, True, time.time()), r, "Registry", True))
            elif r and r.only_changes:
                only_changes += 1
    for d, user_dir in dirs:                  # 3. Dateien
        for f in _files(d, MAX_FILES if user_dir else MAX_FILES * 2):
            if not _wanted(f, user_dir):
                continue
            try:
                st = f.stat()
                if st.st_size > MAX_FILE or st.st_size == 0:
                    continue
                strong = STRONG.search(f.name) is not None
                kind, content = open_bytes(f.read_bytes())
                r = read_content(kind, content)
            except Exception:  # noqa: BLE001 - eine seltsame Datei darf die Suche nicht abbrechen
                continue
            if r and r.count:
                cands.append((_rank(r, user_dir, strong, st.st_mtime), r, f, user_dir))
            elif r and r.only_changes:
                only_changes += 1
            elif kind in ("encrypted", "binary") and (user_dir or re.search(r"bind|key", f.name, re.I)):
                unreadable += 1   # Steuerungs- oder Einstellungsdatei, aber nicht lesbar
            elif strong and kind == "text" and user_dir and _empty_mapping(content):
                only_changes += 1   # Steuerungsdatei mit lauter leeren Einträgen: nichts geändert
            elif strong and kind == "text" and user_dir and len(content.strip()) > 64:
                unknown += 1      # fast leere Dateien (z. B. „Input.ini“ mit 2 Bytes) zählen nicht
    if cands:
        _, r, f, in_user = max(cands, key=lambda c: c[0])
        bind = dict(r.bindings)
        # Benutzerordner hat oft nur die geänderten Tasten (z. B. Input.ini), der Installationsordner den Standard:
        # zusammenführen (Standard zuerst, eigene Änderungen gewinnen)
        defaults = [c for c in cands if not c[3] and c[1].method == r.method and c[1].count > r.count]
        if in_user and defaults:
            base = dict(max(defaults, key=lambda c: c[1].count)[1].bindings)
            base.update({a: v for a, v in bind.items() if v[0] or a not in base})
            bind = base
        count = sum(1 for v in bind.values() if v[0])
        state = "read" if r.method == "exact" else "recognized"
        msg = f"{STATE_TEXT[state]} aus {_shown(f)} ({count} Tasten" + (", mit Standardbelegung" if defaults and in_user
                                                                          else "") + ")"
        if r.only_changes:
            msg += " – nur geänderte Tasten, die übrigen bitte im Editor eintragen"
        elif r.note and state == "recognized":
            msg += f" – {r.note}"
        return Found(state, bind, msg, str(f), r.method)
    for state, n in (("only_changes", only_changes), ("unreadable", unreadable), ("unknown", unknown)):
        if n:
            return Found(state, message=STATE_TEXT[state] + (f" ({n} Datei(en))" if state != "only_changes" else ""))
    return Found("none", message=STATE_TEXT["none"])


def find(name, install_dir=None, appid=None, learned=None):
    """Kurzform: (bindings oder None, Meldung, Datei)."""
    fd = search(name, install_dir, appid, learned)
    return (fd.bindings if fd.count else None), fd.message, fd.file


# ---------------------------------------------------------------- Lernmodus
def snapshot(name, install_dir=None, appid=None):
    """Zustand aller Dateien in den Benutzerordnern des Spiels: {Pfad: (Größe, Änderungszeit)}."""
    dirs, _ = locate.locations(name, install_dir, appid)
    snap = {}
    for d, user_dir in dirs:
        if not user_dir:
            continue
        for f in _files(d):
            try:
                st = f.stat()
                snap[str(f)] = (st.st_size, st.st_mtime_ns)
            except OSError:
                continue
    return snap


def changed(before, name, install_dir=None, appid=None):
    """Seit snapshot() geänderte oder neue Dateien, Steuerungs-Namen zuerst."""
    after = snapshot(name, install_dir, appid)
    diff = [p for p, v in after.items() if before.get(p) != v and v[0] <= MAX_FILE]
    return sorted(diff, key=lambda p: (STRONG.search(Path(p).name) is None, p))
