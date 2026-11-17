"""Rückfall für Spiele ohne eigenen Belegungs-Adapter: Belegungsdateien in den Ordnern des Spiels suchen.

Gesucht wird in Dokumente (auch "My Games"), %LOCALAPPDATA%, %APPDATA% und im Installationsordner unter Namen,
die zum Spiel passen (Name, Ordnername). Lesbare Formate:
  - Enforce-Engine (DayZ): <preset><input name="UA…"><btn name="kW"/> … (Tasten als DirectInput-Namen)
  - Unreal Engine Input.ini: ActionMappings=(ActionName="Jump",…,Key=SpaceBar)
Finden sich nur unlesbare Einstellungsdateien (verschlüsselt/binär, z. B. AION 2), meldet find() das, statt zu raten.
Tastennamen werden fest zugeordnet; was nicht eindeutig ist (Maus, Controller, Doppelklick), bleibt ohne Taste.
"""
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..keys import ALIASES, SCANCODES

MAX_FILE = 2 * 1024 * 1024
MAX_FILES = 4000          # Obergrenze beim Durchsuchen eines Installationsordners
NAME_HINT = re.compile(r"(key|bind|input|control|preset|setting|profile)", re.I)

# DirectInput-Namen (DayZ "k…") -> Hub-Namen
DIK = {"LCONTROL": "LCTRL", "RCONTROL": "RCTRL", "LMENU": "LALT", "RMENU": "RALT", "LSHIFT": "LSHIFT",
       "RSHIFT": "RSHIFT", "RETURN": "ENTER", "ESCAPE": "ESC", "BACK": "BACKSPACE", "NEXT": "PGDN", "PRIOR": "PGUP",
       "CAPITAL": "CAPSLOCK", "SPACE": "SPACE", "TAB": "TAB", "ADD": "NUMPADADD", "SUBSTRACT": "NUMPADSUBTRACT",
       "SUBTRACT": "NUMPADSUBTRACT", "MULTIPLY": "NUMPADMULTIPLY", "DIVIDE": "NUMPADDIVIDE",
       "DECIMAL": "NUMPADDECIMAL", "NUMPADENTER": "NUMPADENTER", "GRAVE": "GRAVE", "APOSTROPHE": "APOSTROPHE",
       "SEMICOLON": "SEMICOLON", "COMMA": "COMMA", "PERIOD": "PERIOD", "SLASH": "SLASH", "BACKSLASH": "BACKSLASH",
       "MINUS": "MINUS", "EQUALS": "EQUALS", "LBRACKET": "LBRACKET", "RBRACKET": "RBRACKET", "UP": "UP",
       "DOWN": "DOWN", "LEFT": "LEFT", "RIGHT": "RIGHT", "HOME": "HOME", "END": "END", "INSERT": "INSERT",
       "DELETE": "DELETE", "SCROLL": "SCROLLLOCK"}
# Unreal-Tastennamen -> Hub-Namen
UNREAL = {"SPACEBAR": "SPACE", "LEFTSHIFT": "LSHIFT", "RIGHTSHIFT": "RSHIFT", "LEFTCONTROL": "LCTRL",
          "RIGHTCONTROL": "RCTRL", "LEFTALT": "LALT", "RIGHTALT": "RALT", "ESCAPE": "ESC", "ENTER": "ENTER",
          "BACKSPACE": "BACKSPACE", "TAB": "TAB", "CAPSLOCK": "CAPSLOCK", "PAGEUP": "PGUP", "PAGEDOWN": "PGDN",
          "HOME": "HOME", "END": "END", "INSERT": "INSERT", "DELETE": "DELETE", "UP": "UP", "DOWN": "DOWN",
          "LEFT": "LEFT", "RIGHT": "RIGHT", "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
          "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9", "TILDE": "GRAVE", "HYPHEN": "MINUS",
          "EQUALS": "EQUALS", "LEFTBRACKET": "LBRACKET", "RIGHTBRACKET": "RBRACKET", "SEMICOLON": "SEMICOLON",
          "APOSTROPHE": "APOSTROPHE", "COMMA": "COMMA", "PERIOD": "PERIOD", "SLASH": "SLASH", "BACKSLASH": "BACKSLASH",
          "ADD": "NUMPADADD", "SUBTRACT": "NUMPADSUBTRACT", "MULTIPLY": "NUMPADMULTIPLY", "DIVIDE": "NUMPADDIVIDE",
          "DECIMAL": "NUMPADDECIMAL"}
