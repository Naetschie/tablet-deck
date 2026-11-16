"""Tastatur-Ausgabe per SendInput mit Scancodes (DirectInput/RawInput-tauglich)."""
import ctypes
from ctypes import wintypes

# Set-1-Scancodes. Wert: (scancode, extended)
SCANCODES = {
    "ESC": (0x01, False),
    **{str(i): (0x01 + i, False) for i in range(1, 10)}, "0": (0x0B, False),
    "MINUS": (0x0C, False), "EQUALS": (0x0D, False), "BACKSPACE": (0x0E, False),
    "TAB": (0x0F, False),
    "Q": (0x10, False), "W": (0x11, False), "E": (0x12, False), "R": (0x13, False),
    "T": (0x14, False), "Y": (0x15, False), "U": (0x16, False), "I": (0x17, False),
    "O": (0x18, False), "P": (0x19, False), "LBRACKET": (0x1A, False), "RBRACKET": (0x1B, False),
    "ENTER": (0x1C, False), "LCTRL": (0x1D, False),
    "A": (0x1E, False), "S": (0x1F, False), "D": (0x20, False), "F": (0x21, False),
    "G": (0x22, False), "H": (0x23, False), "J": (0x24, False), "K": (0x25, False),
    "L": (0x26, False), "SEMICOLON": (0x27, False), "APOSTROPHE": (0x28, False),
    "GRAVE": (0x29, False), "LSHIFT": (0x2A, False), "BACKSLASH": (0x2B, False),
    "Z": (0x2C, False), "X": (0x2D, False), "C": (0x2E, False), "V": (0x2F, False),
    "B": (0x30, False), "N": (0x31, False), "M": (0x32, False), "COMMA": (0x33, False),
    "PERIOD": (0x34, False), "SLASH": (0x35, False), "RSHIFT": (0x36, False),
    "NUMPADMULTIPLY": (0x37, False), "LALT": (0x38, False), "SPACE": (0x39, False),
    "CAPSLOCK": (0x3A, False),
    **{f"F{i}": (0x3A + i, False) for i in range(1, 11)},
    "F11": (0x57, False), "F12": (0x58, False),
    "SCROLLLOCK": (0x46, False),
    "NUMPAD7": (0x47, False), "NUMPAD8": (0x48, False), "NUMPAD9": (0x49, False),
    "NUMPADSUBTRACT": (0x4A, False),
    "NUMPAD4": (0x4B, False), "NUMPAD5": (0x4C, False), "NUMPAD6": (0x4D, False),
    "NUMPADADD": (0x4E, False),
    "NUMPAD1": (0x4F, False), "NUMPAD2": (0x50, False), "NUMPAD3": (0x51, False),
    "NUMPAD0": (0x52, False), "NUMPADDECIMAL": (0x53, False),
    # erweiterte Tasten
    "RCTRL": (0x1D, True), "RALT": (0x38, True), "NUMPADENTER": (0x1C, True),
    "NUMPADDIVIDE": (0x35, True), "HOME": (0x47, True), "UP": (0x48, True),
    "PGUP": (0x49, True), "LEFT": (0x4B, True), "RIGHT": (0x4D, True),
    "END": (0x4F, True), "DOWN": (0x50, True), "PGDN": (0x51, True),
    "INSERT": (0x52, True), "DELETE": (0x53, True),
}
ALIASES = {"CTRL": "LCTRL", "SHIFT": "LSHIFT", "ALT": "LALT", "RETURN": "ENTER",
           "NP_ENTER": "NUMPADENTER"}
for i in range(10):
    ALIASES[f"NP_{i}"] = f"NUMPAD{i}"
    ALIASES[f"KP_{i}"] = f"NUMPAD{i}"


def parse_combo(text):
    """'LALT+NUMPAD8' -> [(0x38,False),(0x48,False)]; wirft KeyError bei unbekannter Taste."""
    out = []
    for part in text.upper().replace(" ", "").split("+"):
        part = ALIASES.get(part, part)
        out.append(SCANCODES[part])
    return out


# --- SendInput -------------------------------------------------------------
ULONG_PTR = ctypes.c_size_t
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


_SendInput = ctypes.windll.user32.SendInput
_SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_SendInput.restype = wintypes.UINT


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    if _SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) != len(inputs):
        raise ctypes.WinError()


def send_scan(scan, extended, up):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0) | (KEYEVENTF_KEYUP if up else 0)
    _send(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, scan, flags, 0, 0)))


# --- Text (Unicode) und virtuelle Tasten -----------------------------------
KEYEVENTF_UNICODE = 0x0004


def type_text(text):
    """Tippt beliebigen Text (auch Umlaute/Emoji) unabhängig vom Tastaturlayout."""
    units = text.encode("utf-16-le")
    events = []
    for i in range(0, len(units), 2):
        cu = int.from_bytes(units[i:i + 2], "little")
        events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, cu, KEYEVENTF_UNICODE, 0, 0)))
        events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, cu, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)))
    if events:
        _send(*events)


# Medien- und Lautstärketasten (virtuelle Tastencodes)
MEDIA_VK = {"playpause": 0xB3, "next": 0xB0, "prev": 0xB1, "stop": 0xB2,
            "mute": 0xAD, "voldown": 0xAE, "volup": 0xAF}


def tap_vk(vk):
    _send(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, 0, 0, 0)),
          INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, 0)))


# --- Maus --------------------------------------------------------------------
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSE_BUTTON_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000


def mouse_move(dx, dy):
    _send(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(int(dx), int(dy), 0, MOUSEEVENTF_MOVE, 0, 0)))


def mouse_button(button, down):
    flag = MOUSE_BUTTON_FLAGS[button][0 if down else 1]
    _send(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, flag, 0, 0)))


def mouse_wheel(dy=0, dx=0):
    """dy > 0 = nach oben scrollen, dx > 0 = nach rechts; 120 = eine Raste."""
    ev = []
    if dy:
        ev.append(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, int(dy) & 0xFFFFFFFF, MOUSEEVENTF_WHEEL, 0, 0)))
    if dx:
        ev.append(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, int(dx) & 0xFFFFFFFF, MOUSEEVENTF_HWHEEL, 0, 0)))
    if ev:
        _send(*ev)
