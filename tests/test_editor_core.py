"""Führt die Node-Tests des Editor-Kerns (tests/js/) aus; ohne Node wird übersprungen."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class EditorCoreJs(unittest.TestCase):
    def test_node_tests(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js nicht installiert")
        # Dateien einzeln übergeben: ein Verzeichnis als Argument kennen nicht alle Node-Versionen
        files = sorted(str(f.relative_to(ROOT)) for f in (ROOT / "tests" / "js").glob("*.test.js"))
        self.assertTrue(files, "keine JS-Tests gefunden")
        r = subprocess.run([node, "--test", *files], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-3000:])


if __name__ == "__main__":
    unittest.main()
