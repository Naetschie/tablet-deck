"""Star Citizen (CryEngine/StarEngine): tatsächliche Tastaturbelegung lesen.

Quelle: Standardprofil des Spiels (defaultProfile.plain.xml, mit StarBreaker aus Data.p4k entpackt) plus die
eigenen Änderungen aus actionmaps.xml. Ergebnis: {aktion: Binding}, siehe bindings.Binding.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

from ..keys import ALIASES, SCANCODES

SC_TOKENS = {
    "lalt": "LALT", "ralt": "RALT", "lctrl": "LCTRL", "rctrl": "RCTRL", "lshift": "LSHIFT", "rshift": "RSHIFT",
    "tab": "TAB", "space": "SPACE", "enter": "ENTER", "escape": "ESC", "backspace": "BACKSPACE",
    "minus": "MINUS", "equals": "EQUALS", "lbracket": "LBRACKET", "rbracket": "RBRACKET",
    "semicolon": "SEMICOLON", "apostrophe": "APOSTROPHE", "comma": "COMMA", "period": "PERIOD",
    "slash": "SLASH", "backslash": "BACKSLASH", "grave": "GRAVE", "up": "UP", "down": "DOWN",
    "left": "LEFT", "right": "RIGHT", "pgup": "PGUP", "pgdn": "PGDN", "home": "HOME", "end": "END",
    "insert": "INSERT", "delete": "DELETE", "capslock": "CAPSLOCK", "scrolllock": "SCROLLLOCK",
    "np_period": "NUMPADDECIMAL", "np_add": "NUMPADADD", "np_subtract": "NUMPADSUBTRACT",
    "np_multiply": "NUMPADMULTIPLY", "np_divide": "NUMPADDIVIDE", "np_enter": "NUMPADENTER",
}
MODIFIERS = ["LCTRL", "RCTRL", "LSHIFT", "RSHIFT", "LALT", "RALT"]
# smart_toggle: Tippen schaltet um (Impuls), Halten wirkt nur solange - deshalb NICHT als hold
HOLD_MODES = {"hold", "delayed_hold", "hold_toggle", "hold_no_retrigger"}
MULTI_MODES = {"double_tap", "double_tap_nonblocking"}
# Vorschläge für Aktionen ohne Tastaturbelegung (rechte Strg + Ziffernblock/F-Tasten: im Spiel kaum belegt).
# 2. Stufe nur F-Tasten: Shift + Ziffernblock lässt Windows (NumLock) Shift kurz loslassen
_POOL_KEYS = ["NUMPAD1", "NUMPAD2", "NUMPAD3", "NUMPAD4", "NUMPAD5", "NUMPAD6", "NUMPAD7", "NUMPAD8",
              "NUMPAD9", "NUMPAD0", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"]
FREE_POOL = [f"RCTRL+{k}" for k in _POOL_KEYS] + [f"RCTRL+RSHIFT+{k}" for k in _POOL_KEYS if k.startswith("F")]


def sc_to_key(sc):
    """'lalt+np_5' -> 'LALT+NUMPAD5'; None bei Maus/Achse/unbekannt."""
    parts = []
    for tok in sc.strip().lower().split("+"):
        if tok in SC_TOKENS:
            parts.append(SC_TOKENS[tok])
        elif tok.startswith("np_") and tok[3:].isdigit():
            parts.append("NUMPAD" + tok[3:])
        elif len(tok) == 1 and tok.isalnum():
            parts.append(tok.upper())
        elif tok[:1] == "f" and tok[1:].isdigit():
            parts.append(tok.upper())
        else:
            return None
    mods = [m for m in MODIFIERS if m in parts]
    rest = [p for p in parts if p not in MODIFIERS]
    if len(rest) != 1 or any(p not in SCANCODES and p not in ALIASES for p in parts):
        return None
    return "+".join(mods + rest)


def key_to_sc(key):
    rev = {v: k for k, v in SC_TOKENS.items()}
    out = []
    for p in key.split("+"):
        if p in rev:
            out.append(rev[p])
        elif p.startswith("NUMPAD") and p[6:].isdigit():
            out.append("np_" + p[6:])
        else:
            out.append(p.lower())
    return "+".join(out)


def effective_bindings(default_path, user_path):
    """{aktion: (tastatur-belegung in SC-Notation oder '', activationMode, multiTap)}"""
    eff = {}
    for a in ET.parse(default_path).getroot().iter("action"):
        eff[a.get("name")] = ((a.get("keyboard") or "").strip(), a.get("activationMode", ""),
                              a.get("multiTap", "1"))
    if user_path and Path(user_path).exists():
        for a in ET.parse(user_path).getroot().iter("action"):
            for rb in a.iter("rebind"):
                inp = rb.get("input", "")
                if inp.startswith("kb1_"):
                    old = eff.get(a.get("name"), ("", "", "1"))
                    # "kb1_ " = bewusst entfernt; Rebind kann Modus/Mehrfachtipp überschreiben
                    eff[a.get("name")] = (inp[4:].strip(), rb.get("activationMode", old[1]),
                                          rb.get("multiTap", old[2]))
    return eff


ACTIONMAPS = Path("LIVE/user/client/0/Profiles/default/actionmaps.xml")


def find_user_actionmaps(entries=None):
    """actionmaps.xml des Spielers über die Spielebibliothek finden (statt festem Pfad in games.json).

    entries: Bibliothekseinträge (library.scan_library), Standard: frisch scannen. Gesucht wird ab Spielordner
    und exe-Ordnern aufwärts nach <Ordner>/LIVE/user/client/0/Profiles/default/actionmaps.xml. None, wenn nichts passt."""
    if entries is None:
        try:
            from .. import library
            entries = library.scan_library()
        except Exception:  # noqa: BLE001 - ohne Bibliothek einfach keine eigenen Änderungen
            return None
    for g in entries:
        names = [g.get("name", ""), g.get("exe", "")] + list(g.get("exes", []))
        if not any("star citizen" in str(n).lower() or "starcitizen" in str(n).lower() for n in names):
            continue
        starts = [g.get("dir")] + [Path(e).parent for e in names[1:] if e]
        for st in starts:
            if not st:
                continue
            d = Path(st)
            for _ in range(6):
                cand = d / ACTIONMAPS
                if cand.is_file():
                    return str(cand)
                if d.parent == d:
                    break
                d = d.parent
    return None


def resolve_cfg(cfg, root, entries=None):
    """Pfade der Belegungsquellen ohne Scan der Bibliothek: (cfg mit gefundenem "user", [Standardprofil, actionmaps]).
    entries: bereits bekannte Bibliothekseinträge (leer = keine eigene actionmaps.xml gefunden)."""
    default = Path(cfg.get("default", ""))
    if not default.is_absolute():
        default = Path(root) / default
    user = cfg.get("user") or find_user_actionmaps(entries or [])
    return (dict(cfg, user=user) if user else dict(cfg)), [str(default), str(user) if user else ""]


def read(cfg, root):
    """cfg: {"default": Pfad zum Standardprofil (relativ zum Projekt), "user": Pfad zu actionmaps.xml
    (optional; fehlt er, wird er über die Spielebibliothek gesucht)}"""
    from . import Binding, Result
    default = Path(cfg.get("default", ""))
    if not default.is_absolute():
        default = Path(root) / default
    if not default.is_file():
        raise FileNotFoundError(f"Standardprofil fehlt: {default} (StarBreaker: p4k extract + cryxml convert)")
    user = cfg["user"] if "user" in cfg else find_user_actionmaps()   # "" = bewusst keine eigene Belegung
    eff = effective_bindings(default, user)
    out, used = {}, set()
    for act, (sc, mode, multi) in eff.items():
        key = sc_to_key(sc) if sc else None
        if key:
            used.add(key)
        if not sc:
            out[act] = Binding(None, False, "keine Tastaturbelegung")
        elif not key:
            out[act] = Binding(None, False, f"nur Maus/Achse ({sc})")
        elif multi not in ("", "1") or mode in MULTI_MODES:
            out[act] = Binding(None, False, f"{key} nur per Doppeltipp")
        else:
            out[act] = Binding(key, mode in HOLD_MODES, "")
    src = f"{default.name}" + (f" + {Path(user).name}" if user and Path(user).exists() else "")
    return Result(out, [k for k in FREE_POOL if k not in used], src)
