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
    b.hold_since, b.late_release = {}, {}
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

    def test_press_ms_lengthens_pulse(self):
        # Spiel wertet erst lange Drücke (delayed_press): Impuls dauert press_ms statt 80 ms
        async def run():
            br = make_bridge()
            br.fire({"id": "l", "key": "N", "press_ms": 300}, True)
            await asyncio.sleep(0.2)
            mid = list(br.out.events)
            await asyncio.sleep(0.2)
            return mid, br.out.events
        mid, end = asyncio.run(run())
        self.assertEqual(mid, [("press", "l")])
        self.assertEqual(end, [("press", "l"), ("release", "l")])

    def test_press_ms_delays_early_release_of_hold(self):
        async def run():
            br = make_bridge()
            btn = {"id": "h", "key": "M", "hold": True, "press_ms": 300}
            br.fire(btn, True)
            br.fire(btn, False)                     # Finger sofort weg
            await asyncio.sleep(0.15)
            mid = list(br.out.events)
            await asyncio.sleep(0.25)
            return mid, br.out.events
        mid, end = asyncio.run(run())
        self.assertEqual(mid, [("press", "h")])     # noch gehalten
        self.assertEqual(end, [("press", "h"), ("release", "h")])

    def test_press_ms_second_release_and_repress(self):
        # zwei Loslassen vor Ablauf: nur ein Termin; erneuter Druck dazwischen hebt ihn auf
        async def run():
            br = make_bridge()
            btn = {"id": "h", "key": "M", "hold": True, "press_ms": 300}
            br.fire(btn, True)
            br.fire(btn, False)
            br.fire(btn, False)
            br.fire(btn, True)                      # wieder gedrückt: bleibt gedrückt
            await asyncio.sleep(0.4)
            mid = list(br.out.events)
            br.fire(btn, False)                     # jetzt länger als press_ms gehalten: sofort los
            return mid, br.out.events
        mid, end = asyncio.run(run())
        self.assertEqual(mid, [("press", "h"), ("press", "h")])
        self.assertEqual(end, [("press", "h"), ("press", "h"), ("release", "h")])

    def test_press_ms_flush_and_no_pileup(self):
        async def run():
            br = make_bridge()
            hold = {"id": "h", "key": "M", "hold": True, "press_ms": 1000}
            br.fire(hold, True)
            br.fire(hold, False)
            self.assertEqual(br.flush_late_releases(), 1)   # Ansichtswechsel: sofort los
            tap = {"id": "t", "key": "N", "press_ms": 200}
            for _ in range(4):                      # hektisches Tippen auf einen langen Druck
                br.fire(tap, True)
            await asyncio.sleep(0.4)
            return br.out.events
        self.assertEqual(asyncio.run(run()), [("press", "h"), ("release", "h"), ("press", "t"), ("release", "t")])

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
