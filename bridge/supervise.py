"""Wächter für den Autostart: startet die Bridge und startet sie nach einem Absturz neu.

Aufruf (aus der geplanten Aufgabe): pythonw -m bridge.supervise [config.json]
- Exit-Code 0 (z. B. "Beenden" im Taskleisten-Menü): Wächter beendet sich ebenfalls.
- Exit-Code 75 (Port belegt: Bridge läuft schon) oder 78 (Konfigurationsfehler): kein Neustart, Ende.
- Anderer Exit-Code / Absturz: Neustart nach 5 s, bei schnellen Folgeabstürzen wachsende Pause bis
  5 min. Lief die Bridge mindestens 10 min stabil, beginnt die Pause wieder bei 5 s.
- Die Bridge hängt in einem Job-Objekt mit KILL_ON_JOB_CLOSE: Wird der Wächter beendet (z. B. die
  geplante Aufgabe gestoppt), endet die Bridge mit - es bleibt keine verwaiste Bridge zurück.
Protokoll: supervise.log (eigene Datei - zwei Prozesse dürfen nicht dieselbe rotierende Datei schreiben).
- Sitzungsende: Der Wächter legt das Tablet beim Herunterfahren ebenfalls schlafen (bridge/session.py).
  Die Bridge wurde am 13.11. beim Herunterfahren sofort beendet (Code 0x40010004), bevor ihr Befehl
  durch war; der Wächter lebte länger. Doppelte Befehle (Bridge und Wächter) schaden nicht.
"""
import ctypes
import logging
import subprocess
import sys
import time
from ctypes import wintypes
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CREATE_NO_WINDOW = 0x08000000
MIN_WAIT, MAX_WAIT, STABLE_S = 5, 300, 600
NO_RESTART = {0: "regulär beendet", 75: "läuft schon (Port belegt)", 78: "Konfigurationsfehler (siehe bridge.log)"}
SYSTEM_KILL = 0x40010004   # DBG_TERMINATE_PROCESS: Windows hat beim Abmelden/Herunterfahren hart beendet
SUPERVISED_ENV = "TABLETDECK_SUPERVISED"   # Bridge weiß damit: adb-Befehle beim Sitzungsende macht der Wächter


class _BasicLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps",
                                               "ReadBytes", "WriteBytes", "OtherBytes")]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def kill_on_close_job():
    """Job-Objekt, dessen Prozesse beim Schließen des letzten Handles (= Ende des Wächters) beendet werden."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _ExtendedLimit()
    # KILL_ON_JOB_CLOSE (0x2000); SILENT_BREAKAWAY_OK (0x1000): von der Bridge gestartete Prozesse
    # (z. B. der adb-Server) landen nicht im Job und laufen nach dem Ende weiter
    info.BasicLimitInformation.LimitFlags = 0x2000 | 0x1000
    if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return k32, job


def config_port():
    import json
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "config.json"
    try:
        return int(json.loads(cfg.read_text(encoding="utf-8")).get("port", 8765))
    except (OSError, ValueError, AttributeError, TypeError):
        return 8765


def bridge_answers(port=None):
    """Antwortet auf dem Port wirklich die Bridge? (Erkennung am CSP-Header der Bridge)"""
    import urllib.request
    port = port or config_port()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # System-Proxy umgehen
    try:
        with opener.open(f"http://127.0.0.1:{port}/", timeout=3) as r:
            return "frame-src 'none'" in (r.headers.get("Content-Security-Policy") or "")
    except OSError:
        return False


def find_adb():
    import json
    import shutil
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "config.json"
    try:
        own = json.loads(cfg.read_text(encoding="utf-8")).get("adb")
    except (OSError, ValueError, AttributeError):
        own = None
    for cand in (own, ROOT / "tools/platform-tools/adb.exe", shutil.which("adb")):
        if cand and Path(cand).is_file():
            return str(cand)
    return None


def main():
    log = logging.getLogger("supervise")
    log.setLevel(logging.INFO)
    h = RotatingFileHandler(ROOT / "supervise.log", maxBytes=200_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(h)
    slog = logging.getLogger("session")   # Meldungen des Sitzungsende-Wächters ebenfalls in supervise.log
    slog.setLevel(logging.INFO)
    slog.addHandler(h)
    ending = {"on": False}   # Windows fährt herunter / meldet ab: Bridge nicht mehr neu starten

    def on_end(flag):
        ending["on"] = flag
    try:
        from .session import watch_session_end
        watch_session_end(find_adb(), on_end=on_end)
    except Exception as e:  # noqa: BLE001
        log.warning("Sitzungsende-Wächter nicht gestartet: %s", e)
    import atexit
    import os
    from .session import close_shells
    atexit.register(close_shells)   # offene adb-Shells nicht verwaist zurücklassen
    env = dict(os.environ, **{SUPERVISED_ENV: "1"})
    try:
        k32, job = kill_on_close_job()
    except OSError as e:
        log.warning("Job-Objekt nicht verfügbar (%s) - Bridge überlebt ggf. das Ende des Wächters", e)
        k32 = job = None
    # Bridge mit demselben Interpreter (pythonw) starten, ohne Fenster; sie loggt selbst nach bridge.log
    cmd = [sys.executable, "-m", "bridge", *sys.argv[1:]]
    wait = MIN_WAIT
    while True:
        started = time.monotonic()
        log.info("starte Bridge: %s", " ".join(cmd))
        try:
            p = subprocess.Popen(cmd, cwd=ROOT, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            if job and not k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(p._handle))):
                log.warning("Bridge nicht im Job-Objekt: %s", ctypes.WinError(ctypes.get_last_error()))
            rc = p.wait()
        except OSError as e:
            log.error("Bridge nicht startbar: %s", e)
            rc = -1
        if rc == 75 and not bridge_answers():
            log.warning("Port belegt, aber dort antwortet keine Bridge - fremdes Programm? Neustart mit Pause")
            rc = -75
        if rc in NO_RESTART:
            log.info("Bridge %s (Code %d) - Wächter endet", NO_RESTART[rc], rc)
            return
        if ending["on"] or rc == SYSTEM_KILL:
            log.info("Bridge von Windows beendet (Herunterfahren/Abmelden, Code %#x) - kein Neustart", rc & 0xFFFFFFFF)
            deadline = time.monotonic() + 300
            # Herunterfahren läuft: auf das Ende warten (Fenster-Thread arbeitet weiter); höchstens 5 min,
            # falls "Apps verhindern das Herunterfahren" ohne Entscheidung stehen bleibt
            while ending["on"] and time.monotonic() < deadline:
                time.sleep(1)
            ending["on"] = False
            if rc == SYSTEM_KILL and not ending["on"]:
                time.sleep(2)        # abgebrochen: Bridge wieder starten
            continue
        if time.monotonic() - started >= STABLE_S:
            wait = MIN_WAIT
        log.warning("Bridge beendet mit Code %s - Neustart in %d s", rc, wait)
        time.sleep(wait)
        wait = min(MAX_WAIT, wait * 2)


if __name__ == "__main__":
    main()
