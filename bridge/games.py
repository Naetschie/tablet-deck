"""Spielerkennung: laufendes Spiel aus der Prozessliste (games.json, Feld exe) bzw. - wenn dort nichts passt -
aus der Bibliothek aller Launcher (library.py, Pfad des Programms liegt im Spielordner).

Bei einem Wechsel meldet der Hub allen Tablet-Seiten {"t":"game", "game": {...} | null}. Das Panel zeigt
dann das erste (bzw. zuletzt gewählte) Panel des Spiels; ein Wechsel von Hand bleibt bis zum nächsten
Spielwechsel bestehen. Optional (config "game_panel", Standard an) schaltet der Launcher beim Spielstart
auf die Kachel "panel" (nur bei Spielen mit Panels).

Karten-Kachel: Bibliotheksspiele ohne Eintrag in games.json bekommen ihre Karten von Map Genie (MapFinder) -
alle installierten, nicht erst das laufende Spiel; Ergebnis dauerhaft in mapgenie_cache.json.
"""
import asyncio
import logging
import time

from . import library, mapgenie
from .autoprofile import running_processes

log = logging.getLogger("games")
RESCAN_S = 600
RETRY_S = 1800      # Map-Genie-Fehler: frühestens nach 30 min erneut
NONE_RUNS = 2       # Durchläufe ohne Treffer, bevor "kein Spiel" übernommen wird
MAP_PAUSE_S = 2     # Pause zwischen zwei Map-Genie-Anfragen


