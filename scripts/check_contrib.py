"""Prüft beigetragene Panels, Dashboards und games.json (läuft auch automatisch bei jedem Pull Request).

Aufruf: python scripts/check_contrib.py            (panels/, profiles/, dashboards/, games.json)
        python scripts/check_contrib.py DATEI ...  (nur diese)
Exit 0 = alles in Ordnung, 1 = Fehler (je Datei gemeldet).

Neben der normalen Prüfung (bridge/layout.py, bridge/dashboard.py, bridge/profiles.py) gelten für eingecheckte
Panels strengere Regeln - ein Panel aus fremder Hand darf am PC nichts tun, was über Tastendrücke in einem
Spiel hinausgeht. Die Windows-Taste kennt das Panel ohnehin nicht (bridge/keys.py).
- kein "open" (Programme, Pfade oder Webseiten am PC öffnen): das trägt jeder nur für sich selbst ein
- keine Systemkürzel: Esc mit Zusatztaste (Startmenü, Task-Manager), Alt+F4, Alt+Tab, Alt+Leertaste
- Tasten, die nur Zusatztasten halten oder umschalten (hold/toggle mit z. B. nur LSHIFT zum Sprinten), sind
  erlaubt, werden aber als Hinweis für die Handprüfung gemeldet: mit einer zweiten Taste ergäben sie ein
  Systemkürzel
- Makros dürfen nichts "tippen": höchstens 12 Schritte, ein "text"-Schritt, zwei einzelne Zeichentasten (auch
  mit Shift) und zwei Enter - sonst ließe sich z. B. ein Befehl Buchstabe für Buchstabe eingeben
- "text" höchstens 60 Zeichen, nur Buchstaben, Ziffern, Leerzeichen und harmlose Satzzeichen, ohne typische
  Befehlsnamen (cmd, powershell, curl, …) - Chat-Grüße wie "o7" gehen, Befehle nicht
Das ist eine Hürde, keine Garantie: Jeder Beitrag wird zusätzlich von Hand geprüft (CONTRIBUTING.md).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bridge import dashboard, keys, layout, profiles  # noqa: E402

MAX_TEXT = 60
MAX_STEPS = 12
MAX_TYPING_KEYS = 2       # einzelne Zeichentasten ohne Zusatztaste je Makro
MAX_ENTER = 2
# Positivliste: Buchstaben, Ziffern, Leerzeichen und harmlose Satzzeichen - alles andere ist verboten
OK_TEXT = re.compile(r"[A-Za-z0-9ÄÖÜäöüß .,!?:;+\-#*=()]+")
# typische Befehle/Programme: auch ohne Sonderzeichen gefährlich, wenn eine Kommandozeile den Fokus hat
BAD_WORDS = re.compile(r"(?i)(cmd|powershell|pwsh|iex|irm|iwr|invoke|curl|wget|bitsadmin|certutil|mshta|"
                       r"rundll32|regsvr32|wscript|cscript|msiexec|schtasks|taskkill|shutdown|notepad|explorer|"
                       r"wmic|mstsc|attrib|robocopy|xcopy|"
                       r"\b(?:reg|start|del|erase|rmdir|rd|format|net|sc|bash|sh|python|py|node|run|ping|copy|move|"
                       r"ren|calc|ftp|tftp|ssh)\b)")
MODIFIERS = {"LCTRL", "RCTRL", "LALT", "RALT", "LSHIFT", "RSHIFT"}
SHIFT = {"LSHIFT", "RSHIFT"}
ALT = {"LALT", "RALT"}
ENTER = {"ENTER", "NUMPADENTER"}
# Tasten, die ohne Zusatztaste ein Zeichen tippen (Buchstaben, Ziffern, Satzzeichen, Leertaste)
TYPING = ({chr(c) for c in range(ord("A"), ord("Z") + 1)} | {str(i) for i in range(10)}
          | {"SPACE", "MINUS", "EQUALS", "LBRACKET", "RBRACKET", "SEMICOLON", "APOSTROPHE", "GRAVE", "BACKSLASH",
             "COMMA", "PERIOD", "SLASH"} | {f"NUMPAD{i}" for i in range(10)}
          | {"NUMPADMULTIPLY", "NUMPADSUBTRACT", "NUMPADADD", "NUMPADDECIMAL", "NUMPADDIVIDE"})


def _walk(obj, path=""):
    """Alle (Pfad, Schlüssel, Wert) in verschachtelten dicts/Listen."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path, k, v
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def _objects(obj, path=""):
    """Alle dicts (auch Listenelemente wie Buttons) mit ihrem Pfad."""
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from _objects(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _objects(v, f"{path}[{i}]")


def _names(combo):
    """Tastennamen einer Kombination wie keys.parse_combo sie liest ("ctrl+esc" -> {"LCTRL", "ESC"})."""
    parts = [p.strip().upper() for p in str(combo).split("+") if p.strip()]
    return [keys.ALIASES.get(p, p) for p in parts]


def system_shortcut(combo):
    """Grund, wenn die Kombination ein Windows-Systemkürzel ist, sonst None."""
    n = set(_names(combo))
    if "ESC" in n and n & MODIFIERS:
        return "Esc mit Zusatztaste (Startmenü/Task-Manager)"
    if n & ALT and n & {"F4", "TAB", "SPACE"}:
        return "Alt+F4 / Alt+Tab / Alt+Leertaste"
    return None


def _macro_rules(where, steps):
    errs = []
    if len(steps) > MAX_STEPS:
        errs.append(f"{where}: Makro mit mehr als {MAX_STEPS} Schritten")
    texts = typing = enters = 0
    for st in steps:
        if not isinstance(st, dict):
            continue
        if "text" in st:
            texts += 1
        k = st.get("key")
        if isinstance(k, str):
            n = _names(k)
            base = [x for x in n if x not in SHIFT]            # Shift tippt ebenfalls (Großbuchstaben)
            if len(base) == 1 and not set(n) & (MODIFIERS - SHIFT):
                typing += base[0] in TYPING
                enters += base[0] in ENTER
    if texts > 1:
        errs.append(f"{where}: Makro mit mehr als einem text-Schritt")
    if typing > MAX_TYPING_KEYS:
        errs.append(f"{where}: Makro tippt mit {typing} einzelnen Zeichentasten (höchstens {MAX_TYPING_KEYS})")
    if enters > MAX_ENTER:
        errs.append(f"{where}: Makro mit mehr als {MAX_ENTER}x Enter")
    return errs


def community_rules(data):
    """Fehlerliste für die strengeren Regeln (leer = in Ordnung)."""
    errs = []
    for where, k, v in _walk(data):
        here = f"{where}.{k}" if where else k
        if k == "open":
            errs.append(f"{here}: 'open' ist in beigetragenen Panels nicht erlaubt")
        elif k in ("key", "up", "down") and isinstance(v, str):
            why = system_shortcut(v)
            if why:
                errs.append(f"{here}: Systemkürzel '{v}' nicht erlaubt ({why})")
        elif k == "macro" and isinstance(v, list):
            errs.extend(_macro_rules(here, v))
        elif k == "text" and isinstance(v, str) and re.search(r"(^|\.)macro\[\d+\]$", where):   # Makro-Schritt
            if len(v) > MAX_TEXT:
                errs.append(f"{here}: text länger als {MAX_TEXT} Zeichen")
            if not OK_TEXT.fullmatch(v):
                errs.append(f"{here}: text darf nur Buchstaben, Ziffern, Leerzeichen und . , ! ? : ; + - # * = ( ) "
                            "enthalten")
            elif BAD_WORDS.search(v):
                errs.append(f"{here}: text enthält einen Befehlsnamen ({BAD_WORDS.search(v).group(0)})")
    return errs


def community_warnings(data):
    """Hinweise für die Handprüfung (kein Fehler): Tasten, die nur Strg/Alt/Shift halten oder umschalten. In
    Spielen üblich (Sprinten mit Shift halten), mit einer zweiten Taste aber ein mögliches Systemkürzel."""
    out = []
    for where, o in _objects(data):
        k = o.get("key")
        if isinstance(k, str) and (o.get("hold") or o.get("mode") == "toggle"):
            n = _names(k)
            if n and set(n) <= MODIFIERS:
                out.append(f"{where or '(oben)'}: Taste hält/schaltet nur Zusatztasten ({k}) - bei der Handprüfung "
                           "ansehen (zusammen mit anderen Tasten: Systemkürzel?)")
    return out


def check_file(path):
    """Fehlerliste für eine Datei (Panel unter panels/ oder profiles/, Dashboard unter dashboards/, games.json)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        return [f"nicht lesbar: {e}"]
    full = path.resolve()
    rel = (full.relative_to(ROOT).as_posix() if full.is_relative_to(ROOT) else path.as_posix()).lower()
    try:
        if rel.startswith("dashboards/"):
            dashboard.validate(data)
            return []                       # Dashboards zeigen nur an
        if rel.startswith(("profiles/", "panels/")):   # panels/ = mitgelieferte, profiles/ = eigene/beigetragene
            layout.validate_layout(data)
            for w in community_warnings(data):
                print(f"{path}: Hinweis: {w}")
            return community_rules(data)
        if rel == "games.json":
            profiles.validate_games(data)   # exe nur als Programmname, Ordner/Karten geprüft
            return []
    except ValueError as e:
        return [str(e)]
    return []                               # andere Dateien prüft dieses Skript nicht


def targets(args):
    if args:
        return [Path(a) for a in args]
    return (sorted((ROOT / "panels").rglob("*.json")) + sorted((ROOT / "profiles").rglob("*.json")) + sorted((ROOT / "dashboards").glob("*.json"))
            + [ROOT / "games.json"])


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    files = [p for p in targets(args) if ".papierkorb" not in p.parts]
    bad = 0
    for p in files:
        errs = check_file(p)
        for e in errs:
            print(f"{p}: {e}")
        bad += bool(errs)
    print(f"{len(files)} Dateien geprüft, {bad} mit Fehlern")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
