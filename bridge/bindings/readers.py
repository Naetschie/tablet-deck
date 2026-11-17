"""Leser für Belegungsdateien. Jeder liefert {aktion: (taste|None, halten, notiz)} oder None (passt nicht).

Genaue Leser (Format bekannt): Enforce/DayZ-Preset, Unreal Input.ini, Unreal Enhanced-Input-Spielstand (GVAS),
Scancode-INI (Project Zomboid "key:17"), Source/idTech-"bind", Unity Input System (JSON der geänderten Tasten).
Allgemeiner Leser (Format unbekannt, Ergebnis „erkannt – bitte prüfen“): XML/JSON/INI-Strukturen mit
Aktionsname + eindeutig bekanntem Tastennamen. Zuordnung der Tastennamen: keynames.py, nie geraten.
"""
import json
import re
import struct
import xml.etree.ElementTree as ET

from . import keynames as kn

MIN_GENERIC = 5   # so viele Paare braucht der allgemeine Leser, sonst ist es wohl keine Belegungsdatei


class Read:
    """Ergebnis eines Lesers."""
    def __init__(self, bindings, method, only_changes=False, note=""):
        self.bindings, self.method, self.only_changes, self.note = bindings, method, only_changes, note

    @property
    def count(self):
        return sum(1 for v in self.bindings.values() if v[0])


# ---------------------------------------------------------------- genaue Leser
def read_enforce(text):
    """DayZ/Enforce: <preset><input name="UA…"><btn name="kW"/> (verschachtelt = Zusatztaste + Taste)."""
    if "<preset" not in text[:4096] or "<input" not in text:
        return None
    out = {}
    for inp in ET.fromstring(text).iter("input"):
        act = inp.get("name")
        if not act:
            continue
        best = None
        for b in inp.findall("btn"):
            outer = kn.dik_name(b.get("name"))
            if not outer:
                continue
            events = {e.get("name") for e in b.findall("event")}
            inner = [kn.dik_name(x.get("name")) for x in b.findall("btn")]
            if "doubleclick" in events:
                best = best or (None, False, f"{outer} nur per Doppelklick")
                continue
            if inner:
                if len(inner) == 1 and inner[0] and outer in kn.MODS and inner[0] not in kn.MODS:
                    key = f"{outer}+{inner[0]}"
                else:
                    best = best or (None, False, "Kombination mit Maus/Controller")
                    continue
            else:
                key = outer
            best = (key, "hold" in events or "holdbegin" in events, "lange halten" if "hold" in events else "")
            break
        out[act] = best or (None, False, "keine Tastaturbelegung")
    return Read(out, "exact")


_UE_ACTION = re.compile(r"ActionMappings=\((.*)\)")


def read_unreal_ini(text):
    """Unreal Input.ini: ActionMappings=(ActionName="Jump",bShift=…,Key=SpaceBar)."""
    if "ActionMappings=" not in text:
        return None
    out = {}
    for line in text.splitlines():
        m = _UE_ACTION.search(line)
        if not m:
            continue
        f = dict(re.findall(r'(\w+)=("[^"]*"|[^,]*)', m.group(1)))
        act, key = f.get("ActionName", "").strip('"'), kn.common(f.get("Key", "").strip('"'))
        if not act or (act in out and out[act][0]):
            continue   # erste Tastaturbelegung gilt; Maus-/Pad-Zeilen davor werden ersetzt
        if f.get("bCmd", "False").lower() == "true":
            out[act] = (None, False, "mit Cmd-Taste (Mac)")
            continue
        if not key or f.get("Key", "").lower().startswith(("left mouse", "mouse", "gamepad")):
            out[act] = (None, False, f"nur Maus/Controller ({f.get('Key', '')})")
            continue
        mods = [m for flag, m in (("bCtrl", "LCTRL"), ("bShift", "LSHIFT"), ("bAlt", "LALT"))
                if f.get(flag, "False").lower() == "true"]
        out[act] = ("+".join(mods + [key]), False, "")
    return Read(out, "exact") if out else None


def gvas_strings(data):
    """Alle FStrings (int32-Länge + ASCII mit Null) eines Unreal-Spielstands, in Reihenfolge."""
    out, i, n = [], 0, len(data)
    while i < n - 4:
        ln = struct.unpack_from("<i", data, i)[0]
        if 2 <= ln <= 200 and i + 4 + ln <= n and data[i + 4 + ln - 1] == 0:
            s = data[i + 4:i + 4 + ln - 1]
            if all(32 <= c < 127 for c in s):
                out.append(s.decode())
                i += 4 + ln
                continue
        i += 1
    return out


_GVAS_TYPES = {"NameProperty", "StructProperty", "StrProperty", "None", "Key", "TextProperty", "MapProperty",
               "ArrayProperty", "IntProperty", "BoolProperty", "EnumProperty", "ObjectProperty"}


