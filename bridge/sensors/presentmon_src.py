"""FPS und Frametime des laufenden Spiels über die Konsolenfassung von Intel PresentMon (Unterprozess).

Aufruf nach README-ConsoleApplication.md von PresentMon 2.x (github.com/GameTechDev/PresentMon):
  PresentMon.exe --process_id <pid> | --process_name <exe>  --output_stdout --no_console_stats
                 --session_name <Name> --stop_existing_session [--terminate_on_proc_exit]
Beenden: zweiter Aufruf mit --session_name <Name> --terminate_existing_session (hält die ETW-Sitzung an,
der erste Prozess endet dann von selbst); erst danach terminate/kill.

Die CSV-Spalten unterscheiden sich je nach Fassung, deshalb richtet sich der Parser nach der Kopfzeile:
  2.x:           FrameTime bzw. MsBetweenAppStart bzw. (Ms)CPUBusy + (Ms)CPUWait; DisplayedTime („NA“ = nicht angezeigt)
  1.x/--v1_metrics: msBetweenPresents; msBetweenDisplayChange, Dropped
PresentMon braucht Adminrechte oder die Gruppe „Leistungsprotokollbenutzer“.
"""
import csv
import ctypes
import logging
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from . import Adapter, Raw, is_admin

log = logging.getLogger("sensors")

SESSION = "TabletDeckSensors"
EXE_NAME = re.compile(r"\w[\w .()+&'\-]{0,119}\.exe", re.IGNORECASE)   # nicht mit "-" beginnend
STALE = 2.0             # s ohne neue Frames: keine Werte mehr (Spiel pausiert/minimiert/beendet)
RETRY = 30.0            # s bis zum nächsten Startversuch, wenn PresentMon unerwartet endet

# Kandidaten für die Frametime, in dieser Reihenfolge; mehrere Spalten werden addiert
FRAME_COLUMNS = (("frametime",), ("msbetweenappstart",), ("mscpubusy", "mscpuwait"), ("cpubusy", "cpuwait"),
                 ("msbetweenpresents",))


# --- CSV (reine Funktionen) ---

def _split(line):
    try:
        return next(csv.reader([line]))
    except (csv.Error, StopIteration):
        return None


def parse_header(line):
    """Kopfzeile -> Spaltenplan {n, frame: [Index…], displayed, dropped} oder None, wenn es keine Kopfzeile ist."""
    cells = _split(line.strip().lstrip("﻿"))
    if not cells:
        return None
    idx = {c.strip().lower(): i for i, c in enumerate(cells)}
    if "application" not in idx or "processid" not in idx:
        return None
    frame = next(([idx[c] for c in cand] for cand in FRAME_COLUMNS if all(c in idx for c in cand)), None)
    displayed = idx.get("displayedtime", idx.get("msbetweendisplaychange"))
    if frame is None and displayed is None:
        return None
    return {"n": len(cells), "frame": frame, "displayed": displayed, "dropped": idx.get("dropped")}


def _ms(cell):
    try:
        v = float(cell)
    except ValueError:      # „NA“
        return None
    return v if 0 < v < 60_000 else None


def parse_row(cols, line):
    """Datenzeile -> (frametime_ms | None, angezeigt_ms | None); None bei fremden/kaputten Zeilen."""
    cells = _split(line.strip())
    if not cells or len(cells) != cols["n"]:
        return None
    frame = None
    if cols["frame"] is not None:
        try:        # bei CPUBusy + CPUWait darf ein Summand 0 sein
            total = sum(float(cells[i]) for i in cols["frame"])
            frame = total if 0 < total < 60_000 else None
        except ValueError:
            frame = None
    displayed = _ms(cells[cols["displayed"]]) if cols["displayed"] is not None else None
    if cols["dropped"] is not None and cells[cols["dropped"]].strip() == "1":
        displayed = None
    if frame is None and displayed is None:
        return None
    return frame, displayed


class FrameStats:
    """Gleitender Mittelwert über das letzte ~1 s Spielzeit (gemessen an den Frame-Dauern selbst)."""

    def __init__(self, window_ms=1000.0, clock=time.monotonic):
        self.window = window_ms
        self.clock = clock
        self.frames = deque()       # (Dauer für das Fenster, frametime, angezeigt)
        self.total = 0.0
        self.last = None
        self.lock = threading.Lock()

    def add(self, frame, displayed):
        span = frame if frame is not None else displayed
        with self.lock:
            self.frames.append((span, frame, displayed))
            self.total += span
            while len(self.frames) > 1 and self.total - self.frames[0][0] >= self.window:
                self.total -= self.frames.popleft()[0]
            self.last = self.clock()

    def values(self):
        """(fps_angezeigt | None, frametime_ms | None)"""
        with self.lock:
            if self.last is None or self.clock() - self.last > STALE:
                return None, None
            ft = [f for _, f, _ in self.frames if f is not None]
            dp = [d for _, _, d in self.frames if d is not None]
        fps = 1000.0 * len(dp) / sum(dp) if dp else None
        return fps, (sum(ft) / len(ft) if ft else None)


# --- Unterprozess ---

def clean_target(msg):
    """Prüft die Angabe aus POST /target. Ergebnis: ("pid", n) | ("exe", name) | None (kein Ziel).
    ValueError bei unbrauchbaren Angaben - der exe-Name landet auf einer Befehlszeile."""
    if not isinstance(msg, dict):
        raise ValueError("Objekt erwartet")
    pid, exe = msg.get("pid"), msg.get("exe")
    if pid is not None:
        if isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid < 2 ** 32:
            raise ValueError("pid ungültig")
        return ("pid", pid)
    if exe is not None:
        if not isinstance(exe, str) or not EXE_NAME.fullmatch(exe):
            raise ValueError("exe ungültig (nur Dateiname, z. B. Spiel.exe)")
        return ("exe", exe)
    return None