class MapFinder:
    """Karten (Map Genie) für Bibliotheksspiele ohne games.json-Eintrag. Bekanntes kommt sofort aus dem
    Zwischenspeicher (prefill, ohne Netz), Unbekanntes wird im Hintergrund nachgeschlagen - eins nach dem
    anderen mit Pause, das laufende Spiel zuerst. Nach einem Netzfehler ruht die Suche RETRY_S lang."""

    def __init__(self, bridge, lookup=None, cached=None, pause=MAP_PAUSE_S, clock=time.monotonic):
        self.bridge = bridge
        self.lookup = lookup or mapgenie.lookup
        self.cached = cached or mapgenie.cached
        self.pause, self.clock = pause, clock
        self.checked = set()   # geprüft oder in der Warteschlange
        self.queue = []
        self.task = None
        self.backoff = 0.0

    def prefill(self):
        """Im Hilfs-Thread nach set_library: ({gid: Karten} aus dem Zwischenspeicher, [unbekannte gids])."""
        p = self.bridge.profiles
        known, unknown = {}, []
        data = mapgenie.load() if self.cached is mapgenie.cached else None   # Datei nur einmal lesen
        for gid, e in p._lib[2].items():
            if not p.is_extra(gid):
                continue
            hit = self.cached(e["name"], data=data) if data is not None else self.cached(e["name"])
            if hit is None:
                unknown.append(gid)
            else:
                known[gid] = hit
        return known, unknown

    def apply(self, known):
        """Karten aus prefill übernehmen; True, wenn sich etwas geändert hat."""
        changed = False
        for gid, maps in known.items():
            changed = self.bridge.profiles.set_extra_maps(gid, maps) or changed
        return changed

    def forget(self, gids):
        """Abgelaufene bzw. unbekannte Spiele wieder zum Nachschlagen freigeben (nicht die wartenden)."""
        self.checked -= set(gids) - set(self.queue)

    def want(self, gid, front=False):
        if self.clock() < self.backoff:
            return
        if gid in self.queue:
            if front and self.queue[0] != gid:   # laufendes Spiel nach vorn holen
                self.queue.remove(gid)
                self.queue.insert(0, gid)
            return
        if gid in self.checked:
            return
        self.checked.add(gid)
        if front:
            self.queue.insert(0, gid)
        else:
            self.queue.append(gid)
        if self.task is None or self.task.done():
            self.task = asyncio.ensure_future(self.run())

    async def run(self):
        loop = asyncio.get_running_loop()
        p = self.bridge.profiles
        while self.queue:
            gid = self.queue.pop(0)
            g = p.game(gid)
            if not g or not p.is_extra(gid):
                continue
            try:
                maps = await loop.run_in_executor(None, self.lookup, g["name"])
            except Exception as e:  # noqa: BLE001
                log.info("Map Genie (%s): %s - nächster Versuch in %d min", gid, e.__class__.__name__, RETRY_S // 60)
                self.backoff = self.clock() + RETRY_S
                for rest in [gid] + self.queue:   # Netz weg: den Rest nicht einzeln scheitern lassen
                    self.checked.discard(rest)
                self.queue.clear()
                return
            try:
                if maps and p.set_extra_maps(gid, maps):
                    log.info("Map Genie für %s: %d Karte(n)", gid, len(maps))
                    await self.bridge.ctl_send(self.bridge.maps_msg())
            except Exception as e:  # noqa: BLE001 - die übrigen Spiele trotzdem nachschlagen
                log.error("Map Genie (%s): %s", gid, e)
            if self.queue:
                await asyncio.sleep(self.pause)


async def watch_games(bridge, cfg, interval=3):
    switch = cfg.get("game_panel", True)
    loop = asyncio.get_running_loop()
    scan_task, next_scan = None, 0.0
    finder = MapFinder(bridge)
    misses = 0

    async def rescan():
        try:
            def work():
                lib = library.scan_library()
                old = bridge.profiles._lib
                bridge.profiles.set_library(lib)
                new = bridge.profiles._lib
                return len(lib), (old[1], old[2].keys()) != (new[1], new[2].keys()), finder.prefill()
            n, changed, (known, unknown) = await loop.run_in_executor(None, work)
            log.info("Bibliothek: %d Spiele", n)
            maps_changed = finder.apply(known)
            if changed:
                gid = bridge.game
                await bridge.broadcast({"t": "profiles", "changed": [],
                                        "game": bridge.profiles.summary(gid) if gid else None})
            if changed or maps_changed:
                await bridge.ctl_send(bridge.maps_msg())
            finder.forget(unknown)   # Zwischenspeicher abgelaufen: bei einem lange laufenden Hub neu prüfen
            for gid in unknown:
                finder.want(gid)
        except Exception as e:  # noqa: BLE001
            log.error("Bibliothek: %s", e)

    while True:
        try:
            if time.monotonic() >= next_scan and (scan_task is None or scan_task.done()):
                next_scan = time.monotonic() + RESCAN_S
                scan_task = asyncio.ensure_future(rescan())
            procs = await running_processes()
            gid = bridge.profiles.detect(procs)
            if gid is None and bridge.profiles.library:
                paths = await loop.run_in_executor(None, library.running_game_paths)
                gid = bridge.profiles.match_library(paths)
            misses = 0 if gid else misses + 1
            if gid is None and bridge.game is not None and misses < NONE_RUNS:
                gid = bridge.game      # Entprellung: "kein Spiel" erst nach zwei Durchläufen
            if gid != bridge.game:
                bridge.game = gid
                info = bridge.profiles.summary(gid) if gid else None
                log.info("Spiel: %s", info["name"] if info else "keins")
                await bridge.broadcast({"t": "game", "game": info})
                await bridge.ctl_send(bridge.maps_msg())   # Karten-Kachel: Karte des Spiels
                try:
                    bridge.stats.set_game(gid, procs)      # PresentMon-Ziel (läuft im Hintergrund)
                except Exception as e:  # noqa: BLE001 - darf die Spielerkennung nicht stören
                    log.warning("PresentMon-Ziel: %s", e.__class__.__name__)
                if gid and switch and info["panels"] and bridge.ctl_clients and any(
                        t.get("id") == "panel" for t in bridge.tiles):
                    await bridge.ctl_send({"t": "mode", "mode": "panel"})
            if gid and bridge.profiles.is_extra(gid):
                finder.want(gid, front=True)   # laufendes Spiel vor allen anderen
        except Exception as e:  # noqa: BLE001
            log.error("Spielerkennung: %s", e)
        await asyncio.sleep(interval)