def read_gvas_input(data):
    """Unreal Enhanced Input (EnhancedInputUserSettings.sav u. ä.): geänderte Tasten aus dem Spielstand.
    Gespeichert werden nur Abweichungen vom Standard; ohne Änderungen: only_changes ohne Tasten."""
    strs = gvas_strings(data)
    joined = " ".join(strs[:60])
    if "EnhancedInput" not in joined and "KeyBinding" not in joined and "KeyMapping" not in joined:
        return None
    out, action = {}, None
    for i, s in enumerate(strs):
        if s in ("MappingName", "ActionName", "SlotName") and i + 2 < len(strs):
            vals = [x for x in strs[i + 1:i + 4] if x not in _GVAS_TYPES and not x.startswith("/Script/")]
            action = vals[0] if vals else None
        elif s in ("KeyName", "CurrentKey") and action and i + 2 < len(strs):
            vals = [x for x in strs[i + 1:i + 4] if x not in _GVAS_TYPES and not x.startswith("/Script/")]
            key = kn.common(vals[0]) if vals else None
            if action not in out or (key and not out[action][0]):
                out[action] = (key, False, "" if key else f"nur Maus/Controller ({vals[0] if vals else '?'})")
    return Read(out, "generic", only_changes=True,
                note="Unreal-Spielstand: nur geänderte Tasten gespeichert")


_SCAN_LINE = re.compile(r"^\s*([^=#;\[]+?)\s*=\s*key:(\d+)", re.I)


def read_scancode_ini(text):
    """INI mit DirectInput-Scancodes: 'Forward=key:17' (Project Zomboid)."""
    hits = [_SCAN_LINE.match(line) for line in text.splitlines()]
    hits = [h for h in hits if h]
    if len(hits) < MIN_GENERIC:
        return None
    out = {}
    for h in hits:
        act, code = h.group(1).strip(), int(h.group(2))
        if act in out:
            continue
        key = kn.dik_code(code)
        out[act] = (key, False, "" if key else ("Maus" if code >= 10000 else "nicht belegt" if code == 0
                                                else f"Scancode {code} unbekannt"))
    return Read(out, "exact")


_BIND = re.compile(r'^\s*bind\s+"?([^"\s]+)"?\s+"([^"]+)"', re.I)


def read_source_binds(text):
    """Source/idTech-Konfiguration: bind "KEY" "befehl"."""
    hits = [_BIND.match(line) for line in text.splitlines()]
    hits = [h for h in hits if h]
    if len(hits) < MIN_GENERIC:
        return None
    out = {}
    for h in hits:
        cmd, key = h.group(2).strip(), kn.common(h.group(1))
        if cmd not in out or (key and not out[cmd][0]):
            out[cmd] = (key, False, "" if key else f"nur Maus/Controller ({h.group(1)})")
    return Read(out, "exact")


def read_unity_json(text):
    """Unity Input System, SaveBindingOverridesAsJson: {"bindings": [{"action": "Map/Jump", "path": "<Keyboard>/space"}]}"""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not (isinstance(data, dict) and isinstance(data.get("bindings"), list)):
        return None
    out = {}
    for b in data["bindings"]:
        if not isinstance(b, dict) or not b.get("action"):
            continue
        key = kn.unity_path(b.get("path") or b.get("overridePath") or "")
        act = str(b["action"])
        if act not in out or (key and not out[act][0]):
            out[act] = (key, False, "" if key else "nur Maus/Controller")
    return Read(out, "exact", only_changes=True, note="Unity: nur geänderte Tasten gespeichert") if out else None


# ---------------------------------------------------------------- allgemeiner Leser
ACTION_FIELDS = ("action", "actionname", "name", "id", "command", "cmd", "function", "func", "concept", "binding")
# Feldnamen, die sicher eine Taste meinen (nicht „value“, „code“, „input“: dort stehen meist andere Werte)
KEY_FIELDS = ("key", "keys", "keyboard", "btn", "button", "primary", "keycode", "shortcut", "hotkey", "bind",
              "path", "secondary")
MIN_SHARE = 0.7   # allgemeiner Leser: so viel der Einträge müssen Tasten sein (sonst ist es eine Einstellungsdatei)


def _unambiguous(value):
    """Wert ist eindeutig eine Taste, auch ohne Feldnamen: Kombination, F-Taste, Ziffernblock, Zusatztaste,
    DirectInput-/Unity-Schreibweise. Einzelbuchstaben und Wörter wie „Left“, „Add“, „Back“ sind es nicht."""
    v = str(value).strip()
    k = kn.text_key(v)
    if not k:
        return None
    if "+" in v or "<" in v or v.startswith(("DIK_", "/")) or re.fullmatch(r"k[A-Z0-9]\w*", v):
        return k
    if re.fullmatch(r"F([1-9]|1[0-2])", k) or k.startswith("NUMPAD") or k in kn.MODS or k in ("SPACE", "ESC",
                                                                                               "ENTER", "TAB"):
        return k if len(v) > 1 else None
    return None
MOD_FIELDS = ("modifier", "modifiers", "mod", "mods")
KEY_TAGS = ("key", "btn", "button", "binding", "input", "shortcut", "hotkey", "keyboard")


