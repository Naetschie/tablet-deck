"""Mitgelieferte Panels (panels/): gültig, und jede Star-Citizen-Aktion (sc) gibt es im Standardprofil.

Das Standardprofil stammt aus den Spieldateien und liegt nicht im Repo (tools/sc/...); ohne es wird die
Aktionsprüfung übersprungen (CI).
"""
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bridge.layout import validate_layout

ROOT = Path(__file__).resolve().parent.parent
SC_DEFAULT = ROOT / "tools" / "sc" / "Data" / "Libs" / "Config" / "defaultProfile.plain.xml"


def bundled():
    return sorted((ROOT / "panels").glob("*/*.json"))


class BundledPanelsTest(unittest.TestCase):
    def test_all_valid(self):
        self.assertTrue(bundled())
        for f in bundled():
            with self.subTest(panel=f.name):
                validate_layout(json.loads(f.read_text(encoding="utf-8")))

    def test_sc_buttons_have_action_and_no_fixed_key(self):
        # Tasten kommen aus der Belegung des Spielers (nie geraten): sc ja, key nein
        for f in (ROOT / "panels" / "star-citizen").glob("*.json"):
            for p in json.loads(f.read_text(encoding="utf-8"))["pages"]:
                for b in p["buttons"]:
                    if "kind" in b:
                        continue
                    with self.subTest(panel=f.name, id=b["id"]):
                        self.assertTrue(b.get("sc"))
                        self.assertNotIn("key", b)

    @unittest.skipUnless(SC_DEFAULT.is_file(), "Standardprofil von Star Citizen fehlt (tools/sc)")
    def test_sc_actions_exist_in_default_profile(self):
        known = {a.get("name") for a in ET.parse(SC_DEFAULT).getroot().iter("action")}
        for f in (ROOT / "panels" / "star-citizen").glob("*.json"):
            for p in json.loads(f.read_text(encoding="utf-8"))["pages"]:
                for b in p["buttons"]:
                    if b.get("sc"):
                        with self.subTest(panel=f.name, sc=b["sc"]):
                            self.assertIn(b["sc"], known)


if __name__ == "__main__":
    unittest.main()
