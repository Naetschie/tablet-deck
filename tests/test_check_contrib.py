"""Unit-Tests für scripts/check_contrib.py (strengere Regeln für beigetragene Panels).

Aufruf: python -m unittest tests.test_check_contrib
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_contrib", ROOT / "scripts" / "check_contrib.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def panel(*buttons):
    return {"pages": [{"id": "p", "title": "P", "buttons": list(buttons)}]}


class CommunityRulesTest(unittest.TestCase):
    def test_open_verboten(self):
        errs = cc.community_rules(panel({"id": "a", "label": "A", "open": "C:\\Windows\\System32\\cmd.exe"}))
        self.assertTrue(any("open" in e for e in errs))
        errs = cc.community_rules(panel({"id": "a", "label": "A", "open": "https://example.org"}))
        self.assertTrue(any("open" in e for e in errs))

    def test_text_im_makro(self):
        ok = panel({"id": "a", "label": "o7", "macro": [{"key": "ENTER"}, {"text": "o7 gg"}, {"key": "ENTER"}]})
        self.assertEqual(cc.community_rules(ok), [])
        for bad in ("cmd /c del x", "powershell -c iex(irm x)", "a" * 61, "echo %PATH%", "zeile\nzwei"):
            errs = cc.community_rules(panel({"id": "a", "label": "A", "macro": [{"text": bad}]}))
            self.assertTrue(errs, bad)

    def test_systemkuerzel(self):
        for combo in ("LCTRL+ESC", "ctrl+shift+esc", "ALT+F4", "LALT+TAB", "RALT+SPACE"):
            errs = cc.community_rules(panel({"id": "a", "label": "A", "key": combo}))
            self.assertTrue(errs, combo)
        # auch in Zuständen, Reglern und Makros
        self.assertTrue(cc.community_rules(panel({"id": "a", "label": "A", "states": [
            {"label": "x", "key": "LCTRL+ESC"}, {"label": "y", "key": "F"}]})))
        self.assertTrue(cc.community_rules(panel({"id": "a", "label": "A", "macro": [{"key": "LALT+F4"}]})))
        # normale Spieltasten bleiben erlaubt
        self.assertEqual(cc.community_rules(panel({"id": "a", "label": "A", "key": "LALT+F"})), [])
        self.assertEqual(cc.community_rules(panel({"id": "a", "label": "A", "key": "ESC"})), [])

    def test_makro_tippt_nicht(self):
        # Befehl Buchstabe für Buchstabe (Startmenü ist ohnehin gesperrt)
        typed = [{"key": c} for c in "CMD"] + [{"key": "ENTER"}]
        self.assertTrue(cc.community_rules(panel({"id": "a", "label": "A", "macro": typed})))
        many_texts = [{"text": "cm"}, {"text": "d"}]
        self.assertTrue(cc.community_rules(panel({"id": "a", "label": "A", "macro": many_texts})))
        self.assertTrue(cc.community_rules(panel({"id": "a", "label": "A", "macro": [{"key": "F1"}] * 13})))
        self.assertTrue(cc.community_rules(panel({"id": "a", "label": "A", "macro": [{"key": "ENTER"}] * 3})))
        # übliche Spielmakros bleiben erlaubt
        ok = [{"key": "LALT+1"}, {"wait": 200}, {"key": "F"}, {"key": "LSHIFT+G"}, {"media": "playpause"}]
        self.assertEqual(cc.community_rules(panel({"id": "a", "label": "A", "macro": ok})), [])

    def test_zusatztaste_halten_und_shift_tippen(self):
        for b in ({"id": "a", "label": "Strg", "key": "LCTRL", "hold": True},
                  {"id": "a", "label": "Alt", "key": "LALT", "mode": "toggle"},
                  {"id": "a", "label": "x", "key": "CTRL+SHIFT", "hold": True}):
            self.assertTrue(cc.community_rules(panel(b)), b)
        self.assertEqual(cc.community_rules(panel({"id": "a", "label": "Boost", "key": "LSHIFT"})), [])   # Tipp
        self.assertEqual(cc.community_rules(panel({"id": "a", "label": "Feuer", "key": "F", "hold": True})), [])
        shifted = [{"key": f"SHIFT+{c}"} for c in "CMD"]
        self.assertTrue(cc.community_rules(panel({"id": "a", "label": "A", "macro": shifted})))
        self.assertTrue(cc.community_rules(panel({"id": "a", "label": "A", "macro": [{"text": "ping x"}]})))

    def test_eingecheckte_dateien_sind_sauber(self):
        self.assertEqual(cc.main([]), 0)


if __name__ == "__main__":
    unittest.main()