for _i, _n in enumerate(("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")):
    UNREAL["NUMPAD" + _n] = f"NUMPAD{_i}"
MODS = {"LCTRL", "RCTRL", "LALT", "RALT", "LSHIFT", "RSHIFT"}


def _known(k):
    return k if k in SCANCODES else ALIASES.get(k)


def dik_key(name):
    """'kLMenu' -> 'LALT', 'kF5' -> 'F5', 'kNumpad8' -> 'NUMPAD8'; None bei Maus/Controller/unbekannt."""
    if not name or not name.startswith("k") or len(name) < 2:
        return None
    n = name[1:].upper()
    if n in DIK:
        return DIK[n]
    if n.startswith("NUMPAD") and n[6:].isdigit():
        return "NUMPAD" + n[6:]
    return _known(n) if (len(n) == 1 or re.fullmatch(r"F\d{1,2}", n)) else None


def unreal_key(name):
    n = str(name or "").strip().strip('"').upper()
    if n in UNREAL:
        return UNREAL[n]
    return _known(n) if (len(n) == 1 or re.fullmatch(r"F\d{1,2}", n)) else None


def parse_enforce(path):
    """DayZ-Preset -> {aktion: (taste|None, hold, notiz)}; erste brauchbare Tastaturbelegung je Aktion."""
    out = {}
    for inp in ET.parse(path).getroot().iter("input"):
        act = inp.get("name")
        if not act:
            continue
        best = None
        for b in inp.findall("btn"):
            outer = dik_key(b.get("name"))
            if not outer:
                continue
            events = {e.get("name") for e in b.findall("event")}
            inner = [dik_key(x.get("name")) for x in b.findall("btn")]
            if "doubleclick" in events:
                best = best or (None, False, f"{outer} nur per Doppelklick")
                continue
            if inner:
                if len(inner) == 1 and inner[0] and outer in MODS and inner[0] not in MODS:
                    key = f"{outer}+{inner[0]}"
                else:
                    best = best or (None, False, "Kombination mit Maus/Controller")
                    continue
            else:
                key = outer
            best = (key, "hold" in events or "holdbegin" in events, "lange halten" if "hold" in events else "")
            break
        out[act] = best or (None, False, "keine Tastaturbelegung")
    return out


_UE_ACTION = re.compile(r"ActionMappings=\((.*)\)")


def parse_unreal_ini(path):
    """Unreal Input.ini -> {aktion: (taste, False, '')} aus ActionMappings (mit bShift/bCtrl/bAlt)."""
    out = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = _UE_ACTION.search(line)
        if not m:
            continue
        f = dict(re.findall(r'(\w+)=("[^"]*"|[^,]*)', m.group(1)))
        act, key = f.get("ActionName", "").strip('"'), unreal_key(f.get("Key"))
        if not act or (act in out and out[act][0]):
            continue   # erste Tastaturbelegung gilt; Maus-/Pad-Zeilen davor werden ersetzt
        if f.get("bCmd", "False").lower() == "true":
            out[act] = (None, False, "mit Cmd-Taste (Mac)")
            continue
        if not key:
            out[act] = (None, False, f"nur Maus/Controller ({f.get('Key', '')})")
            continue
        mods = [m for flag, m in (("bCtrl", "LCTRL"), ("bAlt", "LALT"), ("bShift", "LSHIFT"))
                if f.get(flag, "False").lower() == "true"]
        out[act] = ("+".join(mods + [key]), False, "")
    return out


def _is_text(data):
    if not data:
        return False
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):        # UTF-16 mit BOM
        return True
    if b"\x00" in data[:4096]:
        return False
    try:
        data[:4092].decode("utf-8")   # Ende kann ein abgeschnittenes Mehrbytezeichen sein
        return True
    except UnicodeDecodeError:
        return data[:4092].decode("utf-8", errors="replace").count("\ufffd") < 4


