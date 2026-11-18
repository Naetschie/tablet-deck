"""Unit-Tests: WLAN-Tablet nach dem Schlafbefehl des PCs genau einmal wecken (Bridge.wake_wlan/wlan_slept).

Aufruf: python -m unittest tests.test_wlan_wake
"""
import asyncio
import json
import unittest
from types import SimpleNamespace

from bridge.__main__ import Bridge


class FakeWs:
    def __init__(self, ip, on_send=None, fail=False):
        self.remote_address = (ip, 50000)
        self.sent = []
        self.on_send = on_send
        self.fail = fail

    async def send(self, data):
        if self.on_send:
            self.on_send()
        await asyncio.sleep(0)
        if self.fail:
            raise ConnectionError("weg")
        self.sent.append(json.loads(data))


def hub(**cfg):
    return SimpleNamespace(cfg=cfg, wlan_woken=set())


def wake(b, ws):
    return asyncio.run(Bridge.wake_wlan(b, ws, ws.remote_address[0]))


class WlanWakeTest(unittest.TestCase):
    def test_einmal_je_ip(self):
        b = hub()
        first, again = FakeWs("10.0.0.5"), FakeWs("10.0.0.5")
        self.assertTrue(wake(b, first))
        self.assertEqual(first.sent, [{"t": "power", "action": "wake"}])
        self.assertFalse(wake(b, again))      # WLAN-Aussetzer: nicht erneut wecken
        self.assertEqual(again.sent, [])

    def test_nach_schlafbefehl_wieder(self):
        b = hub()
        wake(b, FakeWs("10.0.0.5"))
        Bridge.wlan_slept(b)                  # auch ohne verbundenes Tablet
        self.assertTrue(wake(b, FakeWs("10.0.0.5")))

    def test_schlafbefehl_waehrend_senden(self):
        b = hub()
        ws = FakeWs("10.0.0.5", on_send=lambda: Bridge.wlan_slept(b))
        wake(b, ws)
        self.assertNotIn("10.0.0.5", b.wlan_woken)   # danach kam "sleep": beim nächsten Verbinden wecken

    def test_senden_scheitert(self):
        b = hub()
        with self.assertRaises(ConnectionError):
            wake(b, FakeWs("10.0.0.5", fail=True))
        self.assertTrue(wake(b, FakeWs("10.0.0.5")))

    def test_usb_und_abgeschaltet(self):
        self.assertFalse(wake(hub(), FakeWs("127.0.0.1")))
        self.assertFalse(wake(hub(tablet_sleep_with_pc=False), FakeWs("10.0.0.5")))


if __name__ == "__main__":
    unittest.main()
