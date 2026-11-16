"""Unit-Tests für Bridge.fire(): Impuls vs. Halten (Attrappen-Ausgabe, keine echten Tasten).

Aufruf: python -m unittest tests.test_fire
"""
import asyncio
import unittest

from bridge.__main__ import Bridge


class FakeOut:
    name = "keyboard"

    def __init__(self):
        self.events = []

    def can(self, btn):
        return bool(btn.get("key"))

    def press(self, btn):
        self.events.append(("press", btn["id"]))

    def release(self, btn):
        self.events.append(("release", btn["id"]))


def make_bridge():
    b = Bridge.__new__(Bridge)   # ohne __init__ (keine Dateien/Ausgabe nötig)
    b.out, b.macros = FakeOut(), {}
    b.pulse_q, b.pulse_tasks = {}, {}
    return b


class FireTest(unittest.TestCase):
    def test_pulse_ignores_finger_duration(self):
        async def run():
            br = make_bridge()
            btn = {"id": "x", "key": "G"}
            br.fire(btn, True)
            await asyncio.sleep(0.01)               # Impuls läuft in der Warteschlange der Taste
            self.assertEqual(br.out.events, [("press", "x")])
            br.fire(btn, False)                     # Finger hoch: ohne Wirkung
            self.assertEqual(br.out.events, [("press", "x")])
            await asyncio.sleep(0.15)               # Impuls endet von selbst
            return br.out.events
        self.assertEqual(asyncio.run(run()), [("press", "x"), ("release", "x")])

    def test_rapid_pulses_stay_separate(self):
        async def run():
            br = make_bridge()
            btn = {"id": "s", "key": "F1"}
            for _ in range(3):                      # Regler über drei Stufen in einem Zug
                br.fire(btn, True)
                br.fire(btn, False)
            await asyncio.sleep(0.5)
            return br.out.events
        self.assertEqual(asyncio.run(run()), [("press", "s"), ("release", "s")] * 3)

    def test_hold_follows_finger(self):
        async def run():
            br = make_bridge()
            btn = {"id": "h", "key": "TAB", "hold": True}
            br.fire(btn, True)
            await asyncio.sleep(0.15)
            self.assertEqual(br.out.events, [("press", "h")])   # noch gehalten
            br.fire(btn, False)
            return br.out.events
        self.assertEqual(asyncio.run(run()), [("press", "h"), ("release", "h")])

    def test_unmapped_does_nothing(self):
        async def run():
            br = make_bridge()
            br.fire({"id": "u"}, True)
            br.fire({"id": "u"}, False)
            await asyncio.sleep(0.1)
            return br.out.events
        self.assertEqual(asyncio.run(run()), [])


if __name__ == "__main__":
    unittest.main()
