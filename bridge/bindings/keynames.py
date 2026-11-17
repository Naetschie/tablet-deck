"""Universelles Tastenwörterbuch: Schreibweisen verschiedener Engines -> Tastennamen des Hubs (bridge/keys.py).

Feste Zuordnungen, nie geraten: was nicht eindeutig eine Tastaturtaste ist (Maus, Controller, unbekannt), ergibt None.
Schemata: DirectInput-Namen ("kLMenu", "DIK_W") und -Scancodes (17 = W), Unreal FKey ("SpaceBar"), Unity Input System
("<Keyboard>/space") und KeyCode ("Alpha1"), Source/idTech ("SHIFT", "KP_8"), Kurzformen ("Ctrl", "Esc").
"""
import re

from ..keys import ALIASES, SCANCODES

MODS = {"LCTRL", "RCTRL", "LALT", "RALT", "LSHIFT", "RSHIFT"}


def hub(name):
    """Name ist schon ein Hub-Tastenname (oder Alias)?"""
    n = str(name or "").strip().upper()
    if n in SCANCODES:
        return n
    return ALIASES.get(n)


def _letter_digit_f(n):
    n = n.upper()
    if len(n) == 1 and (n.isalpha() or n.isdigit()):
        return n
    if re.fullmatch(r"F([1-9]|1[0-2])", n):
        return n
    return None


# ---------------------------------------------------------------- gemeinsame Namen (alle Schreibweisen klein, ohne _ -)
COMMON = {
    "space": "SPACE", "spacebar": "SPACE", "tab": "TAB", "enter": "ENTER", "return": "ENTER", "escape": "ESC",
    "esc": "ESC", "backspace": "BACKSPACE", "back": "BACKSPACE", "capslock": "CAPSLOCK", "capital": "CAPSLOCK",
    "scrolllock": "SCROLLLOCK", "scroll": "SCROLLLOCK", "insert": "INSERT", "ins": "INSERT", "delete": "DELETE",
    "del": "DELETE", "home": "HOME", "end": "END", "pageup": "PGUP", "pgup": "PGUP", "prior": "PGUP",
    "pagedown": "PGDN", "pgdn": "PGDN", "next": "PGDN", "up": "UP", "uparrow": "UP", "down": "DOWN",
    "downarrow": "DOWN", "left": "LEFT", "leftarrow": "LEFT", "right": "RIGHT", "rightarrow": "RIGHT",
    "lshift": "LSHIFT", "leftshift": "LSHIFT", "shift": "LSHIFT", "rshift": "RSHIFT", "rightshift": "RSHIFT",
    "lctrl": "LCTRL", "leftctrl": "LCTRL", "lcontrol": "LCTRL", "leftcontrol": "LCTRL", "ctrl": "LCTRL",
    "control": "LCTRL", "rctrl": "RCTRL", "rightctrl": "RCTRL", "rcontrol": "RCTRL", "rightcontrol": "RCTRL",
    "lalt": "LALT", "leftalt": "LALT", "lmenu": "LALT", "alt": "LALT", "ralt": "RALT", "rightalt": "RALT",
    "rmenu": "RALT", "altgr": "RALT", "grave": "GRAVE", "backquote": "GRAVE", "tilde": "GRAVE", "minus": "MINUS",
    "hyphen": "MINUS", "equals": "EQUALS", "equal": "EQUALS", "leftbracket": "LBRACKET", "lbracket": "LBRACKET",
    "rightbracket": "RBRACKET", "rbracket": "RBRACKET", "semicolon": "SEMICOLON", "apostrophe": "APOSTROPHE",
    "quote": "APOSTROPHE", "comma": "COMMA", "period": "PERIOD", "slash": "SLASH", "backslash": "BACKSLASH",
    "numpadenter": "NUMPADENTER", "kpenter": "NUMPADENTER", "keypadenter": "NUMPADENTER",
    "add": "NUMPADADD", "numpadadd": "NUMPADADD", "numpadplus": "NUMPADADD", "keypadplus": "NUMPADADD",
    "kpplus": "NUMPADADD", "subtract": "NUMPADSUBTRACT", "substract": "NUMPADSUBTRACT",
    "numpadsubtract": "NUMPADSUBTRACT", "numpadminus": "NUMPADSUBTRACT", "keypadminus": "NUMPADSUBTRACT",
    "kpminus": "NUMPADSUBTRACT", "multiply": "NUMPADMULTIPLY", "numpadmultiply": "NUMPADMULTIPLY",
    "keypadmultiply": "NUMPADMULTIPLY", "kpmultiply": "NUMPADMULTIPLY", "divide": "NUMPADDIVIDE",
    "numpaddivide": "NUMPADDIVIDE", "keypaddivide": "NUMPADDIVIDE", "kpslash": "NUMPADDIVIDE",
    "decimal": "NUMPADDECIMAL", "numpaddecimal": "NUMPADDECIMAL", "numpadperiod": "NUMPADDECIMAL",
    "keypadperiod": "NUMPADDECIMAL", "kpdel": "NUMPADDECIMAL",
}
_WORD_DIGITS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
for _i, _w in enumerate(_WORD_DIGITS):
    COMMON[_w] = str(_i)                       # Unreal: One
    COMMON["numpad" + _w] = f"NUMPAD{_i}"      # Unreal: NumPadOne
    COMMON[f"alpha{_i}"] = str(_i)             # Unity KeyCode: Alpha1
    COMMON[f"digit{_i}"] = str(_i)             # Unity Input System: <Keyboard>/digit1
    COMMON[f"numpad{_i}"] = f"NUMPAD{_i}"
    COMMON[f"keypad{_i}"] = f"NUMPAD{_i}"      # Unity KeyCode: Keypad1
    COMMON[f"kp{_i}"] = f"NUMPAD{_i}"          # Source: KP_1 ... (nur Ziffernform)
    COMMON[f"np{_i}"] = f"NUMPAD{_i}"


