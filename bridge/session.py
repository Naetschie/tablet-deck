"""Windows fährt herunter / meldet ab: Tablet aus bzw. dunkel. Der Befehl kommt immer vom PC - das Tablet
schaltet sich nicht selbst ab (abgesteckt/WLAN-Betrieb soll es laufen).

Ein unsichtbares Fenster (kein Message-only-Fenster - die bekommen WM_ENDSESSION nicht) empfängt:
- WM_QUERYENDSESSION: Tablet schlafen legen (umkehrbar - das Herunterfahren kann noch abgebrochen werden).
- WM_ENDSESSION TRUE beim Herunterfahren/Neustart: Tablet ausschalten (svc power shutdown, stayon aus).
  Kappt der PC den USB-Strom, bleibt es aus und startet mit dem PC wieder (off-mode-charge 0). Liefert der
  PC weiter Strom, startet es nach ~60 s neu und wird nach der Zeitsperre dunkel (stayon ist aus).
  Beim Abmelden (ENDSESSION_LOGOFF) nur schlafen.
- WM_ENDSESSION FALSE: abgebrochen -> wieder wecken.
- WM_POWERBROADCAST: Energiesparmodus/Ruhezustand -> schlafen; Aufwecken durch den Benutzer -> wecken
  (nicht bei Wartungs-Aufwachen per Weck-Timer).
Beim nächsten Verbinden weckt die Bridge das Tablet (adb_watch).
"""
import ctypes
import logging
import subprocess
import threading
import time
from ctypes import wintypes

log = logging.getLogger("session")
WM_QUERYENDSESSION, WM_ENDSESSION, WM_POWERBROADCAST = 0x0011, 0x0016, 0x0218
PBT_APMSUSPEND, PBT_APMRESUMESUSPEND = 0x0004, 0x0007   # RESUMESUSPEND: nur wenn ein Mensch weckt
ENDSESSION_LOGOFF = 0x80000000
NO_WINDOW = 0x08000000

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


_known = []   # Seriennummern aus dem letzten Schlafbefehl (bei WM_ENDSESSION kein erneutes "adb devices")
_shells = {}  # Seriennummer -> offene "adb shell" (Popen mit stdin); siehe keep_shells
_shell_lock = threading.Lock()


