"""Ausgabe-Backends: keyboard (SendInput) und pico (USB-Seriell)."""
import logging
import threading
from collections import Counter

log = logging.getLogger("out")


class KeyboardOutput:
    name = "keyboard"
    closing = False

    def __init__(self, cfg):
        from . import keys
        self.keys = keys
        self.held = Counter()  # (scan, ext) -> Anzahl gehaltener Buttons, die diese Taste brauchen

    def can(self, btn):
        k = btn.get("key")
        if not k:
            return False
        try:
            self.keys.parse_combo(k)
            return True
        except KeyError:
            return False

    def press(self, btn):
        if self.closing:
            return
        for sc in self.keys.parse_combo(btn["key"]):
            self.held[sc] += 1
            if self.held[sc] == 1:
                self.keys.send_scan(*sc, up=False)

    def release(self, btn):
        for sc in reversed(self.keys.parse_combo(btn["key"])):
            if self.held[sc] <= 0:
                continue
            self.held[sc] -= 1
            if self.held[sc] == 0:
                self.keys.send_scan(*sc, up=True)

    def release_all(self):
        for sc, n in list(self.held.items()):
            if n > 0:
                self.keys.send_scan(*sc, up=True)
        self.held.clear()

    def close(self):
        self.release_all()


class PicoOutput:
    """Zeilenprotokoll: 'P 65' / 'R 65' / 'A' / '?' -> 'OK ...' oder 'ERR ...'."""
    name = "pico"

    def __init__(self, cfg):
        import serial
        self.port = cfg["pico_port"]
        self.ser = serial.Serial(self.port, 115200, timeout=0.2)
        self.lock = threading.Lock()
        self.held = Counter()
        reply = self._cmd("?")
        log.info("Pico an %s: %s", self.port, reply or "(keine Antwort)")

    def _cmd(self, line):
        with self.lock:
            self.ser.write((line + "\n").encode("ascii"))
            reply = self.ser.readline().decode("ascii", "replace").strip()
        if reply.startswith("ERR"):
            log.warning("Pico %r -> %s", line, reply)
        return reply

    def can(self, btn):
        j = btn.get("joy")
        return isinstance(j, int) and 65 <= j <= 128

    def press(self, btn):
        j = btn["joy"]
        self.held[j] += 1
        if self.held[j] == 1:
            self._cmd(f"P {j}")

    def release(self, btn):
        j = btn["joy"]
        if self.held[j] <= 0:
            return
        self.held[j] -= 1
        if self.held[j] == 0:
            self._cmd(f"R {j}")

    def release_all(self):
        self.held.clear()
        self._cmd("A")

    def close(self):
        try:
            self.release_all()
        finally:
            self.ser.close()


def make_output(cfg):
    return {"keyboard": KeyboardOutput, "pico": PicoOutput}[cfg["output"]](cfg)
