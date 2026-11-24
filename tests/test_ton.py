"""Ton-Feld: Seite /ton/, Symbole im Sprite, Lautstärke an die Launcher."""
import asyncio
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from bridge.__main__ import Bridge

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))


class SpriteTest(unittest.TestCase):
    def test_symbole_vorhanden(self):
        ids = set(re.findall(r'<symbol id="([\w-]+)"', (WEB / "lib/icons.svg").read_text("utf-8")))
        for f in [*WEB.rglob("*.html"), *WEB.rglob("*.js")]:
            for i in re.findall(r"/lib/icons\.svg#([\w-]+)", f.read_text("utf-8")):
                self.assertIn(i, ids, f"{f.relative_to(WEB)}: Symbol {i} fehlt in icons.svg")

    def test_wechselnde_symbole(self):
        sprite = (WEB / "lib/icons.svg").read_text("utf-8")
        for n in ("media.js", "mixer.js"):
            for i in re.findall(r'\? "([\w-]+)" : "([\w-]+)"', (WEB / "ton" / n).read_text("utf-8")):
                for k in i:
                    self.assertIn(f'id="{k}"', sprite)

    def test_seite_vollstaendig(self):
        html = (WEB / "ton/index.html").read_text("utf-8")
        js = "".join((WEB / "ton" / n).read_text("utf-8") for n in ("media.js", "mixer.js"))
        for i in re.findall(r'getElementById\("([\w-]+)"\)', js):
            self.assertIn(f'id="{i}"', html)
        self.assertNotIn("media.js", (WEB / "touchpad/index.html").read_text("utf-8"))


class VolumeTest(unittest.TestCase):
    def test_lautstaerke_an_launcher(self):
        ws = FakeWs()
        b = SimpleNamespace(volume_state=(0.6, True), ctl_clients={ws: "panel"}, ctl_device={ws: "TAB1"}, tiles=[])
        asyncio.run(Bridge.ctl_send(b, Bridge.volume_msg(b)))
        self.assertEqual(ws.sent, [{"t": "volume", "v": 0.6, "mute": True}])


if __name__ == "__main__":
    unittest.main()
