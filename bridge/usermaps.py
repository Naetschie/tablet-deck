"""Eigene Kartenlisten (maps.json, nicht im Git - wie config.json): {"games": {"<spiel-id>": [{name, url, heavy?}]}}.

Ein Eintrag ersetzt für dieses Spiel die Standardliste (games.json bzw. Map Genie); fehlt er, gilt wieder der
Standard. games.json selbst bleibt unangetastet, weil es bei einem Update überschrieben wird. Geändert über den
Editor (Reiter „Karten“) oder von Hand; der Hub lädt die Datei bei jeder Änderung neu.
"""
import json
import logging
import os
import tempfile
from pathlib import Path

from .profiles import ID, validate_maps

log = logging.getLogger("profiles")
MAX_GAMES = 500


def validate(data):
    """maps.json prüfen; gibt {spiel-id: Karten} zurück."""
    if not isinstance(data, dict) or not isinstance(data.get("games", {}), dict):
        raise ValueError("maps.json braucht ein Objekt 'games'")
    games = data.get("games", {})
    if len(games) > MAX_GAMES:
        raise ValueError(f"maps.json: höchstens {MAX_GAMES} Spiele")
    out = {}
    for gid, maps in games.items():
        if not (isinstance(gid, str) and ID.fullmatch(gid)):
            raise ValueError(f"maps.json: ungültige Spiel-id {gid!r}")
        out[gid] = validate_maps(maps, gid)
    return out


class UserMaps:
    def __init__(self, path):
        self.path = Path(path)
        self.maps = {}
        self.mtime = None

    def load(self):
        """Neu laden, wenn sich die Datei geändert hat; True bei Änderung. Kaputte Datei: alte Listen bleiben."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            if self.mtime is None:
                return False
            self.mtime, self.maps = None, {}
            return True
        if mtime == self.mtime:
            return False
        self.mtime = mtime
        try:
            new = validate(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            log.error("maps.json fehlerhaft, bisherige Karten bleiben: %s", e)
            return False
        changed = new != self.maps
        self.maps = new
        if changed:
            log.info("maps.json: eigene Karten für %d Spiel(e)", len(new))
        return changed

    def set(self, gid, maps):
        """Liste eines Spiels setzen (None = Eintrag entfernen, Standard gilt wieder) und atomar speichern."""
        if not (isinstance(gid, str) and ID.fullmatch(gid)):
            raise ValueError("Spiel-id: a-z, 0-9, - (max. 40 Zeichen)")
        new = dict(self.maps)
        if maps is None:
            new.pop(gid, None)
        else:
            new[gid] = validate_maps(maps, gid)
        validate({"games": new})
        if new == self.maps and (self.path.exists() or not new):
            return new   # unverändert: nicht schreiben
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".maps-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"games": new}, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.maps = new
        try:
            self.mtime = self.path.stat().st_mtime
        except OSError:
            self.mtime = None
        return new
