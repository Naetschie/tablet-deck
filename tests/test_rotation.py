"""Unit-Tests für die feste Tablet-Ausrichtung (config tablet_rotation -> Launcher-Nachricht).

Aufruf: python -m unittest tests.test_rotation
"""
import logging
import unittest

from bridge.__main__ import tablet_rotation


class TabletRotationTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_default_querformat(self):
        self.assertEqual(tablet_rotation({}), 1)

    def test_gueltige_werte(self):
        for r in range(4):
            self.assertEqual(tablet_rotation({"tablet_rotation": r}), r)

    def test_null_heisst_nicht_anfassen(self):
        self.assertIsNone(tablet_rotation({"tablet_rotation": None}))

    def test_ungueltig_wird_ignoriert(self):
        for bad in (4, -1, True, "1", 1.0):
            self.assertIsNone(tablet_rotation({"tablet_rotation": bad}), bad)


if __name__ == "__main__":
    unittest.main()
