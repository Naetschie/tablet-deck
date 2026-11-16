"""Taskleisten-Symbol: Modus am Tablet wählen, Seiten neu laden, Bridge beenden.

pystray läuft in einem eigenen Thread; Aktionen werden threadsicher an die asyncio-Schleife übergeben.
"""
import asyncio
import logging
import threading
import webbrowser

log = logging.getLogger("tray")


def _icon_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 12, 58, 52), radius=8, fill=(21, 24, 27, 255), outline=(79, 179, 255, 255), width=4)
    d.ellipse((26, 26, 38, 38), fill=(61, 220, 132, 255))
    return img


def clipboard_text():
    """Text der Windows-Zwischenablage (CF_UNICODETEXT) oder ''."""
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.GetClipboardData.restype = wintypes.HANDLE
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not u32.OpenClipboard(None):
        return ""
    try:
        h = u32.GetClipboardData(13)   # CF_UNICODETEXT
        if not h:
            return ""
        ptr = k32.GlobalLock(h)
        try:
            return ctypes.wstring_at(ptr) if ptr else ""
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def set_clipboard_text(text):
    """Text in die Windows-Zwischenablage, ohne Verlauf (Win+V) und ohne Cloud-Sync (wie Passwortmanager).
    Gibt True bei Erfolg zurück."""
    import ctypes
    import time
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    u32.SetClipboardData.restype = wintypes.HANDLE
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]

    def block(data):
        size = ctypes.sizeof(data)
        h = k32.GlobalAlloc(0x0002, size)   # GMEM_MOVEABLE
        if not h:
            return None
        ptr = k32.GlobalLock(h)
        if not ptr:
            k32.GlobalFree(h)
            return None
        ctypes.memmove(ptr, ctypes.addressof(data), size)
        k32.GlobalUnlock(h)
        return h

    # Speicher zuerst anlegen: scheitert das, bleibt der bisherige Inhalt der Zwischenablage erhalten
    h = block(ctypes.create_unicode_buffer(text))
    if not h:
        return False
    # Zwischenablage kann kurz von einer anderen App belegt sein
    for _ in range(5):
        if u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        k32.GlobalFree(h)
        return False
    try:
        u32.EmptyClipboard()
        if not u32.SetClipboardData(13, h):   # CF_UNICODETEXT; bei Erfolg gehört h der Zwischenablage
            k32.GlobalFree(h)
            return False
        zero = ctypes.c_uint32(0)
        for name in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                     "CanUploadToCloudClipboard"):
            fmt = u32.RegisterClipboardFormatW(name)
            hz = block(zero)
            if fmt and hz and not u32.SetClipboardData(fmt, hz):
                k32.GlobalFree(hz)
        return True
    finally:
        u32.CloseClipboard()


class Tray:
    def __init__(self, bridge, loop, stop):
        self.bridge, self.loop, self.stop = bridge, loop, stop
        self.icon = None

    def _do(self, coro_fn):
        asyncio.run_coroutine_threadsafe(coro_fn(), self.loop)

    def _menu(self):
        import pystray
        b = self.bridge

        def mode_item(t):
            return pystray.MenuItem(t.get("title", t["id"]),
                                    lambda: self._do(lambda: b.ctl_send({"t": "mode", "mode": t["id"]})),
                                    checked=lambda _: t["id"] in b.ctl_clients.values())

        tiles = [t for t in b.tiles if t.get("type") in ("web", "browser")]
        return pystray.Menu(
            pystray.MenuItem(lambda _: f"Tablet: {'verbunden' if b.ctl_clients else 'nicht verbunden'}",
                             None, enabled=False),
            pystray.Menu.SEPARATOR,
            *[mode_item(t) for t in tiles],
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("URL aus Zwischenablage ans Tablet", self._send_clipboard),
            pystray.MenuItem("Schlüssel für Browser-Erweiterung kopieren", self._copy_send_key),
            pystray.MenuItem("Panel-Editor öffnen", lambda: webbrowser.open(b.editor_url), default=True),
            pystray.MenuItem("Tablet-Seiten neu laden", lambda: self._do(lambda: b.ctl_send({"t": "reload"}))),
            pystray.MenuItem("Bridge beenden", self._quit),
        )

    def _send_clipboard(self):
        url = clipboard_text().strip()

        async def go():
            err = await self.bridge.send_url(url)
            if err and self.icon:
                self.icon.notify(f"Nicht gesendet: {err}", "Tablet Deck")
        self._do(go)

    def _copy_send_key(self):
        ok = set_clipboard_text(self.bridge.send_key)
        if self.icon:
            self.icon.notify("Schlüssel kopiert - in den Optionen der Erweiterung einfügen." if ok
                             else "Zwischenablage belegt - bitte nochmal versuchen.", "Tablet Deck")

    def _quit(self):
        log.info("Beenden über Taskleisten-Symbol")
        self.loop.call_soon_threadsafe(self.stop.set)
        self.icon.stop()

    def start(self):
        try:
            import pystray
        except ImportError:
            log.warning("pystray fehlt - kein Taskleisten-Symbol (pip install -r requirements.txt)")
            return
        self.icon = pystray.Icon("tabletdeck", _icon_image(), "Tablet Deck", self._menu())
        threading.Thread(target=self.icon.run, name="tray", daemon=True).start()

    def refresh(self):
        """Menü neu aufbauen (z. B. nach geänderten Kacheln)."""
        if self.icon and self.icon.visible:
            self.icon.menu = self._menu()
            self.icon.update_menu()

    def close(self):
        if self.icon:
            try:
                self.icon.stop()   # ggf. schon über "Beenden" gestoppt
            except Exception:  # noqa: BLE001
                pass
