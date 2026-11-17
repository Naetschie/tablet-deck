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
HOLD_MODES = {"hold", "delayed_hold", "delayed_hold_long", "delayed_hold_no_retrigger", "hold_toggle",
              "hold_no_retrigger"}   # delayed_hold*: halten, aber erst nach der Schwelle (press_ms)
MULTI_MODES = {"double_tap", "double_tap_nonblocking"}
PRESS_MARGIN_MS = 100   # Reserve auf die Mindest-Haltezeit des Spiels (Bildrate, Eingabeabfrage)
PRESS_MAX_MS = 3000
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


def activation_thresholds(default_path):
    """{activationMode: pressTriggerThreshold in s} aus <ActivationModes> des Standardprofils (nur Werte > 0)."""
    out = {}
    for m in ET.parse(default_path).getroot().iter("ActivationMode"):
        try:
            t = float(m.get("pressTriggerThreshold", "-1"))
        except ValueError:
            continue
        if t > 0 and m.get("name"):
            out[m.get("name")] = t
    return out


def min_press_ms(mode, own_threshold, thresholds):
    """Mindest-Haltezeit in ms (0 = keine): eigener pressTriggerThreshold der Aktion vor dem der Aktivierungsart."""
    t = None
    try:
        t = float(own_threshold) if own_threshold not in (None, "") else None
    except ValueError:
        t = None
    if t is None:
        t = thresholds.get(mode, -1)
    if t <= 0:
        return 0
    return min(PRESS_MAX_MS, int(round(t * 1000)) + PRESS_MARGIN_MS)


def effective_bindings(default_path, user_path):
    """{aktion: (tastatur-belegung in SC-Notation oder '', activationMode, multiTap, pressTriggerThreshold|None)}"""
    eff = {}
    for a in ET.parse(default_path).getroot().iter("action"):
        eff[a.get("name")] = ((a.get("keyboard") or "").strip(), a.get("activationMode", ""),
                              a.get("multiTap", "1"), a.get("pressTriggerThreshold"))
    if user_path and Path(user_path).exists():
        for a in ET.parse(user_path).getroot().iter("action"):
            for rb in a.iter("rebind"):
                inp = rb.get("input", "")
                if inp.startswith("kb1_"):
                    old = eff.get(a.get("name"), ("", "", "1", None))
                    # "kb1_ " = bewusst entfernt; Rebind kann Modus/Mehrfachtipp/Schwelle überschreiben
                    mode = rb.get("activationMode", old[1])
                    eff[a.get("name")] = (inp[4:].strip(), mode, rb.get("multiTap", old[2]),
                                          rb.get("pressTriggerThreshold",
                                                 old[3] if mode == old[1] else None))
    return eff


def device_actions(default_path, user_path):
    """Aktionen, die auf einem Joystick/HOTAS oder Gamepad des Spielers liegen: eigene Belegung (js*/gp*-Rebind)
    oder Standardbelegung des Geräts, sofern nicht gelöscht ("js1_ "). Ein Gerät zählt, wenn actionmaps.xml es
    unter <devices> nennt oder Rebinds dafür hat (die Liste <options> nennt oft ein Gamepad, das es gar nicht
    gibt). Ohne actionmaps.xml leer (unbekannt)."""
    if not user_path or not Path(user_path).exists():
        return frozenset()
    root = ET.parse(user_path).getroot()
    kinds = {d.tag for devs in root.iter("devices") for d in devs}
    for rb in root.iter("rebind"):
        inp = rb.get("input", "")
        if inp.startswith("js"):
            kinds.add("joystick")
        elif inp.startswith("gp"):
            kinds.add("gamepad")
    prefixes = tuple(p for k, p in (("joystick", "js"), ("gamepad", "gp")) if k in kinds)
    if not prefixes:
        return frozenset()
    on, cleared = set(), set()
    for a in root.iter("action"):
        if not a.get("name"):
            continue
        for rb in a.iter("rebind"):
            inp = rb.get("input", "")
            if inp.startswith(prefixes):
                if inp.partition("_")[2].strip():
                    on.add(a.get("name"))
                else:
                    cleared.add((a.get("name"), inp[:2]))
    for a in ET.parse(default_path).getroot().iter("action"):
        for attr, pre in (("joystick", "js"), ("gamepad", "gp")):
            if pre in prefixes and (a.get(attr) or "").strip() and (a.get("name"), pre) not in cleared:
                on.add(a.get("name"))
    return frozenset(on)


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
    thresholds = activation_thresholds(default)
    out, used = {}, set()
    for act, (sc, mode, multi, own_t) in eff.items():
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
            out[act] = Binding(key, mode in HOLD_MODES, "", min_press_ms(mode, own_t, thresholds))
    src = f"{default.name}" + (f" + {Path(user).name}" if user and Path(user).exists() else "")
    try:
        on_device = device_actions(default, user)
    except Exception:  # noqa: BLE001 - Nebenfunktion (Filter): darf die echten Tasten nie kosten
        on_device = frozenset()
    return Result(out, [k for k in FREE_POOL if k not in used], src, on_device)
