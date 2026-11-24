"""Bibliothek installierter Spiele (Steam, Epic, GOG, Xbox, EA, Ubisoft, Windows Game Bar) und Zuordnung zum laufenden Prozess.

Nur lesend. Fehlende Launcher und kaputte Dateien werden still uebersprungen.
Registry-Zugriffe laufen ueber reg_value/reg_subkeys (in Tests ersetzbar).
"""
import ctypes
import json
import os
import re
import string
import xml.etree.ElementTree as ET
from ctypes import wintypes
from pathlib import Path

try:
    import winreg
except ImportError:  # kein Windows
    winreg = None

EPIC_MANIFESTS = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"

# --- Registry (kapselt winreg) ------------------------------------------------

_ROOTS = {"HKCU": "HKEY_CURRENT_USER", "HKLM": "HKEY_LOCAL_MACHINE"}


def _root(name):
    return getattr(winreg, _ROOTS[name])


def reg_value(root, path, name):
    """Wert lesen oder None."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(_root(root), path, 0, winreg.KEY_READ) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def reg_subkeys(root, path):
    """Namen der Unterschluessel (leer, wenn nicht vorhanden)."""
    if winreg is None:
        return []
    out = []
    try:
        with winreg.OpenKey(_root(root), path, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


# --- Hilfen ---------------------------------------------------------------------

def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    s = s[:40].strip("-")
    return s or "game"


def norm_path(p):
    return os.path.normpath(str(p).replace("/", "\\"))


def _key(p):
    return norm_path(p).lower().rstrip("\\")


def parse_vdf(text):
    """Einfaches Valve-KeyValues-Format -> verschachteltes dict (Schluessel kleingeschrieben)."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    pos = 0

    def unesc(s):
        return s.replace("\\\\", "\\").replace('\\"', '"')

    def block():
        nonlocal pos
        d = {}
        while pos < len(tokens):
            s, br = tokens[pos]
            pos += 1
            if br == "}":
                return d
            if br == "{":
                continue
            k = unesc(s).lower()
            if pos < len(tokens):
                s2, br2 = tokens[pos]
                if br2 == "{":
                    pos += 1
                    d[k] = block()
                elif not br2:
                    pos += 1
                    d[k] = unesc(s2)
        return d

    return block()


def _read(path):
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return Path(path).read_text(encoding=enc)
        except (UnicodeError, OSError):
            continue
    return None


# --- Steam ----------------------------------------------------------------------

_STEAM_SKIP_NAME = re.compile(
    r"redistributable|steamworks|proton|steam linux runtime|soundtrack|dedicated server|"
    r"\bsdk\b|\bost\b", re.I)
_STEAM_SKIP_IDS = {"228980", "1070560", "1391110", "1493710", "1628350", "1826330", "2180100"}


def _has_exe(d, depth=3):
    d = str(d)
    base = d.count(os.sep)
    try:
        for root, dirs, files in os.walk(d):
            if any(f.lower().endswith(".exe") for f in files):
                return True
            if root.count(os.sep) - base >= depth:
                dirs[:] = []
    except OSError:
        pass
    return False


def steam_cover(steam_root, appid):
    cache = Path(steam_root) / "appcache" / "librarycache"
    names = ["library_600x900.jpg", "library_capsule.jpg", "library_header.jpg",
             "header.jpg", "library_hero.jpg"]
    for n in names:
        cands = [cache / f"{appid}_{n}", cache / str(appid) / n]
        try:
            cands += sorted((cache / str(appid)).glob("*/" + n))
        except OSError:
            pass
        for c in cands:
            try:
                if c.is_file():
                    return str(c)
            except OSError:
                pass
    return None


