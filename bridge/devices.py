"""Geräteliste des Hubs (devices.json): jedes per USB gekoppelte Gerät mit Launcher, eins davon Hauptgerät.

Nichts ist fest verdrahtet: Der Hub trägt ein Gerät beim ersten Koppeln selbst ein (Seriennummer + Modell),
das erste wird Hauptgerät. Das Hauptgerät bekommt „An Tablet senden“; umstellen per set_main (Taskleiste).
Pro Gerät optional: name, mode (home/companion), rotation (0-3 oder null), panel ("spiel/panel"),
light (true/false: Light-Modus für schwache Geräte), theme (Farbschema, siehe themes.py). Fehlt ein Feld, gilt der Wert aus config.json
(tablet_modes/tablet_mode, tablet_rotation, tablet_lights, tablet_theme).

Die Kennung (Seriennummer) schickt der Hub per ADB an den Launcher; der setzt sie als Cookie "deckdev",
damit der Hub auch WLAN-Verbindungen dem Gerät zuordnen kann. Sie ist nur eine Bezeichnung, keine
Berechtigung: Zugang gibt weiterhin allein das Kopplungsgeheimnis.
"""
import json
import logging
import os
import re
import tempfile
from pathlib import Path

from . import themes

log = logging.getLogger("bridge")

ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


def valid_id(dev):
    return isinstance(dev, str) and ID_RE.fullmatch(dev) is not None


class Devices:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {}
        self.broken = False   # Datei unlesbar: nicht überschreiben (handgepflegte Felder blieben sonst weg)
        self.load()

    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError) as e:
            log.error("%s nicht lesbar (%s) - Geräteliste leer und schreibgeschützt, bis die Datei repariert "
                      "und der Hub neu gestartet ist", self.path.name, e)
            self.broken = True
            raw = {}
        devs = raw.get("devices") if isinstance(raw, dict) else None
        self.data = {k: v for k, v in (devs or {}).items() if valid_id(k) and isinstance(v, dict)}
        self._fix_main()

    def save(self):
        if self.broken:
            log.warning("%s ist fehlerhaft - Änderung nicht gespeichert", self.path.name)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".devices-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"devices": self.data}, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _fix_main(self):
        """Genau ein Hauptgerät, sobald es Geräte gibt (sonst das erste eingetragene)."""
        mains = [k for k, v in self.data.items() if v.get("main") is True]
        keep = mains[0] if mains else next(iter(self.data), None)
        for k, v in self.data.items():
            v["main"] = k == keep

    # ---------------------------------------------------------------- Abfragen

    def get(self, dev):
        return self.data.get(dev) if valid_id(dev) else None

    def main(self):
        return next((k for k, v in self.data.items() if v.get("main")), None)

    def name(self, dev):
        d = self.get(dev) or {}
        n = d.get("name")
        return n if isinstance(n, str) and n.strip() else (d.get("model") or dev or "Tablet")

    def multi(self):
        return len(self.data) > 1

    def mode(self, dev, default):
        m = (self.get(dev) or {}).get("mode")
        if m is None:
            return default
        if m in ("home", "companion"):
            return m
        log.error("devices.json %s: mode=%r ungültig (home oder companion) - nehme %s", dev, m, default)
        return default

    def rotation(self, dev, default):
        d = self.get(dev) or {}
        if "rotation" not in d:
            return default
        r = d["rotation"]
        if r is None or (type(r) is int and 0 <= r <= 3):
            return r
        log.error("devices.json %s: rotation=%r ungültig (0-3 oder null) - nehme %r", dev, r, default)
        return default

    def panel(self, dev):
        p = (self.get(dev) or {}).get("panel")
        return p if isinstance(p, str) and p else None

    def light(self, dev, default=False):
        d = self.get(dev) or {}
        if "light" not in d:
            return default
        if isinstance(d["light"], bool):
            return d["light"]
        log.error("devices.json %s: light=%r ungültig (true oder false) - nehme %r", dev, d["light"], default)
        return default

    def theme(self, dev, default):
        d = self.get(dev) or {}
        if "theme" not in d:
            return default
        if themes.valid(d["theme"]):
            return d["theme"]
        log.error("devices.json %s: theme=%r ungültig - nehme %r", dev, d["theme"], default)
        return default

    def tiles(self, dev):
        """Kachel-IDs, die dieses Gerät zeigt (Reihenfolge aus launcher.json), oder None = alle."""
        t = (self.get(dev) or {}).get("tiles")
        if t is None:
            return None
        if isinstance(t, list) and all(isinstance(x, str) for x in t):
            return t
        log.error("devices.json %s: tiles=%r ungültig (Liste von Kachel-IDs) - zeige alle", dev, t)
        return None

    # ---------------------------------------------------------------- Ändern

    def see(self, dev, model=None):
        """Gerät beim Koppeln per USB eintragen (einmalig). True, wenn neu."""
        if not valid_id(dev):
            return False
        if dev in self.data:
            if model and not self.data[dev].get("model"):
                self.data[dev]["model"] = model
                self.save()
            return False
        self.data[dev] = {"name": model or dev, "model": model or "", "main": not self.data}
        self.save()
        log.info("Neues Gerät %s (%s)%s", dev, model or "?", " - Hauptgerät" if self.data[dev]["main"] else "")
        return True

    def set_light(self, dev, on):
        """Light-Modus eines bekannten Geräts setzen (Editor, Hinweis am Tablet). True bei Erfolg."""
        if dev not in self.data or not isinstance(on, bool) or self.broken:
            return False
        if self.data[dev].get("light") is not on:
            self.data[dev]["light"] = on
            self.save()
            log.info("Light-Modus %s: %s", self.name(dev), "an" if on else "aus")
        return True

    def set_theme(self, dev, theme):
        """Farbschema eines bekannten Geräts setzen (Editor). True bei Erfolg."""
        if dev not in self.data or not themes.valid(theme) or self.broken:
            return False
        if self.data[dev].get("theme") != theme:
            self.data[dev]["theme"] = dict(theme)
            self.save()
            log.info("Farbschema %s: %s/%s", self.name(dev), theme["surface"], theme["accent"])
        return True

    def set_main(self, dev):
        if dev not in self.data:
            return False
        for k, v in self.data.items():
            v["main"] = k == dev
        self.save()
        log.info("Hauptgerät: %s (%s)", dev, self.name(dev))
        return True