def common(name):
    """Name in gängiger Schreibweise -> Hub-Taste (Groß/klein, _ und - egal)."""
    raw = str(name or "").strip()
    if not raw:
        return None
    k = re.sub(r"[\s_\-]", "", raw).lower()
    if k in COMMON:
        return COMMON[k]
    return _letter_digit_f(k) or hub(raw)


# ---------------------------------------------------------------- DirectInput
def dik_name(name):
    """'kLMenu' / 'DIK_LMENU' -> 'LALT'."""
    n = str(name or "")
    if n.upper().startswith("DIK_"):
        n = n[4:]
    elif len(n) >= 2 and n[0] == "k" and (n[1].isupper() or n[1].isdigit()):
        n = n[1:]
    else:
        return None
    if n.upper().startswith("NUMPAD") and n[6:].isdigit():
        return "NUMPAD" + n[6:]
    return common(n)


# DirectInput-Scancodes (Satz 1, wie DIK_*; z. B. Project Zomboid "key:17")
DIK_CODES = {1: "ESC", 12: "MINUS", 13: "EQUALS", 14: "BACKSPACE", 15: "TAB", 26: "LBRACKET", 27: "RBRACKET",
             28: "ENTER", 29: "LCTRL", 39: "SEMICOLON", 40: "APOSTROPHE", 41: "GRAVE", 42: "LSHIFT",
             43: "BACKSLASH", 51: "COMMA", 52: "PERIOD", 53: "SLASH", 54: "RSHIFT", 55: "NUMPADMULTIPLY",
             56: "LALT", 57: "SPACE", 58: "CAPSLOCK", 70: "SCROLLLOCK", 71: "NUMPAD7", 72: "NUMPAD8",
             73: "NUMPAD9", 74: "NUMPADSUBTRACT", 75: "NUMPAD4", 76: "NUMPAD5", 77: "NUMPAD6", 78: "NUMPADADD",
             79: "NUMPAD1", 80: "NUMPAD2", 81: "NUMPAD3", 82: "NUMPAD0", 83: "NUMPADDECIMAL", 87: "F11",
             88: "F12", 156: "NUMPADENTER", 157: "RCTRL", 181: "NUMPADDIVIDE", 184: "RALT", 199: "HOME",
             200: "UP", 201: "PGUP", 203: "LEFT", 205: "RIGHT", 207: "END", 208: "DOWN", 209: "PGDN",
             210: "INSERT", 211: "DELETE"}
for _c, _k in zip(range(2, 12), "1234567890"):
    DIK_CODES[_c] = _k
for _c, _k in zip(range(16, 26), "QWERTYUIOP"):
    DIK_CODES[_c] = _k
for _c, _k in zip(range(30, 39), "ASDFGHJKL"):
    DIK_CODES[_c] = _k
for _c, _k in zip(range(44, 51), "ZXCVBNM"):
    DIK_CODES[_c] = _k
for _c in range(59, 69):
    DIK_CODES[_c] = f"F{_c - 58}"


def dik_code(code):
    try:
        return DIK_CODES.get(int(code))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- Unity Input System
def unity_path(path):
    """'<Keyboard>/space', '/Keyboard/leftShift' -> Hub-Taste; Maus/Gamepad -> None."""
    m = re.fullmatch(r"\s*</?keyboard>?/(.+)", str(path or ""), re.I) or re.fullmatch(r"\s*/keyboard/(.+)", str(path or ""), re.I)
    if not m:
        return None
    return common(m.group(1))


# ---------------------------------------------------------------- Kombinationen
def combo(tokens, one):
    """Mehrere Teile (Zusatztasten + Taste) -> 'LCTRL+S'; one: Funktion für einen Teil. None, wenn ein Teil
    unbekannt ist oder es nicht genau eine Nicht-Zusatztaste gibt."""
    keys = [one(t) for t in tokens if str(t).strip()]
    if not keys or any(k is None for k in keys):
        return None
    mods = [k for k in keys if k in MODS]
    rest = [k for k in keys if k not in MODS]
    if len(rest) != 1 and not (len(rest) == 0 and len(mods) == 1):
        return None
    order = ["LCTRL", "RCTRL", "LSHIFT", "RSHIFT", "LALT", "RALT"]
    mods = sorted(set(mods) - set(rest), key=order.index)
    return "+".join(mods + rest) if rest else mods[0]


def text_key(value):
    """Freitext einer Belegung ('Ctrl+S', 'LeftShift', '<Keyboard>/e', 'kW') -> Hub-Taste oder None."""
    v = str(value or "").strip().strip('"').strip("'")
    if not v or len(v) > 40:
        return None
    if "<" in v or v.lower().startswith("/keyboard/"):
        return unity_path(v)
    if re.fullmatch(r"(k[A-Z0-9]\w*|DIK_\w+)", v):
        return dik_name(v)
    parts = re.split(r"\s*\+\s*", v) if "+" in v and len(v) > 1 else [v]
    return combo(parts, common)
