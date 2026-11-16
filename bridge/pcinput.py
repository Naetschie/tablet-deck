"""PC-Eingaben vom Tablet: Touchpad (Maus), Text, Sondertasten, Medien, Lautstärke.

Nachrichten (WebSocket /ws):
  {"t":"move","dx":3,"dy":-2}           relative Mausbewegung (Pixel, Beschleunigung macht der Client)
  {"t":"btn","b":"left","down":true}     Maustaste drücken/loslassen (left/right/middle)
  {"t":"wheel","dy":120,"dx":0}         Scrollen (120 = eine Raste)
  {"t":"text","s":"Hallo"}              Text tippen (Unicode)
  {"t":"key","k":"ENTER"}               Taste antippen (Namen wie in keys.SCANCODES, auch Kombis)
  {"t":"media","a":"playpause"}         playpause/next/prev/stop/mute/voldown/volup
  {"t":"volume","v":0.42} / {"t":"mute","on":true}
  {"t":"app_volume","k":"1234","v":0.4}   Lautstärke einer App (k = PID als Text oder "sys" für Systemklänge)
  {"t":"app_mute","k":"1234","on":true}   App stumm/laut
  {"t":"output","id":"{0.0.0.…}"}        Standard-Ausgabegerät wechseln (ID aus dem "mixer"-Stand des Hubs)
Der Hub meldet Apps und Geräte als {"t":"mixer","sessions":[{"k","name","v","mute"}],"devices":[{"id","name"}],"default":id}.

Maustasten werden pro Client und Taste gezählt (z. B. Ziehen auf dem Pad + Seitentaste "Links");
am PC wird erst losgelassen, wenn keine Quelle die Taste mehr hält.
"""
import asyncio
import logging
import math
import re
from collections import Counter

from . import keys

log = logging.getLogger("pc")
MAX_MOVE = 2000       # Plausibilitätsgrenze je Nachricht
MAX_TEXT = 500
MAX_DEVICE_ID = 200
APP_KEY = re.compile(r"sys|[0-9]{1,10}")


class PcInput:
    def __init__(self, audio, out=None, run_audio=None):
        self.audio = audio
        # Mixer-Befehle (COM) im Audio-Thread des Hubs ausführen; ohne Angabe direkt (Tests)
        self.run_audio = run_audio or (lambda fn, key=None: fn())
        self.out = out                 # KeyboardOutput (Refcounting mit dem Panel) oder None
        self.clients = []              # Zustände aller verbundenen Clients
        self.pressed = Counter()       # Maustaste -> Anzahl Clients, die sie halten

    def new_client(self):
        st = {"buttons": Counter()}
        self.clients.append(st)
        return st

    def _btn(self, st, b, down):
        if down:
            st["buttons"][b] += 1
            if st["buttons"][b] == 1:
                self.pressed[b] += 1
                if self.pressed[b] == 1:
                    keys.mouse_button(b, True)
        elif st["buttons"][b] > 0:
            st["buttons"][b] -= 1
            if st["buttons"][b] == 0:
                del st["buttons"][b]
                self.pressed[b] -= 1
                if self.pressed[b] <= 0:
                    del self.pressed[b]
                    keys.mouse_button(b, False)

    def _tap_key(self, name):
        combo = keys.parse_combo(name)   # KeyError bei unbekannter Taste
        btn = {"key": name}
        if self.out is not None and getattr(self.out, "name", "") == "keyboard":
            # über die Ausgabe des Panels, damit z. B. ein dort gehaltenes Shift nicht losgelassen wird
            self.out.press(btn)
            self.out.release(btn)
            return
        for sc in combo:
            keys.send_scan(*sc, up=False)
        for sc in reversed(combo):
            keys.send_scan(*sc, up=True)

    def handle(self, st, msg):
        """Verarbeitet eine Nachricht. True, wenn sie zu diesem Modul gehörte."""
        t = msg.get("t")
        try:
            if t == "move":
                dx, dy = int(msg.get("dx", 0)), int(msg.get("dy", 0))
                if abs(dx) <= MAX_MOVE and abs(dy) <= MAX_MOVE and (dx or dy):
                    keys.mouse_move(dx, dy)
            elif t == "btn":
                b = msg.get("b")
                if b in keys.MOUSE_BUTTON_FLAGS:
                    self._btn(st, b, bool(msg.get("down")))
            elif t == "wheel":
                dy, dx = int(msg.get("dy", 0)), int(msg.get("dx", 0))
                if abs(dy) <= 12000 and abs(dx) <= 12000:
                    keys.mouse_wheel(dy, dx)
            elif t == "text":
                s = msg.get("s")
                if isinstance(s, str) and 0 < len(s) <= MAX_TEXT:
                    keys.type_text(s)
            elif t == "key":
                self._tap_key(str(msg.get("k", "")))
            elif t == "media":
                vk = keys.MEDIA_VK.get(msg.get("a"))
                if vk:
                    keys.tap_vk(vk)
            elif t == "volume":
                self.audio.set_volume(float(msg.get("v")))
            elif t == "mute":
                self.audio.set_mute(bool(msg.get("on")))
            elif t == "app_volume":
                k, v = msg.get("k"), msg.get("v")
                if (isinstance(k, str) and APP_KEY.fullmatch(k) and isinstance(v, (int, float))
                        and not isinstance(v, bool) and math.isfinite(v)):
                    self.run_audio(lambda: self.audio.set_session(k, v=float(v)), key=("v", k))
            elif t == "app_mute":
                k, on = msg.get("k"), msg.get("on")
                if isinstance(k, str) and APP_KEY.fullmatch(k) and isinstance(on, bool):
                    self.run_audio(lambda: self.audio.set_session(k, mute=on))
            elif t == "output":
                dev = msg.get("id")
                if isinstance(dev, str) and 0 < len(dev) <= MAX_DEVICE_ID:
                    def switch():
                        if self.audio.set_default(dev) is False:   # None: Fehler, schon geloggt
                            log.info("Ausgabegerät abgelehnt: unbekannte ID")
                    self.run_audio(switch)
            else:
                return False
        except (KeyError, ValueError, TypeError) as e:
            log.info("ungültige Eingabe %s: %s", t, e)
        except OSError as e:
            log.error("SendInput-Fehler (%s): %s", t, e)
        return True

    async def run_macro(self, steps):
        """Makro aus layout.json (vorher von layout.validate_macro geprüft)."""
        for step in steps:
            (k, v), = step.items()
            try:
                if k == "key":
                    self._tap_key(v)
                elif k == "text":
                    keys.type_text(v)
                elif k == "media":
                    keys.tap_vk(keys.MEDIA_VK[v])
                elif k == "wait":
                    await asyncio.sleep(v / 1000)
            except (KeyError, OSError) as e:
                log.error("Makro-Schritt %s fehlgeschlagen: %s", step, e)
                return

    def release(self, st):
        """Alle Maustasten dieses Clients loslassen (Verbindung weg o. Ä.). Rückgabe: Anzahl."""
        held = sorted(st["buttons"])
        for b in held:
            while st["buttons"].get(b):
                try:
                    self._btn(st, b, False)
                except OSError:
                    break
        if held:
            log.warning("Maustaste(n) %s losgelassen", ", ".join(held))
        return len(held)

    def release_all(self):
        """Alle Clients: z. B. wenn der Launcher die Ansicht wechselt. Rückgabe: Anzahl."""
        return sum(self.release(st) for st in self.clients)

    def drop_client(self, st):
        self.release(st)
        if st in self.clients:
            self.clients.remove(st)
