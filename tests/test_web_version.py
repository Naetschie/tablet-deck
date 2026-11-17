"""Kennung der Web-Dateien: ändert sich bei jeder Änderung, damit die Tablet-Seiten nach einem Update neu laden."""
import os
import tempfile
import unittest
from pathlib import Path

from bridge.__main__ import web_version


class WebVersionTest(unittest.TestCase):
    def test_changes_with_content_and_new_files(self):
        with tempfile.TemporaryDirectory() as d:
            web = Path(d)
            (web / "lib").mkdir()
            (web / "app.js").write_text("a", encoding="utf-8")
            (web / "lib" / "ui.css").write_text("b", encoding="utf-8")
            v1 = web_version(web)
            self.assertEqual(v1, web_version(web))          # stabil ohne Änderung
            (web / "app.js").write_text("aa", encoding="utf-8")
            v2 = web_version(web)
            self.assertNotEqual(v1, v2)                     # Größe geändert
            st = (web / "lib" / "ui.css").stat()
            os.utime(web / "lib" / "ui.css", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
            v3 = web_version(web)
            self.assertNotEqual(v2, v3)                     # gleiche Größe, neuere Zeit
            (web / "neu.html").write_text("", encoding="utf-8")
            self.assertNotEqual(v3, web_version(web))       # neue Datei

    def test_real_web_dir(self):
        self.assertRegex(web_version(), r"^[0-9a-f]{12}$")


if __name__ == "__main__":
    unittest.main()
