"""Spielprofile: mehrere Panels pro Spiel.

Ablage:
  games.json                     Spiele: id, name, exe (Prozessnamen), steam (AppID), panels (Reihenfolge),
                                 maps (Kartenanbieter: name, url)
  profiles/<spiel>/<panel>.json  ein Panel im Format von layout.json (pages, holdMs) plus "title"

Beim ersten Start ohne Ordner profiles/ wird das alte layout.json als profiles/star-citizen/main.json übernommen.
Tasten-IDs sind nur innerhalb eines Panels eindeutig; der Hub merkt sich pro Tablet-Verbindung das Panel.
"""
import json
import logging
import os
import re
import shutil
from pathlib import Path

from .layout import save_layout, validate_layout

log = logging.getLogger("profiles")
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
EXE = re.compile(r"[^\\/:*?\"<>|\r\n]{1,100}\.exe", re.I)
MAP_URL = re.compile(r"(?i)https://[^\s]+")
MIGRATE_GAME, MIGRATE_PANEL = "star-citizen", "main"
COVER_ID = re.compile(r"[a-z0-9-]{1,40}")
COVER_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def cover_type(path):
    """Content-Type nach Endung (nur jpg/png) oder None."""
    return COVER_TYPES.get(os.path.splitext(str(path or ""))[1].lower())


def _lib_has_exe(e, names):
    """Windows-Eintraege: nur bekannte exe-Namen (kein os.walk, Ordner koennte gross sein)."""
    if e.get("source") == "windows":
        return any(os.path.basename(x).lower() in names for x in (e.get("exes") or [e.get("exe") or ""]))
    return _dir_has_exe(e["dir"], names)


def _dir_has_exe(d, names, depth=3):
    """Liegt eines der Programme (kleingeschrieben) im Spielordner (bis depth Ebenen tief)?"""
    d = str(d)
    base = d.count(os.sep)
    try:
        for root, dirs, files in os.walk(d):
            if any(f.lower() in names for f in files):
                return True
            if root.count(os.sep) - base >= depth:
                dirs[:] = []
    except OSError:
        pass
    return False


class Exists(ValueError):
    """Panel-Datei gibt es schon (Fehlercode "exists" an den Editor)."""


def _err(msg):
    raise ValueError(msg)


def validate_games(data):
    """games.json prüfen; gibt die Liste der Spiele zurück (exe kleingeschrieben)."""
    if not isinstance(data, dict) or not isinstance(data.get("games"), list):
        _err("games.json braucht eine Liste 'games'")
    out, seen = [], set()
    for g in data["games"]:
        gid = g.get("id") if isinstance(g, dict) else None
        if not isinstance(gid, str) or not ID.fullmatch(gid) or gid in seen:
            _err(f"Spiel ohne/mit ungültiger oder doppelter id: {gid!r} (erlaubt: a-z, 0-9, -)")
        seen.add(gid)
        name = g.get("name", gid)
        exe = g.get("exe", [])
        if not isinstance(name, str) or not 0 < len(name) <= 80:
            _err(f"{gid}: name 1-80 Zeichen")
        if not isinstance(exe, list) or not all(isinstance(e, str) and EXE.fullmatch(e) for e in exe):
            _err(f"{gid}: exe muss eine Liste von Programmnamen (*.exe) sein")
        steam = g.get("steam")
        if steam is not None and not (isinstance(steam, int) and 0 < steam < 10 ** 9):
            _err(f"{gid}: steam muss eine AppID (Zahl) oder null sein")
        panels = g.get("panels", [])
        if not isinstance(panels, list) or not all(isinstance(p, str) and ID.fullmatch(p) for p in panels):
            _err(f"{gid}: panels muss eine Liste von Panel-ids sein")
        maps = g.get("maps", [])
        if not isinstance(maps, list):
            _err(f"{gid}: maps muss eine Liste sein")
        for m in maps:
            if not (isinstance(m, dict) and isinstance(m.get("name"), str) and 0 < len(m["name"]) <= 60
                    and isinstance(m.get("url"), str) and len(m["url"]) <= 1024 and MAP_URL.fullmatch(m["url"])):
                _err(f"{gid}: Karte braucht name und eine https-URL")
        bnd = g.get("bindings")
        if bnd is not None:
            from .bindings import ADAPTERS
            if not (isinstance(bnd, dict) and bnd.get("adapter") in ADAPTERS and all(
                    isinstance(v, str) and len(v) <= 1024 for v in bnd.values())):
                _err(f"{gid}: bindings braucht adapter ({', '.join(ADAPTERS)}) und Pfade als Text")
        out.append({"id": gid, "name": name, "exe": [e.lower() for e in exe], "steam": steam,
                    "panels": panels, "maps": [{"name": m["name"], "url": m["url"]} for m in maps],
                    "bindings": bnd})
    return out


