"""Zustand des Tablets fürs Log: Speicher, Laufzeit, Neustarts und Android-Ereignisse (DropBox).

Hilft bei Fehlern, die man erst hinterher bemerkt: spacedesk startet nicht (Tablet überlastet, kein Speicher),
Tablet geht beim Herunterfahren des PCs nicht aus (startet am USB-Strom neu). Der Hub ruft check() für jedes
per USB verbundene Tablet etwa alle 5 Minuten auf; geloggt wird nur, was neu ist:
- neue DropBox-Einträge (Neustart, Absturz, hängende App) mit ihrer Uhrzeit am Tablet
- ein Neustart seit der letzten Prüfung (Laufzeit kleiner geworden)
- wenig freier Speicher (Warnung), sonst alle 30 Minuten eine Statuszeile
Nur lesende adb-Befehle, keine Inhalte der Berichte (die können Daten aus Apps enthalten).
"""
import logging
import re
import time

log = logging.getLogger("bridge")

INTERVAL_S = 300          # Prüfabstand je Tablet
STATUS_S = 1800           # Statuszeile ohne Auffälligkeiten
LOW_MEM_KB = 250 * 1024   # darunter wird es auf dem 2-GB-Tablet eng
# DropBox-Arten, die bei Hängern/Neustarts interessieren (keine App-Daten, nur Art und Uhrzeit)
TAGS = ("SYSTEM_BOOT", "SYSTEM_RESTART", "SYSTEM_LAST_KMSG", "SYSTEM_TOMBSTONE", "system_server_crash",
        "system_server_watchdog", "system_server_pre_watchdog", "system_server_anr", "system_app_anr", "system_app_crash",
        "system_app_native_crash", "data_app_anr", "data_app_crash", "data_app_native_crash",
        "SYSTEM_FSCK", "SYSTEM_RECOVERY_LOG")
DROPBOX_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (\S+) ")

COMMAND = ("cat /proc/uptime; grep -E '^(MemAvailable|SwapFree|SwapTotal):' /proc/meminfo; "
           "dumpsys dropbox 2>/dev/null | grep -E '^[0-9]{4}-'")


def parse(out):
    """Ausgabe von COMMAND -> {"uptime": s, "mem_kb": .., "swap_free_kb": .., "events": [(zeit, art), ...]}."""
    res = {"uptime": None, "mem_kb": None, "swap_free_kb": None, "swap_total_kb": None, "events": []}
    for line in out.splitlines():
        line = line.strip()
        if res["uptime"] is None and re.fullmatch(r"\d+(\.\d+)? \d+(\.\d+)?", line):
            res["uptime"] = float(line.split()[0])
            continue
        m = re.match(r"^(MemAvailable|SwapFree|SwapTotal):\s+(\d+) kB", line)
        if m:
            key = {"MemAvailable": "mem_kb", "SwapFree": "swap_free_kb", "SwapTotal": "swap_total_kb"}[m.group(1)]
            res[key] = int(m.group(2))
            continue
        m = DROPBOX_LINE.match(line)
        if m and m.group(2) in TAGS:
            res["events"].append((m.group(1), m.group(2)))
    return res


def _fmt_uptime(s):
    s = int(s)
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


class TabletHealth:
    """Merkt sich je Tablet den letzten Stand und meldet nur Neues."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state = {}       # serial -> {"next", "uptime", "seen", "status_at"}

    def due(self, serial):
        st = self.state.get(serial)
        return st is None or self.clock() >= st["next"]

    def forget(self, serial):
        """Tablet abgesteckt: beim nächsten Anstecken wieder mit einer Statuszeile beginnen."""
        self.state.pop(serial, None)

    async def check(self, run, adb, serial):
        """Einmal prüfen (run = async (cmd...) -> (rc, out), wie in adb_watch). Gibt die Logzeilen zurück."""
        now = self.clock()
        st = self.state.setdefault(serial, {"next": 0, "uptime": None, "seen": None, "status_at": None})
        st["next"] = now + INTERVAL_S
        rc, out = await run(adb, "-s", serial, "shell", COMMAND)
        if rc != 0:
            return []
        lines = self.evaluate(serial, parse(out), now)
        for level, text in lines:
            log.log(level, text)
        return lines

    def evaluate(self, serial, p, now):
        """Neue Logzeilen [(level, text)] aus einem geparsten Stand (testbar ohne adb)."""
        st = self.state.setdefault(serial, {"next": 0, "uptime": None, "seen": None, "status_at": None})
        out = []
        first = st["seen"] is None
        if first:
            # Beim ersten Mal die jüngsten Neustarts nennen: zeigt z. B., ob das Tablet nach dem letzten
            # Herunterfahren des PCs von selbst wieder hochgefahren ist
            boots = [t for t, tag in p["events"] if tag == "SYSTEM_BOOT"][-3:]
            if boots:
                out.append((logging.INFO, f"Tablet {serial}: letzte Starts laut Android: {', '.join(boots)}"))
        else:
            new = [(t, tag) for t, tag in p["events"] if t > st["seen"]]
            for t, tag in new[-20:]:
                lvl = logging.WARNING if tag != "SYSTEM_BOOT" else logging.INFO
                out.append((lvl, f"Tablet {serial}: Android-Ereignis {tag} um {t}"))
            if len(new) > 20:
                out.append((logging.WARNING, f"Tablet {serial}: {len(new) - 20} weitere Android-Ereignisse"))
        if p["events"]:
            st["seen"] = max(t for t, _ in p["events"])
        elif first:
            st["seen"] = ""
        if p["uptime"] is not None and st["uptime"] is not None and p["uptime"] + 60 < st["uptime"]:
            out.append((logging.WARNING, f"Tablet {serial}: neu gestartet (läuft seit {_fmt_uptime(p['uptime'])})"))
        if p["uptime"] is not None:
            st["uptime"] = p["uptime"]
        mem = p["mem_kb"]
        status = (f"Tablet {serial}: Zustand - läuft seit {_fmt_uptime(p['uptime'] or 0)}, "
                  f"frei {mem // 1024 if mem is not None else '?'} MB, "
                  f"Swap frei {p['swap_free_kb'] // 1024 if p['swap_free_kb'] is not None else '?'} MB")
        if mem is not None and mem < LOW_MEM_KB:
            out.append((logging.WARNING, status + " - Speicher knapp"))
            st["status_at"] = now
        elif first or st["status_at"] is None or now - st["status_at"] >= STATUS_S:
            out.append((logging.INFO, status))
            st["status_at"] = now
        return out
