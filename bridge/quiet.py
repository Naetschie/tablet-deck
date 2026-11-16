"""Hinweisfenster von spacedesk unterdrücken.

Der spacedesk-Dienst startet sein Tray-Programm selbst. Das zeigt mitten auf dem Hauptmonitor den Dialog
"spacedesk Connection Notification" ("Connection(s) pending ..."), sobald das Tablet im USB-Zubehör-Modus
hängt, die spacedesk-App aber (noch) nicht verbunden ist - also bei jedem Anstecken. In der Treiber-Konsole
lässt sich das nicht abschalten. Abbrechen (IDCANCEL/WM_CLOSE) ignoriert der Dialog, solange die Verbindung
aussteht - die Bridge blendet ihn deshalb aus (ShowWindow SW_HIDE); zeigt das Tray-Programm ihn erneut,
wird er wieder ausgeblendet.
"""
import asyncio
import ctypes
import logging

log = logging.getLogger("quiet")
TITLES = ("spacedesk Connection Notification",)
SW_HIDE = 0


def hide_dialogs():
    user32 = ctypes.windll.user32
    closed = 0
    for title in TITLES:
        hwnd = user32.FindWindowW("#32770", title)   # Standard-Dialogklasse
        if hwnd and user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, SW_HIDE)
            closed += 1
    return closed


async def silence_spacedesk(interval=0.5):
    last_log = -1e9
    while True:
        try:
            # Der Dialog taucht beim Verbinden mehrfach kurz hintereinander auf - nur einmal protokollieren
            if hide_dialogs() and asyncio.get_running_loop().time() - last_log > 30:
                last_log = asyncio.get_running_loop().time()
                log.info("spacedesk-Hinweis ausgeblendet")
        except Exception as e:  # noqa: BLE001
            log.error("spacedesk-Hinweis: %s", e)
        await asyncio.sleep(interval)
