"""Wo ein Spiel seine Steuerung ablegt: Ordner und Registry-Schlüssel ermitteln (ohne zu lesen).

Quellen: Installationsordner; Dokumente, My Games, Saved Games, Benutzerordner; AppData Local/LocalLow/Roaming;
Steam-Cloud-Ordner (Steam\\userdata\\<id>\\<appid>); Unreal-Projektname aus dem Installationsordner
(<Projekt>\\Binaries\\Win64 -> %LOCALAPPDATA%\\<Projekt>); Unity-Hersteller/Produkt aus <Spiel>_Data\\app.info
(-> LocalLow\\<Hersteller>\\<Produkt>, Registry HKCU\\Software\\<Hersteller>\\<Produkt>). Ordnernamen werden
tolerant verglichen (Wortteile, z. B. „Project Zomboid“ -> „Zomboid“).
"""
import os
import re
from pathlib import Path

STOP = {"the", "game", "games", "edition", "complete", "remastered", "remake", "definitive", "of", "and", "for",
        "ii", "iii", "iv", "deluxe", "ultimate", "gold", "goty", "enhanced", "director's", "cut", "online",
        # Hersteller-/Sammelwörter: ein Ordner „Microsoft“ oder „Studio“ gehört nicht zu einem Spiel dieses Namens
        "microsoft", "studio", "studios", "interactive", "entertainment", "software", "project", "simulator",
        "world", "total", "steam", "epic", "ubisoft", "electronic", "arts", "windows", "local", "common", "data"}


def _home():
    return Path(os.path.expanduser("~"))


def documents():
    """Dokumente-Ordner (auch umgeleitet, z. B. OneDrive), sonst ~/Documents."""
    home = _home()
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:   # CSIDL_PERSONAL
            p = Path(buf.value)
            if p.is_dir():
                return p
    except Exception:  # noqa: BLE001 - kein Windows o. Ä.
        pass
    return home / "Documents"


def local_low():
    home = _home()
    return Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")).parent / "LocalLow"


def bases():
    home, docs = _home(), documents()
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    out = [docs, docs / "My Games", home / "Documents", home / "Documents" / "My Games", home / "Saved Games",
           local, local.parent / "LocalLow", roaming, home]
    seen, res = set(), []
    for b in out:
        k = str(b).lower()
        if k not in seen:
            seen.add(k)
            res.append(b)
    return res


def tokens(name):
    """Bedeutende Wortteile eines Namens (klein, ohne Satzzeichen, ab 4 Zeichen, ohne Füllwörter)."""
    words = re.findall(r"[a-z0-9]+", str(name or "").lower().replace("&", " "))
    return {w for w in words if len(w) >= 4 and w not in STOP}


ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}


def _squash(s):
    words = re.findall(r"[a-z0-9]+", str(s).lower())
    return "".join(ROMAN.get(w, w) for w in words)


def name_matches(dirname, names):
    """Ordnername passt zu einem der Namen: gleich (ohne Satzzeichen) oder enthält einen bedeutenden Wortteil."""
    d = _squash(dirname)
    if len(d) < 3:
        return False
    for n in names:
        sq = _squash(n)
        # gleich, Spielname im Ordnernamen, oder Ordnername deckt den größten Teil des Spielnamens ab
        if sq and (d == sq or (len(sq) >= 5 and sq in d) or (len(d) >= 5 and d in sq and len(d) >= 0.6 * len(sq))):
            return True
        ts = tokens(n)
        if ts and (any(t == d for t in ts) or all(t in d for t in ts)):   # alle bedeutenden Wortteile
            return True
    return False


def exact_match(dirname, names):
    d = _squash(dirname)
    return len(d) >= 5 and any(d == _squash(n) or (len(d) >= 6 and d in _squash(n)) for n in names)


def unreal_projects(install_dir):
    """Unreal-Projektnamen im Installationsordner: <Projekt>/Binaries/Win64|WinGDK/*.exe."""
    out = []
    root = Path(install_dir)
    for depth in ("*/Binaries/*/*.exe", "*/*/Binaries/*/*.exe"):
        for exe in root.glob(depth):
            proj = exe.parent.parent.parent.name
            if proj.lower() not in ("engine",) and proj not in out:
                out.append(proj)
    return out[:4]


def unity_app(install_dir):
    """(Hersteller, Produkt) aus <Spiel>_Data/app.info eines Unity-Spiels, sonst None."""
    for info in Path(install_dir).glob("*_Data/app.info"):
        try:
            lines = info.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if len(lines) >= 2 and lines[0].strip() and lines[1].strip():
            return lines[0].strip(), lines[1].strip()
    return None


def steam_dirs(appid):
    """Steam-Cloud-Ordner des Spiels für alle Steam-Konten auf dem PC."""
    if not appid:
        return []
    roots = []
    try:
        from ..library import norm_path, reg_value
        r = reg_value("HKCU", r"Software\Valve\Steam", "SteamPath")
        if r:
            roots.append(Path(norm_path(r)))
    except Exception:  # noqa: BLE001
        pass
    roots.append(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam")
    out = []
    for root in roots:
        ud = root / "userdata"
        try:
            for acc in ud.iterdir():
                p = acc / str(appid)
                if p.is_dir() and p not in out:
                    out.append(p)
        except OSError:
            continue
    return out


def locations(name, install_dir=None, appid=None):
    """[(Ordner, ist_benutzerordner)] und [(Registry-Pfad)] für ein Spiel."""
    names = [n for n in (name, Path(install_dir).name if install_dir else None) if n]
    dirs, regs = [], []
    unity = None
    if install_dir and Path(install_dir).is_dir():
        names += unreal_projects(install_dir)
        unity = unity_app(install_dir)
    for b in bases():
        try:
            entries = [p for p in b.iterdir() if p.is_dir()]
        except OSError:
            continue
        for p in entries:
            if name_matches(p.name, names) and p not in [d for d, _ in dirs]:
                dirs.append((p, True))
            elif b != _home():
                # zweite Ebene (Hersteller-Ordner, z. B. Paradox Interactive\Crusader Kings III): nur genaue Namen
                try:
                    for q in p.iterdir():
                        if q.is_dir() and exact_match(q.name, names) and q not in [d for d, _ in dirs]:
                            dirs.append((q, True))
                except OSError:
                    continue
    if unity:
        company, product = unity
        p = local_low() / company / product
        if p.is_dir() and p not in [d for d, _ in dirs]:
            dirs.append((p, True))
        regs.append(rf"Software\{company}\{product}")
    for p in steam_dirs(appid):
        dirs.append((p, True))
    if install_dir and Path(install_dir).is_dir():
        dirs.append((Path(install_dir), False))
    return dirs, regs
