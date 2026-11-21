"""Unit-Tests für die Geräteliste (bridge/devices.py) und das gezielte Senden ans Hauptgerät.

Aufruf: python -m unittest tests.test_devices
"""
import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bridge.devices import Devices, valid_id
from bridge.__main__ import Bridge, device_cookie, device_mode, device_rotation


class FakeWs:
    def __init__(self, cookie=""):
        self.request = SimpleNamespace(headers={"Cookie": cookie})
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))


class DevicesTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "devices.json"

    def tearDown(self):
        self.tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_erstes_geraet_wird_hauptgeraet(self):
        d = Devices(self.path)
        self.assertIsNone(d.main())
        self.assertTrue(d.see("TAB1", "Tablet A"))
        self.assertTrue(d.see("PHONE1", "Phone B"))
        self.assertFalse(d.see("TAB1", "Tablet A"))   # schon bekannt
        self.assertEqual(d.main(), "TAB1")
        self.assertTrue(d.multi())
        # gespeichert und wieder gelesen
        self.assertEqual(Devices(self.path).main(), "TAB1")

    def test_hauptgeraet_umstellen(self):
        d = Devices(self.path)
        d.see("TAB1")
        d.see("PHONE1")
        self.assertTrue(d.set_main("PHONE1"))
        self.assertFalse(d.set_main("UNBEKANNT"))
        d2 = Devices(self.path)
        self.assertEqual(d2.main(), "PHONE1")
        self.assertEqual(sum(1 for v in d2.data.values() if v["main"]), 1)

    def test_genau_ein_hauptgeraet_beim_laden(self):
        self.path.write_text(json.dumps({"devices": {"A": {"main": True}, "B": {"main": True}, "C": {}}}),
                             encoding="utf-8")
        d = Devices(self.path)
        self.assertEqual([k for k, v in d.data.items() if v["main"]], ["A"])
        self.path.write_text(json.dumps({"devices": {"A": {}, "B": {}}}), encoding="utf-8")
        self.assertEqual(Devices(self.path).main(), "A")

    def test_kaputte_datei_und_ungueltige_kennungen(self):
        self.path.write_text("{kaputt", encoding="utf-8")
        self.assertEqual(Devices(self.path).data, {})
        self.path.write_text(json.dumps({"devices": {"ok-1": {}, "bad id": {}, "x;y": {}, "n": "kein dict"}}),
                             encoding="utf-8")
        self.assertEqual(list(Devices(self.path).data), ["ok-1"])
        for bad in ("", "a b", "a;b", "a=b", "x" * 65, None, 5):
            self.assertFalse(valid_id(bad), bad)
        self.assertFalse(Devices(self.path).see("a;b"))

    def test_kaputte_datei_wird_nicht_ueberschrieben(self):
        text = '{"devices": {"TAB1": {"name": "Mein Tablet", "rotation": 0},}'   # Tippfehler: Komma
        self.path.write_text(text, encoding="utf-8")
        d = Devices(self.path)
        self.assertTrue(d.broken)
        d.see("PHONE1")
        self.assertEqual(self.path.read_text(encoding="utf-8"), text)

    def test_name(self):
        d = Devices(self.path)
        d.see("S1", "SNE-LX1")
        self.assertEqual(d.name("S1"), "SNE-LX1")
        d.data["S1"]["name"] = "Handy HOTAS"
        self.assertEqual(d.name("S1"), "Handy HOTAS")
        self.assertEqual(d.name("FREMD"), "FREMD")

    def test_betriebsart_und_ausrichtung_pro_geraet(self):
        d = Devices(self.path)
        d.see("TAB1")
        d.see("PHONE1")
        d.data["PHONE1"].update(mode="companion", rotation=0)
        cfg = {"tablet_rotation": 1}
        self.assertEqual(device_mode(cfg, "PHONE1", d), "companion")
        self.assertEqual(device_mode(cfg, "TAB1", d), "home")
        self.assertEqual(device_rotation(cfg, "PHONE1", d), 0)
        self.assertEqual(device_rotation(cfg, "TAB1", d), 1)
        self.assertEqual(device_rotation(cfg, None, d), 1)
        # config.json tablet_modes gilt weiter, devices.json geht vor
        cfg2 = {"tablet_modes": {"TAB1": "companion"}}
        self.assertEqual(device_mode(cfg2, "TAB1", d), "companion")
        d.data["TAB1"]["mode"] = "home"
        self.assertEqual(device_mode(cfg2, "TAB1", d), "home")
        # ungültig -> Rückfall
        d.data["PHONE1"].update(mode="quer", rotation=7)
        self.assertEqual(device_mode(cfg, "PHONE1", d), "home")
        self.assertEqual(device_rotation(cfg, "PHONE1", d), 1)
        d.data["PHONE1"]["rotation"] = None   # ausdrücklich: nicht anfassen
        self.assertIsNone(device_rotation(cfg, "PHONE1", d))

    def test_nachrichten_pro_geraet(self):
        d = Devices(self.path)
        d.see("PHONE1")
        d.data["PHONE1"].update(mode="companion", rotation=0)
        fake = SimpleNamespace(cfg={"tablet_rotation": 1}, devices=d)
        self.assertEqual(Bridge.rotation_msg(fake, "PHONE1"), {"t": "rotation", "r": 0})
        self.assertEqual(Bridge.rotation_msg(fake), {"t": "rotation", "r": 1})
        self.assertEqual(Bridge.tablet_mode_msg(fake, "PHONE1"), {"t": "tablet_mode", "mode": "companion"})
        self.assertEqual(Bridge.tablet_mode_msg(fake), {"t": "tablet_mode", "mode": "home"})

    def test_cookie(self):
        self.assertEqual(device_cookie(FakeWs("deck=geheim; deckdev=TAB1")), "TAB1")
        self.assertIsNone(device_cookie(FakeWs("deck=geheim")))
        self.assertIsNone(device_cookie(FakeWs("deckdev=a,b")))
        self.assertIsNone(device_cookie(FakeWs("deckdev=x y")))
        self.assertIsNone(device_cookie(object()))


