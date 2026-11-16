"""Tests für scripts/make_zip.py (Ausschlüsse, Geheimnis-Prüfliste) und bridge/firstrun.py (Beispiele anlegen)."""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import make_zip  # noqa: E402
from bridge import firstrun  # noqa: E402

# Prüfbeispiele werden zusammengesetzt, damit dieser Test sich nicht selbst als Fund meldet
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----\nabc\n"
PEM2 = "-----BEGIN " + "PRIVATE KEY-----\nabc\n"
ANT = "sk-" + "ant-api03-" + "A" * 30


class MakeZipTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def put(self, rel, text="x"):
        p = self.d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return rel

    def test_ausschluesse(self):
        for rel in ("secrets/sensors.key", "tls/ca.pem", "secret.key", "send.key", "bridge.log", "supervise.log.1",
                    "tools/platform-tools/adb.exe", "dist/a.zip", "debug.keystore", "android/x/debug.keystore",
                    "bookmarks.json", "web_history.json", "mapgenie_cache.json", "mapgenie_cache.json.tmp",
                    "sensors.json", "config.json", "launcher.json", "profiles/.papierkorb/a/b.json", "dashboards/eigene/x.json",
                    "bridge/__pycache__/x.pyc"):
            self.assertTrue(make_zip.excluded(rel), rel)
        for rel in ("config.example.json", "launcher.example.json", "sensors.example.json", "games.json",
                    "profiles/star-citizen/main.json", "panels/star-citizen/cockpit.json", "bridge/__main__.py", "install.ps1", "docs/install.md",
                    "android/src/app/tabletdeck/launcher/HubLink.java"):
            self.assertFalse(make_zip.excluded(rel), rel)

    def test_build_enthaelt_nur_erlaubtes(self):
        tracked = [self.put("install.ps1"), self.put("config.json"), self.put("config.example.json"),
                   self.put("secrets/sensors.key", "geheim"), self.put("tools/a.exe"), self.put("bridge.log")]
        out, n, warn = make_zip.build(self.d, self.d / "dist" / "t.zip", tracked=tracked)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(sorted(z.namelist()), ["TabletDeck/config.example.json", "TabletDeck/install.ps1"])
        self.assertEqual(n, 2)
        self.assertTrue(any("APK" in w or "apk" in w for w in warn))   # ohne APK nur Warnung

    def test_apk_wird_angehaengt(self):
        tracked = [self.put("install.ps1")]
        self.put(make_zip.APK, "apk")
        out, n, warn = make_zip.build(self.d, self.d / "t.zip", tracked=tracked)
        with zipfile.ZipFile(out) as z:
            self.assertIn("TabletDeck/android/build/tablet-deck.apk", z.namelist())
        self.assertEqual(warn, [])

    def test_fehlende_datei_nur_warnung(self):
        out, n, warn = make_zip.build(self.d, self.d / "t.zip", tracked=[self.put("a.txt"), "weg.txt"])
        self.assertEqual(n, 1)
        self.assertTrue(any("weg.txt" in w for w in warn))

    def test_geheimnis_im_inhalt_bricht_ab(self):
        for text in (PEM, PEM2, "key = " + ANT):
            with self.subTest(text=text[:12]):
                rel = self.put("bridge/x.py", text)
                with self.assertRaises(SystemExit) as cm:
                    make_zip.build(self.d, self.d / "t.zip", tracked=[rel])
                self.assertIn("bridge/x.py", str(cm.exception))
                self.assertNotIn("A" * 20, str(cm.exception))   # Inhalt wird nie ausgegeben
                self.assertFalse((self.d / "t.zip").exists())

    def test_verdaechtiger_name_bricht_ab(self):
        for rel in ("docs/server.pem", "cert.p12", ".env", "id_rsa", "deploy/credentials.txt"):
            with self.subTest(rel=rel):
                self.put(rel)
                with self.assertRaises(SystemExit):
                    make_zip.build(self.d, self.d / "t.zip", tracked=[rel])

    def test_ausgeschlossenes_geheimnis_stoert_nicht(self):
        tracked = [self.put("a.txt"), self.put("secrets/k.txt", PEM), self.put("tls/ca.key", PEM)]
        out, n, _ = make_zip.build(self.d, self.d / "t.zip", tracked=tracked)
        self.assertEqual(n, 1)

    def test_pruefliste_trifft_dieses_repo_nicht(self):
        files, _ = make_zip.select(ROOT, make_zip.git_files(ROOT))
        self.assertEqual(make_zip.check_secrets(ROOT, files), [])


class FirstRunTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)
        for n in ("config.example.json", "launcher.example.json"):
            (self.d / n).write_bytes((ROOT / n).read_bytes())

    def tearDown(self):
        self._t.cleanup()

    def test_beispiele_sind_gueltig_und_neutral(self):
        cfg = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        self.assertNotIn("pico_port", cfg)
        self.assertFalse(cfg["audio_output"]["prefer"])
        self.assertEqual(cfg["auto_modes"], [])
        tiles = json.loads((ROOT / "launcher.example.json").read_text(encoding="utf-8"))["tiles"]
        self.assertIn("ph.spacedesk.beta", [t.get("pkg") for t in tiles])
        self.assertNotIn("mobro", json.dumps(tiles).lower())

    def test_legt_an_und_ueberschreibt_nie(self):
        self.assertEqual(firstrun.ensure_all(self.d), ["config.json", "launcher.json"])
        self.assertEqual((self.d / "config.json").read_bytes(), (ROOT / "config.example.json").read_bytes())
        (self.d / "config.json").write_text('{"port": 1}', encoding="utf-8")
        self.assertEqual(firstrun.ensure_all(self.d), [])
        self.assertEqual((self.d / "config.json").read_text(encoding="utf-8"), '{"port": 1}')
        self.assertEqual(sorted(p.name for p in self.d.iterdir() if p.name.endswith(".tmp")), [])

    def test_ohne_spacedesk(self):
        firstrun.ensure_all(self.d, drop_spacedesk=True)
        tiles = json.loads((self.d / "launcher.json").read_text(encoding="utf-8"))["tiles"]
        self.assertNotIn("ph.spacedesk.beta", [t.get("pkg") for t in tiles])
        self.assertIn("settings", [t["id"] for t in tiles])

    def test_fehlendes_beispiel_ist_kein_fehler(self):
        (self.d / "config.example.json").unlink()
        self.assertEqual(firstrun.ensure_all(self.d), ["launcher.json"])


class ActionmapsTest(unittest.TestCase):
    def test_findet_actionmaps_ueber_die_bibliothek(self):
        from bridge.bindings import cryengine
        with tempfile.TemporaryDirectory() as t:
            am = Path(t) / "StarCitizen" / cryengine.ACTIONMAPS
            am.parent.mkdir(parents=True)
            am.write_text("<x/>", encoding="utf-8")
            exe = Path(t) / "StarCitizen" / "LIVE" / "Bin64" / "StarCitizen.exe"
            lib = [{"name": "Anderes", "dir": t, "exe": "x.exe"},
                   {"name": "Star Citizen", "dir": str(exe.parent), "exe": str(exe)}]
            self.assertEqual(cryengine.find_user_actionmaps(lib), str(am))
            self.assertIsNone(cryengine.find_user_actionmaps([lib[0]]))
            self.assertIsNone(cryengine.find_user_actionmaps([]))


if __name__ == "__main__":
    unittest.main()