class Profiles:
    def __init__(self, root, games_path, legacy_layout=None):
        self.dir = Path(root)
        self.games_path = Path(games_path)
        self.legacy = Path(legacy_layout) if legacy_layout else None
        self.games = []          # aus games.json
        self.games_mtime = None
        self.panels = {}         # "spiel/panel" -> {"layout", "buttons", "mtime"}
        self.failed = {}         # "spiel/panel" -> mtime einer fehlerhaften, nicht geladenen Datei (nur einmal melden)
        self._lib = ({}, {}, {}, [])  # (games.json-id -> Bibliothekseintrag, Bibliotheks-id -> Spiel-id, Spiel-id -> Eintrag)
        self.extra_maps = {}     # Spiel-id (nur Bibliothek) -> Karten (Map Genie)

    # ---------------- Laden ----------------
    def migrate(self):
        """Altes layout.json übernehmen - nur wenn es den Ordner profiles/ noch gar nicht gibt (sonst käme ein
        absichtlich gelöschtes Profil wieder). Das Original bleibt liegen."""
        if self.dir.exists() or not (self.legacy and self.legacy.is_file()):
            return False
        target = self.dir / MIGRATE_GAME / f"{MIGRATE_PANEL}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        layout = json.loads(self.legacy.read_text(encoding="utf-8"))
        layout.setdefault("title", "Pilot")
        save_layout(target, layout)
        log.info("layout.json als Profil %s/%s übernommen", MIGRATE_GAME, MIGRATE_PANEL)
        return True

    def load_games(self):
        """games.json neu laden, wenn geändert. Fehler: alte Liste bleibt (beim Start: leer)."""
        try:
            mtime = self.games_path.stat().st_mtime
        except OSError:
            if self.games:
                self.games, self.games_mtime = [], None
                return True
            return False
        if mtime == self.games_mtime:
            return False
        self.games_mtime = mtime
        try:
            self.games = validate_games(json.loads(self.games_path.read_text(encoding="utf-8")))
            log.info("games.json: %d Spiele", len(self.games))
        except (ValueError, OSError) as e:
            log.error("games.json fehlerhaft, bisherige Liste bleibt: %s", e)
            return False
        return True

    def scan(self):
        """Profile neu einlesen, deren Datei sich geändert hat. Gibt die geänderten Schlüssel zurück.
        Eine kaputte Datei lässt das bisherige Panel aktiv (wie früher beim Layout)."""
        changed, seen = [], set()
        for f in sorted(self.dir.glob("*/*.json")):
            game, panel = f.parent.name, f.stem
            if not (ID.fullmatch(game) and ID.fullmatch(panel)):
                continue
            key = f"{game}/{panel}"
            seen.add(key)
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue   # wird gerade gespeichert
            old = self.panels.get(key)
            if old and old["mtime"] == mtime or self.failed.get(key) == mtime:
                continue
            try:
                layout = json.loads(f.read_text(encoding="utf-8"))
                buttons = validate_layout(layout)
                if "title" in layout and not (isinstance(layout["title"], str) and 0 < len(layout["title"]) <= 40):
                    raise ValueError("title 1-40 Zeichen")
            except (ValueError, OSError) as e:
                log.error("Profil %s fehlerhaft, %s: %s", key, "altes bleibt aktiv" if old else "nicht geladen", e)
                if old:
                    old["mtime"] = mtime
                else:
                    self.failed[key] = mtime
                continue
            self.failed.pop(key, None)
            self.panels[key] = {"layout": layout, "buttons": buttons, "mtime": mtime}
            changed.append(key)
            log.info("Profil %s geladen: %d Seiten, %d Tasten", key, len(layout["pages"]), len(buttons))
        for key in list(self.panels):
            if key not in seen:
                del self.panels[key]
                changed.append(key)
                log.info("Profil %s entfernt", key)
        return changed

    # ---------------- Bibliothek (library.py) ----------------
    def set_library(self, lib):
        """Bibliothek merken (darf in einem Hilfs-Thread laufen: sucht Programme in Spielordnern).
        games.json hat Vorrang; Zuordnung über gleiche Steam-AppID oder ein exe aus games.json im Spielordner."""
        lib = [e for e in (lib or []) if isinstance(e, dict) and e.get("id") and e.get("dir")]
        links, lib_gid, extras = {}, {}, {}
        for g in list(self.games):
            hit = None
            for e in lib:
                if e["id"] not in lib_gid and g["steam"] and e.get("steam") and str(g["steam"]) == str(e["steam"]):
                    hit = e
                    break
            if hit is None and g["exe"]:
                names = set(g["exe"])
                hit = next((e for e in lib if e["id"] not in lib_gid and _lib_has_exe(e, names)), None)
            if hit:
                links[g["id"]] = hit
                lib_gid[hit["id"]] = g["id"]
        taken = {g["id"] for g in self.games}
        for e in lib:
            if e["id"] in lib_gid:
                continue
            gid, n = e["id"], 2
            while gid in taken:
                gid, n = f"{e['id'][:37]}-{n}", n + 1
            taken.add(gid)
            extras[gid] = e
            lib_gid[e["id"]] = gid
        self._lib = (links, lib_gid, extras, lib)   # ein Tupel: Leser sehen nie Mischzustände

    @property
    def library(self):
        return self._lib[3]

    def match_library(self, exe_paths):
        """Spiel-id des laufenden Bibliotheksspiels (aus vollen exe-Pfaden) oder None."""
        from . import library
        lib_gid, lib = self._lib[1], self._lib[3]   # ein Schnappschuss
        e = library.match(lib, exe_paths)
        return lib_gid.get(e["id"]) if e else None

    def is_extra(self, gid):
        """Spiel nur aus der Bibliothek (kein Eintrag in games.json)."""
        return gid in self._lib[2] and not any(g["id"] == gid for g in self.games)

    def set_extra_maps(self, gid, maps):
        self.extra_maps = dict(self.extra_maps, **{gid: maps})

    def map_games(self):
        """Spiele für die Karten-Kachel: alle aus games.json, dazu Bibliotheksspiele mit Karten."""
        out = list(self.games)
        out += [self.game(g) for g in sorted(self._lib[2]) if self.extra_maps.get(g)
                and not any(x["id"] == g for x in self.games)]
        return out

    def cover_file(self, gid):
        """(Pfad, Content-Type) des Coverbilds - Pfad nur aus der Bibliothek, nie aus der Anfrage."""
        if not (isinstance(gid, str) and COVER_ID.fullmatch(gid)):
            return None
        g = self.game(gid)
        path = g.get("cover") if g else None
        ctype = cover_type(path)
        if not (ctype and os.path.isfile(path)):
            return None
        return path, ctype

    # ---------------- Abfragen ----------------
    def game(self, gid):
        for g in self.games:
            if g["id"] == gid:
                e = self._lib[0].get(gid)
                return dict(g, cover=e.get("cover"), dir=e["dir"]) if e else g
        e = self._lib[2].get(gid)
        if e:
            steam = int(e["steam"]) if str(e.get("steam") or "").isdigit() else None
            return {"id": gid, "name": e["name"], "exe": [], "steam": steam, "panels": [],
                    "maps": self.extra_maps.get(gid, []), "bindings": None,
                    "cover": e.get("cover"), "dir": e["dir"]}
        return None

    def exe_names(self, gid):
        """Programmnamen des Spiels (games.json, dazu Programme aus der Bibliothek), ohne Pfad, ohne Doppelte."""
        names = []
        for g in self.games:
            if g["id"] == gid:
                names += g["exe"]
        e = self._lib[0].get(gid) or self._lib[2].get(gid)
        if e:
            names += [os.path.basename(x) for x in (e.get("exes") or [e.get("exe") or ""]) if x]
        return list(dict.fromkeys(names))

    def panel_ids(self, gid):
        """Panels eines Spiels: Reihenfolge aus games.json, weitere Dateien alphabetisch dahinter."""
        have = sorted(k.split("/", 1)[1] for k in self.panels if k.split("/", 1)[0] == gid)
        g = self.game(gid)
        order = [p for p in (g["panels"] if g else []) if p in have]
        return order + [p for p in have if p not in order]

    def panel_list(self, gid):
        return [{"id": p, "title": self.panels[f"{gid}/{p}"]["layout"].get("title", p)} for p in self.panel_ids(gid)]

    def game_ids(self):
        """Alle Spiele: aus games.json, dazu Ordner mit Profilen ohne Eintrag."""
        ids = [g["id"] for g in self.games]
        return ids + sorted(({k.split("/", 1)[0] for k in self.panels} | set(self._lib[2])) - set(ids))

    def summary(self, gid):
        g = self.game(gid) or {"id": gid, "name": gid, "steam": None, "maps": []}
        return {"id": gid, "name": g["name"], "steam": g["steam"], "maps": g["maps"],
                "cover": bool(cover_type(g.get("cover"))), "panels": self.panel_list(gid)}

    def default_key(self, gid=None):
        """Panel, das ein Tablet ohne eigene Wahl bekommt: erstes Panel des laufenden Spiels, sonst des
        ersten Spiels mit Panels."""
        for g in ([gid] if gid else []) + self.game_ids():
            ids = self.panel_ids(g)
            if ids:
                return f"{g}/{ids[0]}"
        return None

    def get(self, key):
        return self.panels.get(key)

    def detect(self, procs):
        """Erstes Spiel aus games.json, dessen Programm läuft (procs: kleingeschriebene Prozessnamen)."""
        for g in self.games:
            if any(e in procs for e in g["exe"]):
                return g["id"]
        return None

    # ---------------- Schreiben (Editor) ----------------
    def path(self, game, panel):
        if not (isinstance(game, str) and ID.fullmatch(game) and isinstance(panel, str) and ID.fullmatch(panel)):
            _err("Spiel- und Panel-id: a-z, 0-9, - (max. 40 Zeichen)")
        return self.dir / game / f"{panel}.json"

    def save(self, game, panel, layout, new=False):
        """new=True: Panel neu anlegen - eine vorhandene Datei (auch eine gerade ungültige) wird nie überschrieben."""
        p = self.path(game, panel)
        if new and p.exists():
            raise Exists(f"Panel {game}/{panel} gibt es schon (Datei vorhanden) – bitte anderen Titel wählen")
        if isinstance(layout, dict) and "title" in layout and not (
                isinstance(layout["title"], str) and 0 < len(layout["title"]) <= 40):
            _err("title 1-40 Zeichen")
        p.parent.mkdir(parents=True, exist_ok=True)
        save_layout(p, layout)
        return f"{game}/{panel}"

    def create(self, game, panel, title, copy_from=None):
        """Neues Panel anlegen (leer oder als Kopie). Vorhandene Dateien werden nie überschrieben."""
        p = self.path(game, panel)
        if p.exists():
            _err(f"Panel {game}/{panel} gibt es schon")
        if copy_from:
            src = self.get(copy_from)
            if not src:
                _err("Vorlage-Panel nicht gefunden")
            layout = json.loads(json.dumps(src["layout"]))
        else:
            layout = {"holdMs": 1000, "pages": [{"id": "seite1", "title": "Seite 1", "buttons": []}]}
        layout["title"] = title
        return self.save(game, panel, layout)

    def delete(self, game, panel):
        """Panel löschen: wird nach profiles/.papierkorb/ verschoben (wiederherstellbar)."""
        p = self.path(game, panel)
        if not p.is_file():
            _err("Panel nicht gefunden")
        trash = self.dir / ".papierkorb"
        trash.mkdir(exist_ok=True)
        n = 1
        while (trash / f"{game}--{panel}-{n}.json").exists():
            n += 1
        shutil.move(str(p), str(trash / f"{game}--{panel}-{n}.json"))
