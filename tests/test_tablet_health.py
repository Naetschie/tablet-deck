"""Unit-Tests für bridge/tablet_health.py (Zustand des Tablets fürs Log).

Aufruf: python -m unittest tests.test_tablet_health
"""
import asyncio
import logging
import unittest

from bridge.tablet_health import TabletHealth, parse

OUT = """18850.23 70110.11
MemAvailable:     702200 kB
SwapTotal:       1048572 kB
SwapFree:         646736 kB
2026-11-14 22:15:04 SYSTEM_BOOT (text, 348 bytes)
2026-11-15 11:00:22 system_app_anr (text, 3495 bytes)
2026-11-15 11:00:30 netstats_error (text, 10 bytes)
2026-11-15 11:27:03 SYSTEM_BOOT (text, 348 bytes)
"""


class ParseTest(unittest.TestCase):
    def test_parse(self):
        p = parse(OUT)
        self.assertEqual(p["uptime"], 18850.23)
        self.assertEqual((p["mem_kb"], p["swap_free_kb"]), (702200, 646736))
        self.assertEqual(p["events"], [("2026-11-14 22:15:04", "SYSTEM_BOOT"),
                                       ("2026-11-15 11:00:22", "system_app_anr"),
                                       ("2026-11-15 11:27:03", "SYSTEM_BOOT")])   # netstats ausgelassen


class EvaluateTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.h = TabletHealth(clock=lambda: self.now)

    def texts(self, p):
        return [t for _, t in self.h.evaluate("S1", p, self.now)]

    def test_erster_lauf_dann_nur_neues(self):
        first = self.texts(parse(OUT))
        self.assertTrue(any("letzte Starts" in t and "2026-11-15 11:27:03" in t for t in first))
        self.assertTrue(any("Zustand" in t and "frei 685 MB" in t for t in first))
        # nichts Neues, Statuszeile erst nach 30 min wieder
        self.now = 300
        self.assertEqual(self.texts(parse(OUT)), [])
        # neues Ereignis und Neustart (Laufzeit kleiner)
        self.now = 600
        neu = OUT.replace("18850.23", "95.0") + "2026-11-15 23:06:27 SYSTEM_BOOT (text, 348 bytes)\n"
        lines = self.texts(parse(neu))
        self.assertTrue(any("SYSTEM_BOOT um 2026-11-15 23:06:27" in t for t in lines))
        self.assertTrue(any("neu gestartet" in t for t in lines))
        self.now = 2500
        self.assertTrue(any("Zustand" in t for t in self.texts(parse(neu))))

    def test_speicher_knapp_ist_warnung(self):
        knapp = OUT.replace("702200", "150000")
        lines = self.h.evaluate("S1", parse(knapp), 0)
        self.assertTrue(any(lvl == logging.WARNING and "Speicher knapp" in t for lvl, t in lines))

    def test_check_mit_adb_fehler_still(self):
        async def run(*_a):
            return 1, "error: device offline"
        self.assertEqual(asyncio.run(self.h.check(run, "adb", "S1")), [])
        self.assertFalse(self.h.due("S1"))       # nächster Versuch erst nach dem Intervall


if __name__ == "__main__":
    unittest.main()