def keep_shells(adb, interval=10):
    """Hält pro verbundenem Tablet eine "adb shell" offen. Beim Herunterfahren startet Windows keine neuen
    Prozesse mehr (14.11.: "adb devices" scheiterte sofort) - der Befehl geht dann über die offene Shell."""
    def loop():
        while True:
            try:
                serials = _devices(adb, quiet=True)
                if serials is None:   # adb hakt gerade: nichts verwerfen, nächste Runde erneut
                    time.sleep(interval)
                    continue
                with _shell_lock:
                    for s, p in list(_shells.items()):
                        if p.poll() is not None or s not in serials:
                            _close(_shells.pop(s))
                    for s in serials:
                        if s not in _shells:
                            _shells[s] = subprocess.Popen(
                                [adb, "-s", s, "shell"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
                            log.info("Sitzungsende: Shell zu Tablet %s bereit", s)
            except Exception as e:  # noqa: BLE001
                log.warning("Sitzungsende: Shell nicht vorbereitet: %s", e)
            time.sleep(interval)
    threading.Thread(target=loop, name="session-shells", daemon=True).start()


def _close(p):
    try:
        p.stdin.close()
    except OSError:
        pass
    if p.poll() is None:
        p.kill()


def close_shells():
    """Alle offenen Shells beenden (Ende des Wächters - sonst liefen sie verwaist weiter)."""
    with _shell_lock:
        for s in list(_shells):
            _close(_shells.pop(s))


def _via_shell(cmd):
    """Befehl über alle offenen Shells; gibt die erreichten Seriennummern zurück."""
    done = []
    with _shell_lock:
        for s, p in list(_shells.items()):
            try:
                if p.poll() is None:
                    p.stdin.write((cmd + "\n").encode())
                    p.stdin.flush()
                    done.append(s)
            except OSError as e:
                log.warning("Sitzungsende: Shell zu %s nicht nutzbar: %s", s, e)
    return done
_serials = None   # Rückruf der Bridge: per USB eingerichtete Tablets (ohne adb-Abfrage beim Herunterfahren)


def _targets(adb):
    """Tablets für den Befehl: zuerst die der Bridge bekannten, sonst "adb devices"."""
    try:
        known = list(_serials()) if _serials else []
    except Exception:  # noqa: BLE001
        known = []
    found = known or _devices(adb) or []
    if not found:
        log.warning("Sitzungsende: kein Tablet per USB/adb gefunden")
    return found


def sleep_tablets(adb):
    """Alle per adb verbundenen Tablets schlafen legen. Kurz halten: Windows wartet nur wenige Sekunden."""
    via = _via_shell("svc power stayon false; input keyevent KEYCODE_SLEEP")
    for serial in via:
        log.info("Windows wird beendet: Tablet %s schlafen gelegt (offene Shell)", serial)
    if via:
        _known[:] = via
        return
    _known[:] = _targets(adb)
    for serial in _known:
        try:   # ein Aufruf statt zwei
            subprocess.run([adb, "-s", serial, "shell", "svc power stayon false; input keyevent KEYCODE_SLEEP"],
                           capture_output=True, timeout=2, creationflags=NO_WINDOW)
            log.info("Windows wird beendet: Tablet %s schlafen gelegt", serial)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("Sitzungsende: Tablet %s nicht schlafen gelegt: %s", serial, e)


def shutdown_tablets(adb):
    """Tablets ausschalten (geht als Shell-Nutzer). stayon aus, damit ein Neustart am USB-Strom dunkel wird."""
    via = _via_shell("svc power stayon false; svc power shutdown")
    for serial in via:
        log.info("Windows fährt herunter: Tablet %s ausgeschaltet (offene Shell)", serial)
    if via:
        return
    for serial in _known or _targets(adb):
        try:
            subprocess.run([adb, "-s", serial, "shell", "svc power stayon false; svc power shutdown"],
                           capture_output=True, timeout=2, creationflags=NO_WINDOW)
            log.info("Windows fährt herunter: Tablet %s ausgeschaltet", serial)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("Sitzungsende: Tablet %s nicht ausgeschaltet: %s", serial, e)


def wake_tablets(adb):
    via = _via_shell("svc power stayon true; input keyevent KEYCODE_WAKEUP")
    for serial in via:
        log.info("Tablet %s geweckt (offene Shell)", serial)
    if via:
        return
    for serial in _devices(adb) or []:
        try:
            subprocess.run([adb, "-s", serial, "shell", "svc power stayon true; input keyevent KEYCODE_WAKEUP"],
                           capture_output=True, timeout=3, creationflags=NO_WINDOW)
            log.info("Tablet %s geweckt", serial)
        except (OSError, subprocess.SubprocessError):
            pass


def _devices(adb, quiet=False):
    try:
        out = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=2.5,
                             creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError) as e:
        if not quiet:
            log.warning("Sitzungsende: adb devices fehlgeschlagen: %r", e)
        return None   # Fehler, nicht "keine Tablets"
    return [p[0] for p in (ln.split() for ln in out.splitlines()[1:]) if len(p) == 2 and p[1] == "device"]


def watch_session_end(adb, notify=None, serials=None, on_end=None):
    """Startet den Fenster-Thread. adb: Pfad zu adb.exe (oder None).
    notify(action): dieselbe Aktion ("sleep"/"shutdown") an Tablets im WLAN (Steuerkanal), synchron und kurz.
    serials(): per USB eingerichtete Tablets (aus der Bridge), spart beim Herunterfahren das "adb devices".
    on_end(ending): Sitzung endet (True) bzw. Herunterfahren abgebrochen (False) - z. B. Wächter: kein Neustart."""
    global _serials
    _serials = serials
    if adb:
        keep_shells(adb)
    done = threading.Event()
    order = threading.Lock()   # Schlafen und Wecken nacheinander, nie überholend

    def tell(action):
        """WLAN-Meldung parallel zu adb starten (Windows gibt beim Herunterfahren nur wenige Sekunden)."""
        if not notify:
            return None

        def run():
            try:
                notify(action)
            except Exception as e:  # noqa: BLE001
                log.warning("WLAN-Tablet nicht erreicht (%s): %s", action, e)
        t = threading.Thread(target=run, name="session-notify", daemon=True)
        t.start()
        return t

    def do_sleep():
        t = tell("sleep")
        if adb:
            sleep_tablets(adb)
        if t:
            t.join(1.0)

    def do_shutdown():
        t = tell("shutdown")
        if adb:
            shutdown_tablets(adb)
        if t:
            t.join(0.5)

    def sleep_locked():
        with order:
            do_sleep()

    def wake_locked():
        with order:
            if adb:
                wake_tablets(adb)

    def wake_after_resume():
        # USB/adb melden sich nach dem Aufwachen erst neu an - bis zu 30 s auf das Tablet warten
        for _ in range(15):
            if adb and _devices(adb):
                time.sleep(2)   # adb kurz stabil werden lassen
                wake_locked()
                return
            time.sleep(2)

    def proc(hwnd, msg, wparam, lparam):
        # Schon bei der Anfrage starten (Hintergrund-Thread, hält das Herunterfahren nicht auf): bis
        # WM_ENDSESSION kann die Aufgabenplanung den Wächter samt Bridge (Job-Objekt) schon beendet haben.
        if msg == WM_QUERYENDSESSION:
            log.info("Sitzungsende: Windows wird beendet (QUERYENDSESSION)")
            if on_end:
                on_end(True)
            if not done.is_set():
                done.set()
                threading.Thread(target=sleep_locked, name="session-sleep", daemon=True).start()
            return 1
        if msg == WM_POWERBROADCAST:
            if wparam == PBT_APMSUSPEND:
                with order:
                    do_sleep()   # synchron: danach schläft der PC
            elif wparam == PBT_APMRESUMESUSPEND:
                threading.Thread(target=wake_after_resume, name="session-wake", daemon=True).start()
            return 1
        if msg == WM_ENDSESSION:
            log.info("Sitzungsende: ENDSESSION %s%s", "ja" if wparam else "abgebrochen",
                     " (Abmelden)" if lparam & ENDSESSION_LOGOFF else "")
            if wparam:
                done.set()
                with order:   # wartet auf einen noch laufenden Schlafbefehl
                    if lparam & ENDSESSION_LOGOFF:
                        do_sleep()        # nur abmelden: PC läuft weiter
                    else:
                        do_shutdown()     # endgültig: Herunterfahren oder Neustart
            elif not wparam and done.is_set():
                # Herunterfahren abgebrochen (z. B. ungespeicherte Datei): Tablet wieder wecken
                done.clear()
                if on_end:
                    on_end(False)
                threading.Thread(target=wake_locked, name="session-wake", daemon=True).start()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # eigene DLL-Instanz: argtypes/errcheck sind sonst prozessweit mit pystray (Taskleisten-Symbol) geteilt
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    wndproc = WNDPROC(proc)

    def run():
        # Fehler hier liefen unter pythonw sonst still ins Leere (kein stderr) - immer ins Log
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE   # Standard c_int schneidet 64-Bit-Handles ab
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            hinst = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW(lpfnWndProc=wndproc, hInstance=hinst, lpszClassName="TabletDeckSession")
            if not user32.RegisterClassW(ctypes.byref(wc)):
                log.error("Sitzungsende-Wächter: RegisterClass fehlgeschlagen (Fehler %d)", ctypes.get_last_error())
                return
            hwnd = user32.CreateWindowExW(0, "TabletDeckSession", "Tablet Deck", 0, 0, 0, 0, 0,
                                          None, None, hinst, None)
            if not hwnd:
                log.error("Sitzungsende-Wächter: CreateWindow fehlgeschlagen (Fehler %d)", ctypes.get_last_error())
                return
            log.info("Sitzungsende-Wächter aktiv (%s)", "Tablet geht mit dem PC aus" if adb
                     else "nur WLAN-Meldung, USB-Tablets schaltet der Wächter")
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            log.error("Sitzungsende-Wächter: Nachrichtenschleife beendet")
        except Exception:  # noqa: BLE001
            log.exception("Sitzungsende-Wächter ausgefallen - Tablet geht nicht mit dem PC aus")

    # Unter den Anwendungen zuerst benachrichtigt werden (höchste Stufe für Nicht-System-Prozesse)
    ctypes.windll.kernel32.SetProcessShutdownParameters(0x3FF, 0)
    t = threading.Thread(target=run, name="session", daemon=True)
    t.wndproc = wndproc   # Rückruf am Leben halten
    t.start()
    return t
