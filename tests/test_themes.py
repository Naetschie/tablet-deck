"""Farbschemas: Kontrast jeder Kombination, Abstand zu den festen Zustandsfarben, Speichern, Auslieferung."""
import json
import logging
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bridge import themes
from bridge.__main__ import Bridge, device_theme
from bridge.devices import Devices

ROOT = Path(__file__).resolve().parent.parent
TOKENS = (ROOT / "web/lib/tokens.css").read_text("utf-8")
STATES = {"warn": "#F0923A", "bad": "#E5484D", "ok": "#3DDC84"}
ALL = [{"surface": s, "accent": a} for s in themes.SURFACES for a in themes.ACCENTS]


def lin(h):
    return [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in (v / 255 for v in themes.rgb(h))]


def lum(h):
    r, g, b = lin(h)
    return .2126 * r + .7152 * g + .0722 * b


def contrast(a, b):
    a, b = sorted((lum(a), lum(b)), reverse=True)
    return (a + .05) / (b + .05)


def lab(h):
    r, g, b = lin(h)
    xyz = ((.4124 * r + .3576 * g + .1805 * b) / .95047, .2126 * r + .7152 * g + .0722 * b,
           (.0193 * r + .1192 * g + .9505 * b) / 1.08883)
    x, y, z = (t ** (1 / 3) if t > .008856 else 7.787 * t + 16 / 116 for t in xyz)
    return 116 * y - 16, 500 * (x - y), 200 * (y - z)


class ContrastTest(unittest.TestCase):
    def test_lesbar(self):
        for t in ALL:
            c = themes.colors(t)
            with self.subTest(t):
                for f in ("bg", "s1", "s2", "s3"):
                    self.assertGreaterEqual(contrast(c["tx"], c[f]), 7, f)
                for f in ("bg", "s1", "s2"):
                    self.assertGreaterEqual(contrast(c["dim"], c[f]), 4.5, f)
                self.assertGreaterEqual(contrast(c["acTx"], c["ac"]), 4.5)
                self.assertGreaterEqual(contrast(c["ac"], c["s3"]), 3)
                # Regler: Text auf der getönten Füllung (web/lib/ui.css, 30 % Akzent auf --s3)
                self.assertGreaterEqual(contrast(c["tx"], themes.mix(c["ac"], c["s3"], .3)), 4.5)
                for n, s in STATES.items():   # feste Zustandsfarben bleiben auf Tasten sichtbar
                    self.assertGreaterEqual(contrast(s, c["s2"]), 3, n)

    def test_akzent_nicht_wie_zustand(self):
        for n, (_, ac) in themes.ACCENTS.items():
            for s, col in STATES.items():
                d = sum((x - y) ** 2 for x, y in zip(lab(ac), lab(col))) ** .5
                self.assertGreaterEqual(d, 30, f"{n} zu nah an {s}")

    def test_standard_wie_tokens_css(self):
        c = themes.colors(themes.DEFAULT)
        for k, v in c.items():
            m = re.search(r"--%s: ([^;]+);" % k, TOKENS)
            self.assertIsNotNone(m, k)
            self.assertEqual(m.group(1), v, k)
        for v in STATES.values():
            self.assertIn(v, TOKENS)

    def test_launcher_standardfarben(self):
        java = (ROOT / "android/src/app/tabletdeck/launcher/HomeActivity.java").read_text("utf-8")
        c = themes.colors(themes.DEFAULT)
        for name, key in (("BG", "bg"), ("PANEL", "s1"), ("S2", "s2"), ("S3", "s3"), ("LINE", "line"), ("TEXT", "tx"),
                          ("DIM", "dim"), ("ACCENT", "ac"), ("ACCENT_TX", "acTx")):
            self.assertRegex(java, r"\b%s = 0xFF%s\b" % (name, c[key][1:]))


