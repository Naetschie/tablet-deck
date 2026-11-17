"""Standardtasten aus Steuerungs-Seiten (bridge/bindings/web.py) - ohne Netz, mit Beispiel-HTML."""
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bridge.autolayout import build
from bridge.bindings import web

TABLE_PAGE = """<html><head><title>PC keybindings - Testspiel | Shacknews</title></head><body>
<nav><ul><li>Home</li><li>Guides: Alle</li></ul></nav>
<article><h2>Keyboard controls</h2><table>
<tr><th colspan="2">In-Game Mapping</th></tr>
<tr><td>Move Forward</td><td>W</td></tr><tr><td>Jump</td><td>Space Bar</td></tr>
<tr><td>Sprint</td><td>Left Shift (Hold)</td></tr><tr><td>Attack</td><td>Left Mouse Button</td></tr>
<tr><td>Quick Save</td><td>F5</td></tr><tr><td>Copy</td><td>Ctrl + C</td></tr>
<tr><td>Movement</td><td>WASD</td></tr><tr><td>Hotbar</td><td>1-9</td></tr>
</table></article></body></html>"""
LIST_PAGE = """<html><head><title>Testspiel PC Keyboard Controls Guide</title></head><body><article>
<h3>Camera</h3><ul><li>Q: Rotate Left</li><li>E: Rotate Right</li><li>Page Up: Zoom In</li></ul>
<h3>Menus</h3><ul><li>Esc &#8211; Pause Menu</li><li>M: Map</li><li>Mouse Wheel: Zoom</li></ul>
</article></body></html>"""


class PageKeyTest(unittest.TestCase):
    def test_keys(self):
        cases = {"Space Bar": ("SPACE", False), "Left Shift (Hold)": ("LSHIFT", True), "Hold F": ("F", True),
                 "Ctrl + C": ("LCTRL+C", False), "F1 / F2": (None, False), "Page Up": ("PGUP", False),
                 "W, A, S, D": (None, False), "Left / Right Arrow": (None, False), "Ctrl + Shift + S": ("LCTRL+LSHIFT+S", False),
                 "Left Mouse Button": (None, False), "WASD": (None, False), "1-9": (None, False),
                 "Esc": ("ESC", False)}
        for text, want in cases.items():
            self.assertEqual(web.page_key(text), want, text)


class ParseTest(unittest.TestCase):
    def test_table_page(self):
        rows = web.parse_page(TABLE_PAGE)
        got = {a: k for _, a, k, _h in rows}
        self.assertEqual(got, {"Move Forward": "W", "Jump": "SPACE", "Sprint": "LSHIFT", "Quick Save": "F5",
                               "Copy": "LCTRL+C"})                         # Maus, WASD, 1-9 weggelassen
        self.assertEqual(rows[0][0], "In-Game Mapping")
        self.assertTrue([r for r in rows if r[1] == "Sprint"][0][3])     # halten

    def test_list_page_and_template(self):
        rows = web.parse_page(LIST_PAGE)
        self.assertEqual([(a, r, k) for a, r, k, _ in rows],
                         [("Camera", "Rotate Left", "Q"), ("Camera", "Rotate Right", "E"), ("Camera", "Zoom In", "PGUP"),
                          ("Menus", "Pause Menu", "ESC"), ("Menus", "Map", "M")])
        tpl = web.to_template("Testspiel", rows, "https://example.com/x", "Example", "T")
        self.assertEqual([a["title"] for a in tpl["sections"][0]["areas"]], ["Camera", "Menus"])
        self.assertEqual(tpl["source"]["url"], "https://example.com/x")
        build(tpl)                                                          # lässt sich anordnen

    def test_only_public_addresses(self):
        def fake(host, port, **kw):
            ip = {"intern.local": "192.168.1.5", "example.com": "93.184.216.34"}[host]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
        with mock.patch.object(socket, "getaddrinfo", fake):
            self.assertEqual(web._public_url("https://example.com/a"), "https://example.com/a")
            for bad in ("https://intern.local/", "file:///c:/x", "ftp://example.com/", "https://user:pw@example.com/"):
                with self.assertRaises(ValueError):
                    web._public_url(bad)

    def test_linear_on_unclosed_tags(self):
        import time
        t0 = time.monotonic()
        web.parse_page("<article>" + "<li>x" * 20000 + "</article>")
        web.parse_page("<p>x" * 20000)
        self.assertLess(time.monotonic() - t0, 2)

    def test_redirect_checked_before_follow(self):
        calls = []

        def fake_get(url, deadline):
            calls.append(url)
            web._check_url(url)
            if "start" in url:
                return None, "http://127.0.0.1:8765/geheim"
            return "ok", None

        def fake_ip(host, port):
            if host == "127.0.0.1":
                raise ValueError("nur öffentliche Adressen")
            return "93.184.216.34"
        with mock.patch.object(web, "_public_ip", fake_ip), mock.patch.object(web, "_get", side_effect=lambda u, d: (
                fake_get(u, d) if "start" in u else (fake_ip(web._check_url(u)[1], 80), ("ok", None))[1])):
            with self.assertRaises(ValueError):
                web.fetch("https://example.com/start")
        with self.assertRaises(ValueError):
            web._check_url("https://example.com:8765/")                    # nur Standard-Ports

    def test_search_names(self):
        self.assertEqual(web.name_variants("S.T.A.L.K.E.R. 2", "Anno 117: Pax Romana")[:3],
                         ["STALKER 2", "Anno 117 Pax Romana", "Anno 117"])

    def test_save_and_list_with_source(self):
        from bridge.generate import list_templates, save_web_template, template_bindings
        with tempfile.TemporaryDirectory() as d:
            tpl = web.to_template("Testspiel", web.parse_page(LIST_PAGE), "https://example.com/x", "Example", "T")
            tid = save_web_template(d, "testspiel", tpl)
            self.assertEqual(tid, "web-example")
            entry = list_templates(d, "testspiel")[0]
            self.assertEqual((entry["id"], entry["web"], entry["source"]["site"]), ("web-example", True, "Example"))
            self.assertEqual(template_bindings(d, "testspiel").bindings["Map"].key, "M")   # KI-Ersatzquelle
            with self.assertRaises(ValueError):
                save_web_template(d, "../böse", tpl)
            self.assertEqual(save_web_template(d, "testspiel", tpl), "web-example")       # gleiche Adresse: ersetzen
            other = dict(tpl, source=dict(tpl["source"], url="https://example.com/y"))
            self.assertEqual(save_web_template(d, "testspiel", other), "web-example-2")   # andere Seite: neu
            bad = dict(tpl, source=dict(tpl["source"], url="javascript:alert(1)"))
            save_web_template(d, "testspiel", bad)
            urls = [e["source"].get("url") for e in list_templates(d, "testspiel")]
            self.assertNotIn("javascript:alert(1)", urls)                                 # nur http(s)-Links

    def test_repo_templates_name_their_source(self):
        root = Path(__file__).resolve().parent.parent
        for f in (root / "templates").glob("*/*.json"):
            if f.stem.startswith("web-"):
                continue
            with self.subTest(template=f.name):
                self.assertTrue(json.loads(f.read_text(encoding="utf-8")).get("source", {}).get("site"))


if __name__ == "__main__":
    unittest.main()