def scan_steam(steam_root=None, check_exe=True):
    if steam_root is None:
        steam_root = reg_value("HKCU", r"Software\Valve\Steam", "SteamPath")
    if not steam_root:
        return []
    steam_root = norm_path(steam_root)
    libs = [steam_root]
    txt = _read(os.path.join(steam_root, "steamapps", "libraryfolders.vdf"))
    if txt:
        try:
            lf = parse_vdf(txt).get("libraryfolders", {})
            for v in lf.values():
                p = v.get("path") if isinstance(v, dict) else v
                if isinstance(p, str) and p:
                    libs.append(norm_path(p))
        except Exception:
            pass
    seen, out = set(), []
    for lib in libs:
        if _key(lib) in seen:
            continue
        seen.add(_key(lib))
        sa = Path(lib) / "steamapps"
        try:
            files = sorted(sa.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for f in files:
            try:
                t = _read(f)
                st = parse_vdf(t).get("appstate", {}) if t else {}
                appid, name, inst = st.get("appid"), st.get("name"), st.get("installdir")
                if not (appid and name and inst):
                    continue
                if appid in _STEAM_SKIP_IDS or _STEAM_SKIP_NAME.search(name):
                    continue
                d = sa / "common" / inst
                if not d.is_dir() or (check_exe and not _has_exe(d)):
                    continue
                out.append(_entry(name, "steam", d, appid, steam_cover(steam_root, appid)))
            except Exception:
                continue
    return out


# --- Epic -----------------------------------------------------------------------

def scan_epic(manifests=EPIC_MANIFESTS):
    out = []
    try:
        files = sorted(Path(manifests).glob("*.item"))
    except OSError:
        return out
    for f in files:
        try:
            j = json.loads(_read(f))
            name, loc = j.get("DisplayName"), j.get("InstallLocation")
            if name and loc and os.path.isdir(loc):
                out.append(_entry(name, "epic", loc))
        except Exception:
            continue
    return out


# --- GOG ------------------------------------------------------------------------

def scan_gog():
    base = r"SOFTWARE\WOW6432Node\GOG.com\Games"
    out = []
    for sub in reg_subkeys("HKLM", base):
        name = reg_value("HKLM", base + "\\" + sub, "gameName")
        path = reg_value("HKLM", base + "\\" + sub, "path")
        if name and path and os.path.isdir(path):
            out.append(_entry(name, "gog", path))
    return out


# --- Xbox -----------------------------------------------------------------------

def _xbox_name(content, fallback):
    try:
        root = ET.parse(os.path.join(content, "MicrosoftGame.config")).getroot()
        for el in root.iter("ShellVisuals"):
            n = el.get("DefaultDisplayName")
            if n and not n.startswith("ms-resource:"):
                return n
    except Exception:
        pass
    return fallback


def _xbox_roots(drive):
    """Xbox-Spielordner eines Laufwerks: laut .GamingRoot (RGBX, uint32, Ordnername UTF-16 mit Nullende),
    dazu immer der Standardordner XboxGames."""
    roots = [os.path.join(drive, "XboxGames")]
    try:
        with open(os.path.join(drive, ".GamingRoot"), "rb") as f:
            raw = f.read(4096)
    except OSError:
        return roots
    if raw[:4] == b"RGBX":
        rel = raw[8:].decode("utf-16-le", "ignore").split("\0")[0].replace("/", "\\").strip("\\ ")
        # nur ein Ordner unterhalb des Laufwerks, nie das ganze Laufwerk
        if rel and ":" not in rel and not {".", ".."} & set(rel.split("\\")):
            d = os.path.join(drive, rel)
            if _key(d) != _key(roots[0]):
                roots.insert(0, d)
    return roots


def scan_xbox(drives=None):
    if drives is None:
        drives = [f"{c}:\\" for c in string.ascii_uppercase if os.path.isdir(f"{c}:\\")]
    out = []
    for dr in drives:
        for xg in _xbox_roots(dr):
            try:
                subs = sorted(os.listdir(xg))
            except OSError:
                continue
            for s in subs:
                content = os.path.join(xg, s, "Content")
                if os.path.isdir(content) and _has_exe(content, 2):
                    out.append(_entry(_xbox_name(content, s), "xbox", content))
    return out


# --- EA / Ubisoft ---------------------------------------------------------------

def scan_ea():
    out = []
    for base in (r"SOFTWARE\WOW6432Node\EA Games", r"SOFTWARE\EA Games"):
        for sub in reg_subkeys("HKLM", base):
            p = reg_value("HKLM", base + "\\" + sub, "Install Dir")
            if p and os.path.isdir(p):
                out.append(_entry(sub, "ea", p))
    return out


def scan_ubisoft():
    base = r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"
    out = []
    for sub in reg_subkeys("HKLM", base):
        p = reg_value("HKLM", base + "\\" + sub, "InstallDir")
        if p and os.path.isdir(p):
            out.append(_entry(os.path.basename(norm_path(p)), "ubisoft", p))
    return out


# --- Windows (GameConfigStore / Game Bar) -----------------------------------------

_SKIP_DIRS = {"binaries", "win64", "win32", "bin64", "bin32", "bin", "x64", "x86", "shipping", "live", "game"}
_GENERIC_NAME = re.compile(
    r"^(ue4 game|ue5 game|unreal engine|bootstrappackagedgame|shipping|game|application|"
    r"unity|unity player|.*packagedgame|.*-win64-shipping)$", re.I)


def exe_product_name(exe):
    """ProductName (sonst FileDescription) aus der Versionsinfo oder None."""
    try:
        ver = ctypes.WinDLL("version")
        ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(wintypes.UINT)]
        size = ver.GetFileVersionInfoSizeW(exe, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(exe, 0, size, buf):
            return None
        ptr, ln = ctypes.c_void_p(), wintypes.UINT()
        langs = []
        if ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(ln)) \
                and ln.value >= 4:
            for i in range(ln.value // 4):
                lang, cp = ctypes.cast(ptr.value + 4 * i, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
                langs.append("%04x%04x" % (lang, cp))
        langs += ["040904b0", "040904e4", "000004b0"]
        for field in ("ProductName", "FileDescription"):
            for lc in langs:
                if ver.VerQueryValueW(buf, "\\StringFileInfo\\%s\\%s" % (lc, field),
                                      ctypes.byref(ptr), ctypes.byref(ln)) and ln.value:
                    v = ctypes.wstring_at(ptr.value, ln.value).strip("\0 ").strip()
                    if v:
                        return v
    except Exception:
        pass
    return None


_BROAD_DIRS = {"program files", "program files (x86)", "windows", "programdata", "users",
               "games", "spiele", "steamlibrary", "xboxgames"}
_STOP_NAMES = {"launcher", "client", "setup", "game", "application", "app", "main", "start"}


_SHIPPING = re.compile(r"[-_ ]win(64|32)([-_ ]shipping)?$|[-_ ]shipping$", re.I)


def _windows_game_dir(exe):
    """(Spielordner, Ordnername, breit): vom exe-Ordner aufwaerts Ordner wie Binaries/Win64 ueberspringen.
    Laufwerkswurzel, Systemordner und Sammelordner (Games, ...) sind kein Spielordner -> exe-Ordner, breit=True
    (dort koennen mehrere Spiele liegen: nicht nach Ordner zusammenfassen, Name aus dem exe-Stamm)."""
    start = Path(norm_path(exe)).parent
    d = start
    while d.name and d.name.lower() in _SKIP_DIRS and d.parent != d:
        d = d.parent
    if not d.name or d.name.lower() in _BROAD_DIRS or d.parent == d:
        return str(start), _SHIPPING.sub("", Path(exe).stem) or Path(exe).stem, True
    return str(d), d.name, False


def _windows_name(exe, folder_name):
    n = (exe_product_name(exe) or "").strip()
    if n and not _GENERIC_NAME.match(n) and n.lower() != Path(exe).stem.lower()             and n.lower() not in _STOP_NAMES:
        return n
    return folder_name


def _last_accessed(sub_path):
    v = reg_value("HKCU", sub_path, "LastAccessed")
    return v if isinstance(v, int) else 0


def scan_windows(existing=None):
    base = r"System\GameConfigStore\Children"
    others = [_key(g["dir"]) for g in existing or [] if g.get("dir")]
    cands, seen = [], set()
    for sub in reg_subkeys("HKCU", base):
        exe = reg_value("HKCU", base + "\\" + sub, "MatchedExeFullPath")
        if not exe or not isinstance(exe, str) or not os.path.isfile(exe):
            continue
        e = _key(exe)
        if e in seen or is_helper(exe) or any(e.startswith(o + "\\") for o in others if o):
            continue
        seen.add(e)
        cands.append((exe, _last_accessed(base + "\\" + sub)))
    groups = {}
    for exe, acc in cands:
        d, folder, broad = _windows_game_dir(exe)
        groups.setdefault(_key(exe) if broad else _key(d), []).append((exe, acc, d, folder))
    out = []
    for items in groups.values():
        # bevorzugt: kein Hilfsprogramm-Aussehen (Stamm gleich Ordnername), dann zuletzt benutzt
        items.sort(key=lambda t: (Path(t[0]).stem.lower() == t[3].lower(), t[1]), reverse=True)
        exe, _, d, folder = items[0]
        g = _entry(_windows_name(exe, folder), "windows", d)
        g["exe"] = norm_path(exe)
        g["exes"] = [norm_path(t[0]) for t in items]
        out.append(g)
    return out


def _entry(name, source, d, steam=None, cover=None):
    return {"id": slugify(name), "name": name, "source": source, "dir": norm_path(d),
            "steam": steam, "cover": cover}


def scan_library():
    out, ids = [], set()
    for fn in (scan_steam, scan_epic, scan_gog, scan_xbox, scan_ea, scan_ubisoft, scan_windows):
        try:
            items = fn(list(out)) if fn is scan_windows else fn()
        except Exception:
            continue
        for g in items:
            base, n = g["id"], 2
            while g["id"] in ids:
                g["id"] = f"{base[:37]}-{n}"
                n += 1
            ids.add(g["id"])
            out.append(g)
    return out


# --- Prozesse -------------------------------------------------------------------

def running_game_paths():
    """Volle exe-Pfade aller Prozesse, die wir oeffnen duerfen."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    n = 4096
    while True:
        arr = (wintypes.DWORD * n)()
        got = wintypes.DWORD()
        if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(got)):
            return []
        if got.value < ctypes.sizeof(arr):
            break
        n *= 2
    paths = []
    for pid in arr[: got.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid:
            continue
        try:
            h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                continue
            try:
                buf = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(buf))
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    paths.append(buf.value)
            finally:
                k32.CloseHandle(h)
        except Exception:
            continue
    return paths


# --- Zuordnung ------------------------------------------------------------------

_HELPER = re.compile(
    r"crash|easyanticheat|^eac|battleye|beservice|vc_?redist|dxsetup|"
    r"^unins\d*\.exe|^setup\.exe|dotnet|prereq|installer|cefsubprocess|webhelper", re.I)
_LAUNCHER_EXE = {"steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "galaxyclient.exe",
                 "eadesktop.exe", "ealauncher.exe", "upc.exe", "ubisoftconnect.exe",
                 "ubisoftgamelauncher.exe", "origin.exe"}


_UTIL_NAME = re.compile(r"launcher|updater|config|setup|settings", re.I)


def is_helper(exe_path):
    n = os.path.basename(exe_path).lower()
    return n in _LAUNCHER_EXE or bool(_HELPER.search(n)) or bool(_UTIL_NAME.search(n))


def match(library, exe_paths):
    best, best_len = None, -1
    for exe in exe_paths or []:
        if is_helper(exe):
            continue
        e = _key(exe)
        for g in library or []:
            if g.get("source") == "windows" and g.get("exe"):
                if e in {_key(x) for x in (g.get("exes") or [g["exe"]])} and len(e) > best_len:
                    best, best_len = g, len(e)
                continue
            d = _key(g["dir"])
            if d and e.startswith(d + "\\") and len(d) > best_len:
                best, best_len = g, len(d)
    return best
