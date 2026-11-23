"""Unit-Tests für den Begleit-Modus (config tablet_mode -> Hub-Logik und Launcher-Nachricht).

Aufruf: python -m unittest tests.test_tablet_mode
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from bridge.__main__ import (HOME_ACTIVITY, HOME_COMPONENT, Bridge, home_is_launcher, home_start_args,
                             launcher_start_args, tablet_mode, device_mode)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TabletModeTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_standard_ist_home(self):
        self.assertEqual(tablet_mode({}), "home")

    def test_gueltige_werte(self):
        for m in ("home", "companion"):
            self.assertEqual(tablet_mode({"tablet_mode": m}), m)

    def test_ungueltig_wird_home(self):
        for bad in ("Companion", "", None, 1, True, ["companion"]):
            self.assertEqual(tablet_mode({"tablet_mode": bad}), "home", bad)

    def test_ctl_nachricht(self):
        fake = SimpleNamespace(cfg={"tablet_mode": "companion"})
        self.assertEqual(Bridge.tablet_mode_msg(fake), {"t": "tablet_mode", "mode": "companion"})
        fake = SimpleNamespace(cfg={})
        self.assertEqual(Bridge.tablet_mode_msg(fake), {"t": "tablet_mode", "mode": "home"})

    def test_resolve_activity_alias_oder_ziel(self):
        for ok in (HOME_COMPONENT, HOME_ACTIVITY, " " + HOME_COMPONENT + "\r",
                   "app.tabletdeck.launcher/app.tabletdeck.launcher.HomeAlias",
                   "app.tabletdeck.launcher/app.tabletdeck.launcher.HomeActivity"):
            self.assertTrue(home_is_launcher(ok), ok)
        for bad in ("com.android.launcher3/.Launcher", "", "app.tabletdeck.launcher/.Other"):
            self.assertFalse(home_is_launcher(bad), bad)

    def test_home_ist_der_alias(self):
        self.assertEqual(HOME_COMPONENT, "app.tabletdeck.launcher/.HomeAlias")

    def test_start_argumente(self):
        self.assertIn("android.intent.category.LAUNCHER", launcher_start_args())
        self.assertNotIn("android.intent.category.HOME", launcher_start_args())
        self.assertIn("android.intent.category.HOME", home_start_args())
        for a in (launcher_start_args(), home_start_args()):
            self.assertEqual(a[-2:], ("-n", HOME_ACTIVITY))


class DeviceModeTest(unittest.TestCase):
    def test_pro_geraet(self):
        cfg = {"tablet_mode": "home", "tablet_modes": {"HUAWEI1": "companion", "KAPUTT": "irgendwas"}}
        logging.disable(logging.CRITICAL)
        try:
            self.assertEqual(device_mode(cfg, "HUAWEI1"), "companion")
            self.assertEqual(device_mode(cfg, "LENOVO1"), "home")       # nicht eingetragen: Standard
            self.assertEqual(device_mode(cfg, "KAPUTT"), "home")        # ungültig: Standard
            self.assertEqual(device_mode({"tablet_mode": "companion"}, "X"), "companion")
            self.assertEqual(device_mode({"tablet_modes": "kein dict"}, "X"), "home")
        finally:
            logging.disable(logging.NOTSET)


class SetConfigTest(unittest.TestCase):
    def run_cfg(self, cfg, mode, *extra):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "set_config.py"), p, mode, *extra],
                               capture_output=True, text=True)
            with open(p, encoding="utf-8") as f:
                return r.returncode, json.load(f), os.listdir(d)

    def test_companion_setzt_nur_tablet_mode(self):
        rc, cfg, files = self.run_cfg({"spacedesk_usb": True, "x": 1}, "companion")
        self.assertEqual(rc, 0)
        self.assertEqual(cfg, {"spacedesk_usb": True, "x": 1, "tablet_mode": "companion"})
        self.assertEqual(files, ["config.json"])   # keine .tmp-Reste

    def test_home_und_use_skip_lassen_tablet_mode(self):
        rc, cfg, _ = self.run_cfg({"tablet_mode": "companion"}, "use")
        self.assertEqual(cfg["tablet_mode"], "companion")
        rc, cfg, _ = self.run_cfg({"tablet_mode": "companion"}, "skip")
        self.assertEqual(cfg["tablet_mode"], "companion")
        rc, cfg, _ = self.run_cfg({"tablet_mode": "companion"}, "home")
        self.assertEqual(cfg["tablet_mode"], "home")

    def test_device_nur_dieses_geraet(self):
        rc, cfg, files = self.run_cfg({"tablet_mode": "home", "tablet_modes": {"A1": "home"}},
                                      "device", "B2", "companion")
        self.assertEqual(rc, 0)
        self.assertEqual(cfg, {"tablet_mode": "home", "tablet_modes": {"A1": "home", "B2": "companion"}})
        self.assertEqual(files, ["config.json"])
        rc, cfg, _ = self.run_cfg({}, "device", "B2", "companion")
        self.assertEqual(cfg, {"tablet_modes": {"B2": "companion"}})

    def test_device_ungueltig(self):
        for extra in (("a;b", "companion"), ("B2", "quer"), ("B2",), ()):
            rc, cfg, _ = self.run_cfg({"x": 1}, "device", *extra)
            self.assertNotEqual(rc, 0, extra)
            self.assertEqual(cfg, {"x": 1})

    def test_device_light(self):
        rc, cfg, files = self.run_cfg({"tablet_lights": {"A1": False}}, "device", "B2", "light", "on")
        self.assertEqual(rc, 0)
        self.assertEqual(cfg, {"tablet_lights": {"A1": False, "B2": True}})
        rc, cfg, _ = self.run_cfg({"tablet_modes": {"B2": "companion"}}, "device", "B2", "light", "off")
        self.assertEqual(cfg, {"tablet_modes": {"B2": "companion"}, "tablet_lights": {"B2": False}})
        for extra in (("B2", "light"), ("B2", "light", "ja"), ("a;b", "light", "on")):
            rc, cfg, _ = self.run_cfg({"x": 1}, "device", *extra)
            self.assertNotEqual(rc, 0, extra)
            self.assertEqual(cfg, {"x": 1})

    def test_device_light_zieht_devices_json_mit(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            dp = os.path.join(d, "devices.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({}, f)
            with open(dp, "w", encoding="utf-8") as f:
                json.dump({"devices": {"SAM1": {"name": "Samsung", "light": False}, "TAB1": {"name": "T"}}}, f)
            r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "set_config.py"), p, "device", "SAM1",
                                "light", "on"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(dp, encoding="utf-8") as f:
                devs = json.load(f)["devices"]
            self.assertEqual((devs["SAM1"]["light"], "light" in devs["TAB1"]), (True, False))
            # unbekanntes Gerät: devices.json bleibt, config.json bekommt den Eintrag
            r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "set_config.py"), p, "device", "NEU1",
                                "light", "on"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(dp, encoding="utf-8") as f:
                self.assertNotIn("NEU1", json.load(f)["devices"])
            with open(p, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["tablet_lights"], {"SAM1": True, "NEU1": True})
            self.assertEqual(sorted(os.listdir(d)), ["config.json", "devices.json"])

    def test_unbekannter_modus(self):
        rc, _, _ = self.run_cfg({}, "quatsch")
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