class SendTargetTest(unittest.TestCase):
    """„An Tablet senden“: nur ans Hauptgerät, sobald mehrere Geräte gekoppelt sind."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.tmp = tempfile.TemporaryDirectory()
        self.devs = Devices(Path(self.tmp.name) / "devices.json")
        self.added = []

    def tearDown(self):
        self.tmp.cleanup()
        logging.disable(logging.NOTSET)

    def bridge(self, conns):
        b = SimpleNamespace(devices=self.devs, ctl_clients={}, ctl_device={},
                            web=SimpleNamespace(add_sent=lambda url: self.added.append(url) or False))
        for ws, dev in conns:
            b.ctl_clients[ws] = None
            b.ctl_device[ws] = dev
        b.send_targets = lambda: Bridge.send_targets(b)
        return b

    def send(self, b, url="https://example.org/x"):
        return asyncio.run(Bridge.send_url(b, url))

    def test_ein_geraet_wie_bisher(self):
        self.devs.see("TAB1")
        a, c = FakeWs(), FakeWs()
        b = self.bridge([(a, "TAB1"), (c, None)])   # auch ohne Kennung (alte App)
        self.assertIsNone(self.send(b))
        self.assertEqual(len(a.sent), 1)
        self.assertEqual(len(c.sent), 1)

    def test_nur_hauptgeraet(self):
        self.devs.see("TAB1", "Tablet")
        self.devs.see("PHONE1", "Handy")
        tab, phone, alt = FakeWs(), FakeWs(), FakeWs()
        b = self.bridge([(tab, "TAB1"), (phone, "PHONE1"), (alt, None)])
        self.assertIsNone(self.send(b))
        self.assertEqual(tab.sent, [{"t": "open", "url": "https://example.org/x"}])
        self.assertEqual(phone.sent, [])
        self.assertEqual(alt.sent, [])
        self.devs.set_main("PHONE1")
        self.send(b)
        self.assertEqual(len(phone.sent), 1)
        self.assertEqual(len(tab.sent), 1)

    def test_hauptgeraet_weg_kein_ausweichen(self):
        self.devs.see("TAB1", "Tablet")
        self.devs.see("PHONE1", "Handy")
        phone = FakeWs()
        b = self.bridge([(phone, "PHONE1")])
        self.assertEqual(self.send(b), "Tablet nicht verbunden")
        self.assertEqual(phone.sent, [])
        self.assertEqual(self.added, [])   # nicht gesendet -> nicht unter „Vom PC gesendet“

    def test_ohne_launcher(self):
        b = self.bridge([])
        self.assertEqual(self.send(b), "Tablet nicht verbunden")


class TilesTest(unittest.TestCase):
    """Kacheln pro Gerät (devices.json tiles) und Ansichtswechsel nur an Geräte mit der Kachel."""

    TILES = [{"id": "screen"}, {"id": "panel"}, {"id": "touchpad"}, {"id": "web"}]

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.tmp = tempfile.TemporaryDirectory()
        self.devs = Devices(Path(self.tmp.name) / "devices.json")
        self.devs.see("TAB1")
        self.devs.see("PHONE1")
        self.devs.data["PHONE1"]["tiles"] = ["touchpad", "panel"]

    def tearDown(self):
        self.tmp.cleanup()
        logging.disable(logging.NOTSET)

    def bridge(self, conns):
        b = SimpleNamespace(devices=self.devs, tiles=self.TILES, ctl_clients={}, ctl_device={})
        for ws, dev in conns:
            b.ctl_clients[ws] = None
            b.ctl_device[ws] = dev
        b.tiles_for = lambda dev: Bridge.tiles_for(b, dev)
        return b

    def test_filter(self):
        b = self.bridge([])
        ids = lambda dev: [t["id"] for t in Bridge.tiles_for(b, dev)]
        self.assertEqual(ids("PHONE1"), ["panel", "touchpad"])   # Reihenfolge aus launcher.json
        self.assertEqual(ids("TAB1"), ["screen", "panel", "touchpad", "web"])
        self.assertEqual(ids(None), ["screen", "panel", "touchpad", "web"])
        self.devs.data["PHONE1"]["tiles"] = "panel"   # ungültig -> alle
        self.assertEqual(len(ids("PHONE1")), 4)

    def test_ctl_send(self):
        tab, phone = FakeWs(), FakeWs()
        b = self.bridge([(tab, "TAB1"), (phone, "PHONE1")])
        asyncio.run(Bridge.ctl_send(b, {"t": "tiles", "tiles": self.TILES}))
        self.assertEqual(len(tab.sent[-1]["tiles"]), 4)
        self.assertEqual([t["id"] for t in phone.sent[-1]["tiles"]], ["panel", "touchpad"])
        asyncio.run(Bridge.ctl_send(b, {"t": "mode", "mode": "web"}))
        self.assertEqual(tab.sent[-1], {"t": "mode", "mode": "web"})
        self.assertEqual(len(phone.sent), 1)   # Handy hat keine Web-Kachel
        asyncio.run(Bridge.ctl_send(b, {"t": "mode", "mode": "panel"}))
        self.assertEqual(phone.sent[-1], {"t": "mode", "mode": "panel"})
        asyncio.run(Bridge.ctl_send(b, {"t": "reload"}))
        self.assertEqual(phone.sent[-1], {"t": "reload"})

    def test_ohne_kacheln_wie_bisher(self):
        phone = FakeWs()
        b = self.bridge([(phone, "PHONE1")])
        b.tiles = []   # launcher.json fehlt/leer: Launcher nutzt seine Standards
        asyncio.run(Bridge.ctl_send(b, {"t": "mode", "mode": "panel"}))
        self.assertEqual(phone.sent, [{"t": "mode", "mode": "panel"}])


if __name__ == "__main__":
    unittest.main()
