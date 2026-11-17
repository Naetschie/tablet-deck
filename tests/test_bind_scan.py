"""Generisches Einlesen der Steuerung (bridge/bindings: keynames, containers, readers, locate, scan)."""
import gzip
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bridge import bindings
from bridge.bindings import keynames as kn
from bridge.bindings import locate, scan
from bridge.bindings.containers import open_bytes
from bridge.bindings.readers import read_content

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
ActionMappings=(ActionName="Fire",bShift=False,bCtrl=False,bAlt=False,bCmd=False,Key=F)
ActionMappings=(ActionName="Copy",bShift=False,bCtrl=False,bAlt=False,bCmd=True,Key=C)
ActionMappings=(ActionName="Slot1",bShift=False,bCtrl=False,bAlt=False,bCmd=False,Key=One)
"""
SCANCODES = "[Player]\nForward=key:17\nBack=key:31\nRun=key:42\nAttack=key:10000\nNone=key:0\nUse=key:18\n"
SOURCE = 'bind "w" "+forward"\nbind "SHIFT" "+speed"\nbind "MOUSE1" "+attack"\nbind "e" "+use"\nbind "r" "+reload"\nbind "F5" "save"\n'
UNITY = json.dumps({"bindings": [{"action": "Player/Jump", "id": "x", "path": "<Keyboard>/space"},
                                 {"action": "Player/Fire", "id": "y", "path": "<Mouse>/leftButton"}]})
GENERIC_XML = """<shortcuts><func name="pause"><key>P</key></func><func name="save"><key modifier="CTRL">S</key></func>
<func name="ui"><key>K</key></func><func name="map"><key>M</key></func><func name="all"><key modifier="CTRL">A</key></func></shortcuts>"""


def gvas(*strings):
    out = b"GVAS" + b"\x00" * 8
    for s in strings:
        b = s.encode() + b"\x00"
        out += struct.pack("<i", len(b)) + b + b"\x00\x00"
    return out


class KeyNamesTest(unittest.TestCase):
    def test_schemes(self):
        cases = {"Ctrl+S": "LCTRL+S", "LeftShift": "LSHIFT", "<Keyboard>/digit1": "1", "<Mouse>/leftButton": None,
                 "kLMenu": "LALT", "DIK_NEXT": "PGDN", "SpaceBar": "SPACE", "NumPadEight": "NUMPAD8", "Alpha1": "1",
                 "KP_8": "NUMPAD8", "Esc": "ESC", "Mouse1": None, "ABC": None, "": None}
        for raw, want in cases.items():
            self.assertEqual(kn.text_key(raw), want, raw)
        self.assertEqual((kn.dik_code(17), kn.dik_code(42), kn.dik_code(10000)), ("W", "LSHIFT", None))
        self.assertEqual(kn.combo(["Alt", "Shift", "F4"], kn.common), "LSHIFT+LALT+F4")


class ContainersTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(open_bytes(b"a=1\nb=2")[0], "text")
        self.assertEqual(open_bytes(("a" * 4095 + "ä").encode())[0], "text")       # abgeschnittenes Zeichen
        self.assertEqual(open_bytes("x=1".encode("utf-16")), ("text", "x=1"))
        self.assertEqual(open_bytes(gzip.compress(b"bind w +forward"))[0], "text")
        self.assertEqual(open_bytes(gvas("x"))[0], "gvas")
        self.assertEqual(open_bytes(os.urandom(20000))[0], "encrypted")
        self.assertEqual(open_bytes(b"\x00\x01\x02" * 500)[0], "binary")


class ReadersTest(unittest.TestCase):
    def test_enforce(self):
        r = read_content("text", PRESET)
        b = r.bindings
        self.assertEqual(r.method, "exact")
        self.assertEqual((b["UAMoveForward"][0], b["UAToggleNVG"][:2], b["UACopy"][0], b["UAPgDn"][0]),
                         ("W", ("L", True), "LCTRL+C", "PGDN"))
        for a in ("UAWalkRunToggle", "UABrush", "UAOnlyPad"):
            self.assertIsNone(b[a][0], a)

    def test_unreal_ini(self):
        b = read_content("text", UE).bindings
        self.assertEqual((b["Jump"][0], b["QuickSave"][0], b["Fire"][0], b["Copy"][0], b["Slot1"][0]),
                         ("SPACE", "LCTRL+F5", "F", None, "1"))

    def test_scancodes_source_unity(self):
        b = read_content("text", SCANCODES).bindings
        self.assertEqual((b["Forward"][0], b["Run"][0], b["Attack"][0], b["None"][0]), ("W", "LSHIFT", None, None))
        b = read_content("text", SOURCE).bindings
        self.assertEqual((b["+forward"][0], b["+speed"][0], b["+attack"][0]), ("W", "LSHIFT", None))
        r = read_content("text", UNITY)
        self.assertEqual((r.bindings["Player/Jump"][0], r.bindings["Player/Fire"][0], r.only_changes),
                         ("SPACE", None, True))

    def test_gvas(self):
        r = read_content("gvas", gvas("/Script/EnhancedInput.EnhancedInputUserSettings", "MappingName",
                                      "NameProperty", "IA_Jump", "CurrentKey", "KeyName", "NameProperty", "SpaceBar"))
        self.assertEqual(r.bindings["IA_Jump"][0], "SPACE")
        empty = read_content("gvas", gvas("/Script/EnhancedInput.EnhancedInputUserSettings", "None"))
        self.assertEqual((empty.count, empty.only_changes), (0, True))
        self.assertIsNone(read_content("gvas", gvas("/Script/Game.SaveGame", "Level")))

    def test_generic(self):
        r = read_content("text", GENERIC_XML)
        self.assertEqual((r.method, r.bindings["save"][0], r.bindings["pause"][0]), ("generic", "LCTRL+S", "P"))
        js = json.dumps({"keys": [{"action": a, "key": k} for a, k in
                                  (("jump", "Space"), ("map", "M"), ("inv", "I"), ("use", "E"), ("run", "LeftShift"))]})
        self.assertEqual(read_content("text", js).bindings["run"][0], "LSHIFT")
        ini = "Workers=1\nThreads=4\nQuality=High\nFullscreen=True\nJump=Space\n"
        self.assertIsNone(read_content("text", ini))                     # Zahlen sind keine Tasten, zu wenig Paare


class ReviewTest(unittest.TestCase):
    def test_no_false_positives(self):
        ini = "Align=Left\nDock=Right\nMode=Add\nChannel=A\nDir=Back\nNext=Next\nVolume=5\nQuality=High\n"
        self.assertIsNone(read_content("text", ini))
        vals = json.dumps([{"name": n, "value": v} for n, v in (("Volume", "5"), ("Music", "3"), ("Fx", "4"),
                                                                 ("A", "2"), ("B", "1"))])
        self.assertIsNone(read_content("text", vals))
        self.assertIsNone(read_content("text", json.dumps({"Alignment": "Left", "Anchor": "Right", "Theme": "Tab",
                                                            "Grade": "B", "Mode": "Add"})))
        keys = "[Keys]\nJump=Space\nUse=E\nMap=M\nInventory=I\nCrouch=C\nSprint=LeftShift\n"
        self.assertEqual(read_content("text", keys).count, 6)   # „[Keys]“ ist kein JSON

    def test_gzip_bomb_limited(self):
        kind, content = open_bytes(gzip.compress(bytes(50_000_000)))
        self.assertLessEqual(len(content or b""), 8 * 1024 * 1024)

    def test_local_low_and_stop_words(self):
        self.assertEqual(locate.local_low().name, "LocalLow")
        self.assertFalse(locate.name_matches("Microsoft", ["Microsoft Flight Simulator"]))


class LocateTest(unittest.TestCase):
    def test_name_matching(self):
        self.assertTrue(locate.name_matches("Zomboid", ["Project Zomboid"]))
        self.assertFalse(locate.name_matches("SpaceEngineers", ["Space Haven"]))
        self.assertTrue(locate.name_matches("DayZ", ["DayZ"]))
        self.assertTrue(locate.exact_match("Warhammer3", ["Total War: WARHAMMER III"]))
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "G1R" / "Binaries" / "Win64"
            exe.mkdir(parents=True)
            (exe / "G1R-Win64-Shipping.exe").write_bytes(b"")
            (Path(d) / "Game_Data").mkdir()
            (Path(d) / "Game_Data" / "app.info").write_text("Firma\nProdukt", encoding="utf-8")
            self.assertEqual(locate.unreal_projects(d), ["G1R"])
            self.assertEqual(locate.unity_app(d), ("Firma", "Produkt"))


class SearchTest(unittest.TestCase):
    def env(self, d):
        home = Path(d) / "home"
        local = home / "AppData" / "Local"
        for p in (home / "Documents", local, home / "AppData" / "Roaming"):
            p.mkdir(parents=True, exist_ok=True)
        return home, local, {"LOCALAPPDATA": str(local), "APPDATA": str(home / "AppData" / "Roaming"),
                             "USERPROFILE": str(home), "HOME": str(home)}

    def test_states(self):
        with tempfile.TemporaryDirectory() as d:
            home, local, env = self.env(d)
            (home / "Documents" / "Testspiel").mkdir()
            (home / "Documents" / "Testspiel" / "Spieler.dayz_preset_User.xml").write_text(PRESET, encoding="utf-8")
            (local / "GEHEIM2" / "Saved").mkdir(parents=True)
            (local / "GEHEIM2" / "Saved" / "DeviceSetting_V2.dat").write_bytes(os.urandom(4000))
            (local / "NURNEU" / "Saved" / "SaveGames").mkdir(parents=True)
            (local / "NURNEU" / "Saved" / "SaveGames" / "EnhancedInputUserSettings.sav").write_bytes(
                gvas("/Script/EnhancedInput.EnhancedInputUserSettings", "None"))
            with mock.patch.dict(os.environ, env), mock.patch.object(locate, "documents", lambda: home / "Documents"):
                fd = scan.search("Testspiel")
                self.assertEqual((fd.state, fd.bindings["UAMap"][0]), ("read", "M"))
                self.assertIn("…dayz_preset_User.xml", fd.message)
                self.assertNotIn("Spieler", fd.message)                  # kein Profilname in Meldung/Log
                self.assertEqual(scan.search("Geheim 2").state, "unreadable")
                self.assertEqual(scan.search("Nurneu").state, "only_changes")
                self.assertEqual(scan.search("Gibtsnicht").state, "none")
                res, msg, state = bindings.find_fallback("Testspiel")
                self.assertTrue(res.bindings["UAToggleNVG"].hold)
                self.assertTrue(res.free)

    def test_defaults_merged_and_bad_file_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            home, local, env = self.env(d)
            inst = Path(d) / "steam" / "Mischspiel"
            (inst / "Config").mkdir(parents=True)
            (inst / "Config" / "Input.ini").write_text(UE, encoding="utf-8")      # Standard (Installationsordner)
            user = local / "Mischspiel" / "Saved" / "Config"
            user.mkdir(parents=True)
            (user / "Input.ini").write_text(
                'ActionMappings=(ActionName="Jump",bShift=False,bCtrl=False,bAlt=False,bCmd=False,Key=J)\n',
                encoding="utf-8")                                                 # nur eine Änderung
            (user / "keys_broken.xml").write_text("<preset><input", encoding="utf-8")   # kaputt
            with mock.patch.dict(os.environ, env), mock.patch.object(locate, "documents", lambda: home / "Documents"):
                fd = scan.search("Mischspiel", str(inst))
            self.assertEqual((fd.bindings["Jump"][0], fd.bindings["QuickSave"][0]), ("J", "LCTRL+F5"))
            self.assertIn("Standardbelegung", fd.message)

    def test_learn_mode(self):
        with tempfile.TemporaryDirectory() as d:
            home, local, env = self.env(d)
            g = local / "Lernspiel"
            g.mkdir()
            (g / "a.cfg").write_text("x", encoding="utf-8")
            with mock.patch.dict(os.environ, env), mock.patch.object(locate, "documents", lambda: home / "Documents"):
                snap = scan.snapshot("Lernspiel")
                (g / "anything.dat").write_text(SOURCE, encoding="utf-8")   # Name verrät nichts
                ch = scan.changed(snap, "Lernspiel")
                self.assertEqual([Path(p).name for p in ch], ["anything.dat"])
                self.assertEqual(scan.search("Lernspiel").state, "none")    # ohne Lernen nicht gefunden
                fd = scan.search("Lernspiel", learned=ch[0])
                self.assertEqual((fd.state, fd.bindings["+forward"][0]), ("read", "W"))


if __name__ == "__main__":
    unittest.main()