def _key_with_mods(value, mods):
    # nur aus Feldern, die ausdrücklich eine Taste meinen (KEY_FIELDS/KEY_TAGS) - dort sind Ziffern echte Tasten
    k = kn.text_key(value)
    if not k:
        return None
    if mods:
        return kn.combo(re.split(r"[\s+,|]+", mods.strip()) + [k], kn.common)
    return k


def _generic_xml(text):
    root = ET.fromstring(text)
    out = {}
    for el in root.iter():
        attrs = {k.lower(): v for k, v in el.attrib.items()}
        act = next((attrs[f] for f in ACTION_FIELDS if attrs.get(f)), None)
        if not act:
            continue
        cands = [el] + [c for c in el if c.tag.lower() in KEY_TAGS]
        for c in cands:
            ca = {k.lower(): v for k, v in c.attrib.items()}
            mods = next((ca[f] for f in MOD_FIELDS if ca.get(f)), "")
            vals = [ca[f] for f in KEY_FIELDS if ca.get(f) and not (c is el and f in ACTION_FIELDS)]
            if c is not el and (c.text or "").strip():
                vals.insert(0, c.text.strip())
            key = next((k for k in (_key_with_mods(v, mods) for v in vals) if k), None)
            if key:
                out.setdefault(act, (key, False, ""))
                break
    return out


def _generic_json(text):
    data = json.loads(text)
    out = {}

    def walk(o, depth=0):
        if depth > 12:
            return
        if isinstance(o, dict):
            low = {str(k).lower(): v for k, v in o.items()}
            act = next((low[f] for f in ACTION_FIELDS if isinstance(low.get(f), str) and low[f]), None)
            if act:
                mods = next((low[f] for f in MOD_FIELDS if isinstance(low.get(f), str)), "")
                for f in KEY_FIELDS:
                    v = low.get(f)
                    if isinstance(v, str) and f not in ACTION_FIELDS:
                        k = _key_with_mods(v, mods)
                        if k:
                            out.setdefault(act, (k, False, ""))
                            break
            else:
                # {"Jump": "Ctrl+J", …} - Aktionsname als Schlüssel: nur eindeutige Tasten
                for k, v in o.items():
                    if isinstance(v, str) and len(str(k)) > 2 and not str(k).lower() in KEY_FIELDS:
                        kk = _unambiguous(v)
                        if kk:
                            out.setdefault(str(k), (kk, False, ""))
            for v in o.values():
                walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, depth + 1)
    walk(data)
    return out


_INI = re.compile(r"^\s*([A-Za-z][\w .\-/]{1,60}?)\s*[=:]\s*\"?([^\";#]{1,40}?)\"?\s*$")


def _generic_ini(text):
    """Zeilen „Aktion = Taste“. Mehrdeutige Werte (A, Left, Add) nur, wenn die Datei überwiegend aus Tasten besteht."""
    out, plain, entries = {}, {}, 0
    for line in text.splitlines():
        m = _INI.match(line)
        if not m:
            continue
        entries += 1
        act, val = m.group(1).strip(), m.group(2).strip()
        if val.isdigit() or act.lower() in KEY_FIELDS:
            continue   # Zahlen sind in INIs meist Werte, keine Tasten
        k = _unambiguous(val)
        if k:
            out.setdefault(act, (k, False, ""))
            continue
        k = kn.text_key(val)
        if k and not k.isdigit():
            plain.setdefault(act, (k, False, ""))
    # mehrdeutige Werte nur, wenn die Datei überwiegend Tasten enthält und mindestens zwei eindeutige
    if entries and len(out) >= 2 and (len(out) + len(plain)) / entries >= MIN_SHARE:
        for a, v in plain.items():
            out.setdefault(a, v)
    return out


def read_generic(text):
    """Unbekanntes Format: Paare aus Aktionsname + bekanntem Tastennamen. Ergebnis immer „bitte prüfen“."""
    s = text.lstrip()
    out = None
    try:
        if s.startswith("<"):
            out = _generic_xml(text)
        elif s.startswith(("{", "[")):
            try:
                out = _generic_json(text)
            except ValueError:
                out = None   # „[Abschnitt]“ einer INI ist kein JSON
        if out is None:
            out = _generic_ini(text)
    except (ET.ParseError, ValueError, RecursionError):
        return None
    if sum(1 for v in out.values() if v[0]) < MIN_GENERIC:
        return None
    return Read(out, "generic", note="Format nicht genau bekannt – Tasten bitte prüfen")


EXACT_TEXT = (read_enforce, read_unreal_ini, read_scancode_ini, read_source_binds, read_unity_json)


def read_content(kind, content):
    """Inhalt (aus containers.open_bytes) mit allen Lesern versuchen; genaue zuerst."""
    if kind == "gvas":
        return read_gvas_input(content)
    if kind != "text":
        return None
    for r in EXACT_TEXT:
        try:
            res = r(content)
        except (ET.ParseError, ValueError, RecursionError):
            res = None
        if res and (res.count or res.only_changes):
            return res
    return read_generic(content)