def _kill_on_close_job():
    """Job-Objekt, das seine Prozesse beendet, sobald sensord endet - auch bei hartem Abbruch (Aufgabe
    gestoppt). Sonst liefe PresentMon samt ETW-Sitzung ohne uns weiter."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32)]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k.CreateJobObjectW.restype = ctypes.c_void_p
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    job = k.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = Extended()
    info.Basic.LimitFlags = 0x2000      # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):   # 9 = ExtendedLimitInformation
        raise ctypes.WinError(ctypes.get_last_error())
    return k, job


class PresentMonSource(Adapter):
    name = "presentmon"

    def __init__(self, exe, popen=subprocess.Popen, run=subprocess.run, clock=time.monotonic):
        self.exe = Path(exe)
        self._popen = popen
        self._run = run
        self.clock = clock
        self.lock = threading.Lock()
        self.wanted = None          # vom Hub gesetztes Ziel
        self.running = None         # Ziel des laufenden Unterprozesses
        self.proc = None
        self.stats = None
        self.retry_at = 0.0
        self.status = "kein Ziel"
        self._job = None

    # Aufruf aus dem HTTP-Thread; gestartet/beendet wird nur im Abtast-Thread (read)
    def set_target(self, target):
        with self.lock:
            if target != self.wanted:
                self.wanted = target
                self.retry_at = 0.0

    def start(self):
        self.status = "kein Ziel" if self.exe.is_file() else "nicht installiert"

    def close(self):
        self._stop()

    def command(self, target):
        kind, value = target
        cmd = [str(self.exe), "--process_id" if kind == "pid" else "--process_name", str(value),
               "--output_stdout", "--no_console_stats", "--session_name", SESSION, "--stop_existing_session"]
        if kind == "pid":
            cmd.append("--terminate_on_proc_exit")
        return cmd

    def read(self):
        with self.lock:
            wanted = self.wanted
        if not self.exe.is_file():
            self._stop()
            self.status = "nicht installiert"
            return []
        if self.proc is not None and self.proc.poll() is not None:      # von selbst beendet
            code = self.proc.returncode
            target = self.running
            self._stop()
            if target and target[0] == "pid" and code == 0:
                with self.lock:                 # Spiel beendet: der Hub setzt beim nächsten Spiel ein neues Ziel
                    if self.wanted == target:
                        self.wanted = wanted = None
            else:
                self.retry_at = self.clock() + RETRY
                self.status = f"beendet (Code {code})" + ("" if is_admin() else
                                                          ", braucht Admin oder Gruppe Leistungsprotokollbenutzer")
                log.warning("PresentMon: %s", self.status)
        if wanted != self.running and self.proc is not None:
            self._stop()
        if wanted is None:
            self.status = "kein Ziel"
            return []
        if self.proc is None:
            if self.clock() < self.retry_at:
                return []
            if not self._start(wanted):
                return []
        fps, ft = self.stats.values()
        out = []
        if fps is not None:
            out.append(Raw(self.name, "fps.displayed", "FPS (angezeigt)", fps, "FPS"))
        if ft is not None:
            out.append(Raw(self.name, "fps.frametime", "Frametime", ft, "ms"))
        return out

    def _start(self, target):
        self.stats = FrameStats(clock=self.clock)
        try:
            self.proc = self._popen(self.command(target), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self.retry_at = self.clock() + RETRY
            self.status = f"Start fehlgeschlagen ({type(e).__name__})"
            log.warning("PresentMon: %s: %s", self.status, e)
            return False
        self.running = target
        self.status = "ok"
        self._assign_job(self.proc)
        threading.Thread(target=self._pump, args=(self.proc, self.stats), name="presentmon", daemon=True).start()
        log.info("PresentMon gestartet (%s %s)", target[0], target[1])
        return True

    def _assign_job(self, proc):
        handle = getattr(proc, "_handle", None)
        if handle is None:
            return
        try:
            if self._job is None:
                self._job = _kill_on_close_job()
            k, job = self._job
            k.AssignProcessToJobObject(job, int(handle))
        except Exception as e:  # noqa: BLE001 - nur ein Sicherheitsnetz; das geordnete Beenden bleibt
            log.warning("PresentMon: Job-Objekt nicht nutzbar (%s)", e)

    @staticmethod
    def _pump(proc, stats):
        """stdout des Unterprozesses lesen, bis er endet (eigener Thread je Unterprozess)."""
        cols = None
        try:
            for line in proc.stdout:
                if cols is None:
                    cols = parse_header(line)
                    continue
                row = parse_row(cols, line)
                if row:
                    stats.add(*row)
        except (OSError, ValueError):       # Pipe beim Beenden geschlossen
            pass

    def _stop(self):
        proc, self.proc, self.running = self.proc, None, None
        if proc is None:
            return
        if proc.poll() is None:
            try:        # geordnet: ETW-Sitzung anhalten, PresentMon endet dann selbst
                self._run([str(self.exe), "--session_name", SESSION, "--terminate_existing_session"],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                proc.wait(timeout=3)
            except (OSError, subprocess.SubprocessError):
                pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            proc.stdout.close()
        except (OSError, AttributeError):
            pass
        log.info("PresentMon beendet")
