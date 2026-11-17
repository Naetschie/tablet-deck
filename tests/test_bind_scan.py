"""Rückfall-Suche nach Belegungsdateien (bridge/bindings/scan.py): DayZ-Presets, Unreal Input.ini, Unlesbares."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bridge import bindings
from bridge.bindings import scan

PRESET = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<preset>
  <input name="UAMoveForward"><btn name="kW"/><btn name="x1LeftThumbUp"/></input>
  <input name="UAToggleNVG"><btn name="kL"><event name="hold"/></btn></input>
  <input name="UAWalkRunToggle"><btn name="kLControl"><event name="doubleclick"/></btn></input>
  <input name="UACopy"><btn name="kLControl"><btn name="kC"/></btn></input>
  <input name="UABrush"><btn name="kB"><btn name="mWheelUp"/></btn></input>
  <input name="UAMap"><btn name="kM"/></input>
  <input name="UAPgDn"><btn name="kNext"/></input>
  <input name="UAOnlyPad"><btn name="x1A"/></input>
</preset>"""
UE = """[/Script/Engine.InputSettings]
ActionMappings=(ActionName="Jump",bShift=False,bCtrl=False,bAlt=False,bCmd=False,Key=SpaceBar)
ActionMappings=(ActionName="QuickSave",bShift=False,bCtrl=True,bAlt=False,bCmd=False,Key=F5)
ActionMappings=(ActionName="Fire",bShift=False,bCtrl=False,bAlt=False,bCmd=False,Key=LeftMouseButton)
ActionMappings=(ActionName="Slot1",bShift=False,bCtrl=False,bAlt=False,bCmd=False,Key=One)
"""


class ScanTest(unittest.TestCase):
    def test_dik_and_unreal_names(self):
        self.assertEqual([scan.dik_key(n) for n in ("kLMenu", "kF5", "kNumpad8", "kNext", "mLeft", "x1A", "kSubstract")],
                         ["LALT", "F5", "NUMPAD8", "PGDN", None, None, "NUMPADSUBTRACT"])
        self.assertEqual([scan.unreal_key(n) for n in ("SpaceBar", "One", "NumPadEight", "LeftMouseButton", "Q")],
                         ["SPACE", "1", "NUMPAD8", None, "Q"])

    def test_parse_enforce(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "Spieler.dayz_preset_User.xml"
            f.write_text(PRESET, encoding="utf-8")
            b = scan.parse_enforce(f)
        self.assertEqual(b["UAMoveForward"][0], "W")
        self.assertEqual(b["UAToggleNVG"][:2], ("L", True))               # Halten: Finger hält
        self.assertIsNone(b["UAWalkRunToggle"][0])                          # Doppelklick: nicht übernehmen
        self.assertEqual(b["UACopy"][0], "LCTRL+C")
        self.assertIsNone(b["UABrush"][0])                                  # mit Mausrad: nein
        self.assertEqual(b["UAPgDn"][0], "PGDN")
        self.assertIsNone(b["UAOnlyPad"][0])

    def test_parse_unreal(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "Input.ini"
            f.write_text(UE, encoding="utf-8")
            b = scan.parse_unreal_ini(f)
        self.assertEqual((b["Jump"][0], b["QuickSave"][0], b["Fire"][0], b["Slot1"][0]), ("SPACE", "LCTRL+F5", None, "1"))

    def test_find_readable_unreadable_none(self):
        with tempfile.TemporaryDirectory() as d:
            home, local = Path(d) / "home", Path(d) / "local"
            (home / "Documents" / "Testspiel").mkdir(parents=True)
            (local / "GEHEIM2" / "Saved").mkdir(parents=True)
            (home / "Documents" / "Testspiel" / "Spieler.dayz_preset_User.xml").write_text(PRESET, encoding="utf-8")
            (local / "GEHEIM2" / "Saved" / "DeviceSetting_V2.dat").write_bytes(b"NCS1\x01\x00\xffZ" * 50)
            env = {"LOCALAPPDATA": str(local), "APPDATA": str(Path(d) / "roam"), "USERPROFILE": str(home), "HOME": str(home)}
            with mock.patch.dict(os.environ, env):
                b, msg, src = scan.find("Testspiel")
                self.assertEqual(b["UAMap"][0], "M")
                self.assertIn("…dayz_preset_User.xml", msg)
                self.assertNotIn("Spieler", msg)                           # kein Profilname in Meldung/Log
                b2, msg2, _ = scan.find("Geheim 2", install_dir=str(Path(d) / "x" / "GEHEIM2"))
                self.assertIsNone(b2)
                self.assertIn("nicht lesbar", msg2)
                b3, msg3, _ = scan.find("Gibtsnicht")
                self.assertIsNone(b3)
                self.assertIn("keine lesbare", msg3)
                res, m = bindings.find_fallback("Testspiel")
                self.assertEqual(res.bindings["UAToggleNVG"].hold, True)
                self.assertTrue(res.free)


if __name__ == "__main__":
    unittest.main()