class FormatTest(unittest.TestCase):
    def test_css(self):
        self.assertNotIn("{", themes.css(themes.DEFAULT))
        self.assertNotIn("{", themes.css({"surface": "standard", "accent": "x}"}))
        out = themes.css({"surface": "schwarz", "accent": "pink"})
        self.assertIn("--bg: #000000;", out)
        self.assertIn("--ac: #F28BCB;", out)
        self.assertNotIn("--warn", out)

    def test_werte_fuer_launcher(self):
        # dieselbe Prüfung macht HomeActivity.setTheme
        for t in ALL:
            for k, v in themes.colors(t).items():
                self.assertRegex(k, r"\A[a-zA-Z0-9]{1,10}\Z")
                self.assertRegex(v, r"\A(#[0-9A-Fa-f]{6}|rgba\([0-9., ]{5,30}\))\Z")

    def test_dashboard(self):
        text = (ROOT / "dashboards/deck.json").read_text("utf-8")
        self.assertEqual(themes.recolor(text, themes.DEFAULT), text)
        new = themes.recolor(text, {"surface": "kontrast", "accent": "violett"})
        self.assertNotIn("#4FB3FF", new)
        self.assertIn("#A99BFF", new)
        for s in ("#3DDC84", "#F0923A", "#E5484D"):   # Zustandsfarben unverändert
            self.assertEqual(new.count(s), text.count(s))
        self.assertNotIn("79,179,255", new.replace(" ", ""))   # auch getönte Flächen
        self.assertEqual(len(json.loads(new)["widgets"]), len(json.loads(text)["widgets"]))


    def test_dashboard_nur_bekannte_farben(self):
        # neue Farbe in deck.json? Dann in themes.recolor aufnehmen oder eine Zustandsfarbe nehmen
        text = (ROOT / "dashboards/deck.json").read_text("utf-8")
        known = {v.upper() for v in themes.colors(themes.DEFAULT).values()} | set(STATES.values()) | {"#8AC9FF"}
        for c in re.findall(r'"(#[0-9A-Fa-f]+)"', text):
            self.assertIn(c.upper(), known)

    def test_einmal_melden(self):
        with self.assertLogs("bridge", "ERROR") as cm:
            for _ in range(3):
                device_theme({"tablet_theme": "einmal-melden"}, None)
        self.assertEqual(len(cm.output), 1)


class HttpTest(unittest.TestCase):
    def css(self, cookie):
        b = SimpleNamespace(cfg={"tablet_theme": {"surface": "schwarz", "accent": "cyan"}},
                            devices=SimpleNamespace(theme=lambda dev, default: default))
        return themes.css(Bridge.request_theme(b, SimpleNamespace(headers={"Cookie": cookie} if cookie else {})))

    def test_nur_mit_geraetekennung(self):
        self.assertIn("--ac: #2FD3D8;", self.css("deckdev=TAB1"))
        self.assertNotIn("--ac", self.css(None))            # Editor am PC
        self.assertNotIn("--ac", self.css("deckdev=../x"))

    def test_launcher_ohne_kennung_wie_seiten(self):
        b = SimpleNamespace(cfg={"tablet_theme": {"surface": "schwarz", "accent": "cyan"}})
        self.assertEqual(Bridge.theme_msg(b, None)["colors"], themes.colors(themes.DEFAULT))


class DeviceTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "devices.json"
        self.d = Devices(self.path)
        self.d.see("TAB1")

    def tearDown(self):
        self.tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_speichern_und_vorrang(self):
        t = {"surface": "schwarz", "accent": "cyan"}
        self.assertEqual(device_theme({}, "TAB1", self.d), themes.DEFAULT)
        self.assertEqual(device_theme({"tablet_theme": t}, "TAB1", self.d), t)
        self.assertEqual(device_theme({"tablet_theme": "bunt"}, "TAB1", self.d), themes.DEFAULT)
        u = {"surface": "kontrast", "accent": "weiss"}
        self.assertTrue(self.d.set_theme("TAB1", u))
        self.assertEqual(device_theme({"tablet_theme": t}, "TAB1", self.d), u)
        self.assertEqual(json.loads(self.path.read_text("utf-8"))["devices"]["TAB1"]["theme"], u)
        for bad in ({"surface": "x", "accent": "blau"}, {"surface": "schwarz"}, "schwarz", None,
                    {"surface": ["schwarz"], "accent": "blau"}):
            self.assertFalse(self.d.set_theme("TAB1", bad))
        self.assertFalse(self.d.set_theme("FREMD", u))
        self.d.data["TAB1"]["theme"] = {"surface": 3}
        self.assertEqual(device_theme({}, "TAB1", self.d), themes.DEFAULT)
        self.assertEqual(device_theme({}, None, self.d), themes.DEFAULT)

    def test_nachricht(self):
        self.d.set_theme("TAB1", {"surface": "schwarz", "accent": "pink"})
        b = SimpleNamespace(cfg={}, devices=self.d)
        m = Bridge.theme_msg(b, "TAB1")
        self.assertEqual((m["t"], m["colors"]["ac"]), ("theme", "#F28BCB"))
        self.assertEqual(Bridge.theme_msg(b, None)["colors"]["ac"], "#4FB3FF")


if __name__ == "__main__":
    unittest.main()
