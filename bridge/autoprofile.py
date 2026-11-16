"""Automatischer Moduswechsel am Tablet nach laufenden Programmen.

config.json:
  "auto_modes": [ {"process": "StarCitizen.exe", "mode": "panel"} ],   erste passende Regel gewinnt
  "auto_default": "touchpad"                                           wenn keine Regel passt (optional)

Gewechselt wird nur, wenn sich das *Ergebnis* der Regeln ändert (Programm startet/endet). Ein Wechsel von
Hand am Tablet bleibt also bestehen, bis sich an den laufenden Programmen etwas Relevantes ändert.
Ein Launcher, der sich später verbindet, bekommt den aktuellen Wunschmodus sofort.
Hinweis: Ein App-Modus (z. B. "screen") startet die App bei jedem Wechsel des Regelergebnisses.
"""
import asyncio
import csv
import io
import logging

log = logging.getLogger("auto")


_cache = {"t": -1e9, "procs": set(), "lock": None}


async def running_processes(max_age=2.0):
    """Prozessnamen (klein). Automatik und Spielerkennung teilen sich eine Abfrage (max. alle 2 s)."""
    if _cache["lock"] is None:
        _cache["lock"] = asyncio.Lock()
    async with _cache["lock"]:
        now = asyncio.get_running_loop().time()
        if now - _cache["t"] < max_age:
            return _cache["procs"]
        _cache["procs"] = await _tasklist()
        _cache["t"] = asyncio.get_running_loop().time()
        return _cache["procs"]


async def _tasklist():
    p = await asyncio.create_subprocess_exec("tasklist", "/fo", "csv", "/nh",
                                             stdout=asyncio.subprocess.PIPE,
                                             stderr=asyncio.subprocess.DEVNULL,
                                             creationflags=0x08000000)  # CREATE_NO_WINDOW
    out, _ = await p.communicate()
    text = out.decode("mbcs", errors="replace")
    return {row[0].lower() for row in csv.reader(io.StringIO(text)) if row}


def decide(rules, default, procs):
    for r in rules:
        if str(r.get("process", "")).lower() in procs:
            return r.get("mode"), r.get("process")
    return default, None


async def auto_modes(bridge, cfg):
    rules = cfg.get("auto_modes") or []
    default = cfg.get("auto_default")
    if not rules:
        return
    last = None
    while True:
        try:
            mode, why = decide(rules, default, await running_processes())
            if mode != bridge.auto_mode:
                bridge.auto_mode = mode
                bridge.auto_pending = True   # einmal an den nächsten (neu) verbundenen Launcher
            if mode and mode != last and bridge.ctl_clients:
                log.info("Automatik: %s -> Modus '%s'", why or "keine Regel", mode)
                await bridge.ctl_send({"t": "mode", "mode": mode})
            if bridge.ctl_clients:   # ohne Launcher nicht als "erledigt" merken
                last = mode
                bridge.auto_pending = False
        except Exception as e:  # noqa: BLE001
            log.error("Automatik: %s", e)
        await asyncio.sleep(3)