def _variants(name):
    n = str(name or "")
    out = {n, n.replace(" ", ""), n.replace(" ", "_"), n.replace(":", "")}
    return {v for v in out if len(v) >= 3}


def _documents():
    """Dokumente-Ordner (auch umgeleitet, z. B. OneDrive) über die Windows-API, sonst ~/Documents."""
    home = Path(os.path.expanduser("~"))
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:   # CSIDL_PERSONAL
            p = Path(buf.value)
            if p.is_dir() and str(home).lower() in str(p).lower():
                return p
    except Exception:  # noqa: BLE001 - kein Windows o. Ä.
        pass
    return home / "Documents"


def candidate_dirs(name, install_dir=None):
    """[(Ordner, ist_benutzerordner)] passend zum Spiel."""
    home = Path(os.path.expanduser("~"))
    docs = _documents()
    bases = [docs, docs / "My Games", home / "Documents", home / "Documents" / "My Games", home / "Saved Games",
             Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")),
             Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))]
    names = set(_variants(name))
    if install_dir:
        names |= _variants(Path(install_dir).name)
    out = []
    for b in bases:
        try:
            entries = {p.name.lower(): p for p in b.iterdir() if p.is_dir()}
        except OSError:
            continue
        for n in names:
            p = entries.get(n.lower())
            if p and p not in [x for x, _ in out]:
                out.append((p, True))
    if install_dir and Path(install_dir).is_dir():
        out.append((Path(install_dir), False))
    return out


def _is_link(p):
    try:
        return p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p))
    except OSError:
        return True


def _files(d):
    n = 0
    for root, dirs, files in os.walk(d):
        n += 1 + len(dirs)   # auch Ordner zählen (tiefe, leere Bäume)
        dirs[:] = [x for x in dirs if x.lower() not in ("logs", "crashes", "webcache", "shadercache", "cache")
                   and not x.lower().startswith("webcache") and not _is_link(Path(root) / x)]
        for f in files:
            n += 1
            if n > MAX_FILES:
                return
            yield Path(root) / f


def _shown(f):
    """Dateiname ohne vorangestellten Profilnamen ("Spieler.dayz_preset_User.xml" -> "…dayz_preset_User.xml")."""
    return re.sub(r"^[^.]+\.(?=[^.]+\.[^.]+$)", "…", f.name)


def find(name, install_dir=None):
    """Belegung suchen -> (bindings {aktion: (taste|None, hold, notiz)} oder None, Meldung, Quelldatei|None)."""
    unreadable, found = 0, []
    for d, user_dir in candidate_dirs(name, install_dir):
        for f in _files(d):
            low = f.name.lower()
            try:
                st = f.stat()
                if st.st_size > MAX_FILE:
                    continue
                if low.endswith(".xml") and "preset" in low:
                    head = f.read_bytes()[:4096]
                    if b"<preset" in head and b"<input" in head:
                        b = parse_enforce(f)
                        if any(v[0] for v in b.values()):
                            found.append((st.st_mtime, b, f))
                elif low == "input.ini":
                    b = parse_unreal_ini(f)
                    if any(v[0] for v in b.values()):
                        found.append((st.st_mtime, b, f))
                elif (user_dir and NAME_HINT.search(low)   # Installationsordner: zu viele Asset-Dateien
                      and low.endswith((".dat", ".sav", ".bin", ".cfg", ".ini", ".json", ".xml"))):
                    if not _is_text(f.read_bytes()[:4096]):
                        unreadable += 1
            except (OSError, ET.ParseError, ValueError):
                continue
    if found:
        _, b, f = max(found, key=lambda x: x[0])   # mehrere Profile: zuletzt geänderte Belegung
        more = f" (neueste von {len(found)})" if len(found) > 1 else ""
        return b, f"Belegung aus {_shown(f)}{more}", str(f)
    if unreadable:
        return None, (f"Einstellungsdateien gefunden, aber nicht lesbar (verschlüsselt/binär, {unreadable} Datei(en)) "
                      "– Tasten bleiben leer, bitte im Editor eintragen"), None
    return None, "keine lesbare Belegungsdatei gefunden – Tasten bleiben leer, bitte im Editor eintragen", None
