"""Spielerkennung: laufendes Spiel aus der Prozessliste (games.json, Feld exe) bzw. - wenn dort nichts passt -
aus der Bibliothek aller Launcher (library.py, Pfad des Programms liegt im Spielordner).

Bei einem Wechsel meldet der Hub allen Tablet-Seiten {"t":"game", "game": {...} | null}. Das Panel zeigt
dann das erste (bzw. zuletzt gewählte) Panel des Spiels; ein Wechsel von Hand bleibt bis zum nächsten
Spielwechsel bestehen. Optional (config "game_panel", Standard an) schaltet der Launcher beim Spielstart
auf die Kachel "panel" (nur bei Spielen mit Panels).
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


async def watch_games(bridge, cfg, interval=3):
    switch = cfg.get("game_panel", True)
    loop = asyncio.get_running_loop()
    scan_task, next_scan = None, 0.0
    checked = set()     # Bibliotheksspiele, deren Karten schon geprüft wurden/werden
    failed = {}         # gid -> Zeitpunkt des letzten Map-Genie-Fehlers
    bg = set()
    misses = 0

    def spawn(coro):
        t = asyncio.ensure_future(coro)
        bg.add(t)
        t.add_done_callback(bg.discard)

    async def rescan():
        try:
            def work():
                lib = library.scan_library()
                old = bridge.profiles._lib
                bridge.profiles.set_library(lib)
                new = bridge.profiles._lib
                return len(lib), (old[1], old[2].keys()) != (new[1], new[2].keys())
            n, changed = await loop.run_in_executor(None, work)
            log.info("Bibliothek: %d Spiele", n)
            if changed:
                gid = bridge.game
                await bridge.broadcast({"t": "profiles", "changed": [],
                                        "game": bridge.profiles.summary(gid) if gid else None})
                await bridge.ctl_send(bridge.maps_msg())
        except Exception as e:  # noqa: BLE001
            log.error("Bibliothek: %s", e)

    async def find_maps(gid, name):
        try:
            url = await loop.run_in_executor(None, mapgenie.lookup, name)
        except Exception as e:  # noqa: BLE001
            log.info("Map Genie (%s): %s", gid, e.__class__.__name__)
            failed[gid] = time.monotonic()
            checked.discard(gid)   # frühestens nach RETRY_S erneut versuchen
            return
        failed.pop(gid, None)
        if url:
            bridge.profiles.set_extra_maps(gid, [{"name": "Map Genie", "url": url}])
            log.info("Map Genie für %s gefunden", gid)
            await bridge.ctl_send(bridge.maps_msg())

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
            if (gid and gid not in checked and bridge.profiles.is_extra(gid)
                    and time.monotonic() - failed.get(gid, -RETRY_S) >= RETRY_S):
                checked.add(gid)
                spawn(find_maps(gid, bridge.profiles.game(gid)["name"]))
        except Exception as e:  # noqa: BLE001
            log.error("Spielerkennung: %s", e)
        await asyncio.sleep(interval)
