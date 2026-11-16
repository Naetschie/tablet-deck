"""Unit-Tests für bridge/webhome.py (Lesezeichen, gesendet, Verlauf).

Aufruf: python -m unittest tests.test_webhome
"""
import json
import tempfile
import unittest
from pathlib import Path

from bridge.webhome import MAX_HISTORY, WebHome, clean_url


class WebHomeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_url(self):
        self.assertEqual(clean_url(" https://a.de/x "), "https://a.de/x")
        for bad in ("javascript:alert(1)", "file:///c:/x", "https://", "http://a b", 3, None, "https://a.de/" + "x" * 3000):
            self.assertIsNone(clean_url(bad), bad)

    def test_history_dedup_title_and_limit(self):
        w = WebHome(self.d)
        self.assertTrue(w.add_history("https://a.de/1"))
        self.assertTrue(w.add_history("https://a.de/1", "Titel"))     # Titel nachgereicht
        self.assertFalse(w.add_history("https://a.de/1", "Anders"))
        self.assertEqual(w.history[0]["title"], "Titel")
        for i in range(MAX_HISTORY + 5):
            w.add_history(f"https://a.de/{i + 2}")
        self.assertEqual(len(w.history), MAX_HISTORY)
        self.assertFalse(w.add_history("ftp://x"))

    def test_sent_gets_title_and_persists(self):
        w = WebHome(self.d)
        w.add_sent("https://b.de/")
        w.add_history("https://b.de/", "Seite B")
        self.assertEqual(w.sent[0]["title"], "Seite B")
        w2 = WebHome(self.d)                      # neu laden
        self.assertEqual(w2.sent[0]["url"], "https://b.de/")

    def test_bookmarks_and_clear(self):
        w = WebHome(self.d)
        w.bookmark("https://c.de/", "C")
        w.bookmark("https://c.de/", "C neu")      # kein Duplikat
        self.assertEqual([b["title"] for b in w.bookmarks], ["C neu"])
        w.bookmark("https://c.de/", add=False)
        self.assertEqual(w.bookmarks, [])
        with self.assertRaises(ValueError):
            w.bookmark("javascript:x")
        w.add_history("https://d.de/")
        w.clear_history()
        self.assertEqual(WebHome(self.d).data()["history"], [])

    def test_no_ping_pong_and_fragment(self):
        w = WebHome(self.d)
        w.add_history("https://a.de/x#oben")
        w.add_history("https://b.de/")
        self.assertFalse(w.add_history("https://a.de/x#unten"))     # kurz danach, ohne Sprungmarke gleich
        self.assertEqual([e["url"] for e in w.history], ["https://b.de/", "https://a.de/x"])

    def test_bookmarks_file_edited_by_hand(self):
        w = WebHome(self.d)
        w.bookmark("https://c.de/", "C")
        import os, time
        (self.d / "bookmarks.json").write_text(json.dumps({"bookmarks": [{"title": "Hand", "url": "https://h.de/"}]}),
                                               encoding="utf-8")
        st = (self.d / "bookmarks.json").stat()
        os.utime(self.d / "bookmarks.json", (st.st_atime, st.st_mtime + 5))
        self.assertEqual([b["title"] for b in w.data()["bookmarks"]], ["Hand"])
        w.bookmark("https://e.de/", "E")                            # Handänderung bleibt erhalten
        self.assertEqual([b["title"] for b in w.bookmarks], ["Hand", "E"])

    def test_broken_files_do_not_crash(self):
        (self.d / "bookmarks.json").write_text("{kaputt", encoding="utf-8")
        (self.d / "web_history.json").write_text(json.dumps({"history": [{"url": "javascript:x", "time": 1}]}),
                                                  encoding="utf-8")
        w = WebHome(self.d)
        self.assertEqual(w.data(), {"bookmarks": [], "sent": [], "history": []})


if __name__ == "__main__":
    unittest.main()
