"""Unit-Tests für bridge/pcinput.py mit Attrappen (keine echte Maus/Tastatur).

Aufruf: python -m unittest tests.test_pcinput
"""
import unittest
from unittest import mock

from bridge import keys
from bridge.pcinput import PcInput


class FakeAudio:
    def __init__(self):
        self.v, self.m = None, None

    def set_volume(self, v):
        self.v = v

    def set_mute(self, m):
        self.m = m


class PcInputTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        patches = [
            mock.patch.object(keys, "mouse_button", lambda b, d: self.events.append(("btn", b, d))),
            mock.patch.object(keys, "mouse_move", lambda dx, dy: self.events.append(("move", dx, dy))),
            mock.patch.object(keys, "send_scan", lambda sc, ext, up: self.events.append(("scan", sc, up))),
            mock.patch.object(keys, "type_text", lambda s: self.events.append(("text", s))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.pc = PcInput(FakeAudio())

    def test_button_refcount_two_sources_one_client(self):
        st = self.pc.new_client()
        self.pc.handle(st, {"t": "btn", "b": "left", "down": True})   # Pad-Ziehen
        self.pc.handle(st, {"t": "btn", "b": "left", "down": True})   # Seitentaste
        self.pc.handle(st, {"t": "btn", "b": "left", "down": False})
        self.assertEqual(self.events, [("btn", "left", True)])          # noch gehalten
        self.pc.handle(st, {"t": "btn", "b": "left", "down": False})
        self.assertEqual(self.events[-1], ("btn", "left", False))

    def test_two_clients_and_disconnect(self):
        a, b = self.pc.new_client(), self.pc.new_client()
        self.pc.handle(a, {"t": "btn", "b": "right", "down": True})
        self.pc.handle(b, {"t": "btn", "b": "right", "down": True})
        self.pc.drop_client(a)
        self.assertNotIn(("btn", "right", False), self.events)        # b hält noch
        self.pc.drop_client(b)
        self.assertEqual(self.events.count(("btn", "right", False)), 1)

    def test_release_all(self):
        a = self.pc.new_client()
        self.pc.handle(a, {"t": "btn", "b": "left", "down": True})
        self.pc.handle(a, {"t": "btn", "b": "middle", "down": True})
        self.pc.release_all()
        self.assertIn(("btn", "left", False), self.events)
        self.assertIn(("btn", "middle", False), self.events)
        self.assertEqual(self.pc.pressed, {})

    def test_up_without_down_ignored(self):
        st = self.pc.new_client()
        self.pc.handle(st, {"t": "btn", "b": "left", "down": False})
        self.assertEqual(self.events, [])

    def test_invalid_input_does_not_raise(self):
        st = self.pc.new_client()
        for m in ({"t": "move", "dx": "x"}, {"t": "btn", "b": "evil", "down": True},
                  {"t": "key", "k": "GIBTSNICHT"}, {"t": "move", "dx": 99999, "dy": 0},
                  {"t": "text", "s": "x" * 10000}, {"t": "volume", "v": "laut"}):
            self.assertTrue(self.pc.handle(st, m))
        self.assertEqual(self.events, [])

    def test_key_combo_order(self):
        st = self.pc.new_client()
        self.pc.handle(st, {"t": "key", "k": "LCTRL+C"})
        scans = [(e[1], e[2]) for e in self.events]
        self.assertEqual(scans, [(0x1D, False), (0x2E, False), (0x2E, True), (0x1D, True)])

    def test_macro_runs_steps_in_order(self):
        import asyncio
        with mock.patch.object(keys, "tap_vk", lambda vk: self.events.append(("vk", vk))):
            asyncio.run(self.pc.run_macro([{"key": "F1"}, {"wait": 10}, {"text": "o7"}, {"media": "next"}]))
        kinds = [e[0] for e in self.events]
        self.assertEqual(kinds, ["scan", "scan", "text", "vk"])
        self.assertEqual(self.events[2], ("text", "o7"))

    def test_unknown_type_not_handled(self):
        self.assertFalse(self.pc.handle(self.pc.new_client(), {"t": "down", "id": "x"}))


if __name__ == "__main__":
    unittest.main()
