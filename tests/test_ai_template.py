"""Tests für die KI-Vorlage (bridge/ai_template.py) - ohne Netzwerk, mit Fake-Client.

Aufruf: python -m unittest tests.test_ai_template
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from bridge import ai_template
from bridge.layout import validate_layout


def btn(id, label, key="F5", **kw):
    b = {"id": id, "label": label, "action": "a_" + id, "key": key, "mode": "tap",
         "style": "", "group": None, "hold": False}
    b.update(kw)
    return b


def reply(pages, stop="end_turn"):
    text = json.dumps({"title": "Testspiel", "pages": pages})
    return NS(stop_reason=stop, content=[NS(type="text", text=text)])


class FakeClient:
    def __init__(self, response):
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))
        self._response = response

    def _create(self, **kw):
        self.calls.append(kw)
        return self._response


class AiTemplateTest(unittest.TestCase):
    def test_gueltige_antwort(self):
        pages = [{"id": "main", "title": "Haupt", "buttons": [
            btn("licht", "LICHT", "L", mode="toggle", group="Schiff"),
            btn("laden", "SCHNELLLADEN", "F9", mode="hold-confirm", style="danger")]}]
        out = ai_template.generate_template(".", "Testspiel", client=FakeClient(reply(pages)))
        validate_layout(out)
        self.assertEqual(out["holdMs"], 1000)
        b = out["pages"][0]["buttons"]
        self.assertEqual(out["pages"][0]["type"], "grid")
        self.assertNotIn("style", b[0])
        self.assertEqual(b[0]["group"], "Schiff")
        self.assertNotIn("hold", b[0])
        self.assertEqual(b[1]["style"], "danger")

    def test_ungueltige_taste_entfernt(self):
        pages = [{"id": "p", "title": "P", "buttons": [btn("x", "X", "GIBTSNICHT+Q"), btn("y", "Y", None)]}]
        out = ai_template.generate_template(".", "S", client=FakeClient(reply(pages)))
        for b in out["pages"][0]["buttons"]:
            self.assertNotIn("key", b)

    def test_doppelte_ids(self):
        pages = [{"id": "p", "title": "A", "buttons": [btn("x", "A"), btn("x", "B")]},
                 {"id": "p", "title": "B", "buttons": [btn("x", "C")]},
                 {"id": "leer", "title": "Leer", "buttons": []}]
        out = ai_template.generate_template(".", "S", client=FakeClient(reply(pages)))
        self.assertEqual(len(out["pages"]), 2)
        ids = [b["id"] for p in out["pages"] for b in p["buttons"]]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(len({p["id"] for p in out["pages"]}), 2)

    def test_refusal_und_max_tokens(self):
        with self.assertRaisesRegex(ValueError, "abgelehnt"):
            ai_template.generate_template(".", "S", client=FakeClient(reply([], "refusal")))
        with self.assertRaisesRegex(ValueError, "zu lang"):
            ai_template.generate_template(".", "S", client=FakeClient(reply([], "max_tokens")))

    def test_fehlender_schluessel(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as cm:
                ai_template.generate_template(d, "S")
            self.assertIn("Einstellungen", str(cm.exception))
            (Path(d) / "secrets").mkdir()
            (Path(d) / "secrets" / "anthropic.key").write_text("   \n")   # leer = fehlt
            with self.assertRaises(ValueError):
                ai_template.generate_template(d, "S")

    def test_actions_im_user_text_und_parameter(self):
        pages = [{"id": "p", "title": "P", "buttons": [btn("x", "X")]}]
        c = FakeClient(reply(pages))
        ai_template.generate_template(".", "Stalker 2", hint="h" * 5000, client=c,
                                      actions=[{"action": "v_lights", "key": "LALT+L"},
                                               {"action": "v_boost", "key": None}])
        kw = c.calls[0]
        text = kw["messages"][0]["content"]
        self.assertIn("v_lights: LALT+L", text)
        self.assertIn("v_boost", text)
        self.assertIn("Stalker 2", text)
        self.assertLess(len(text), 2400)
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(kw["output_config"]["effort"], "medium")
        self.assertNotIn("thinking", kw)
        self.assertNotIn("temperature", kw)


class KeyTest(unittest.TestCase):
    """Schlüssel verwalten (Editor, ⚙ Einstellungen): nur Format prüfen, speichern, entfernen, Status."""
    KEY = "sk-ant-api03-" + "x" * 40

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_speichern_status_entfernen(self):
        self.assertEqual(ai_template.key_status(self.root), {"set": False})
        with self.assertLogs("ai_template", "INFO") as cm:
            ai_template.save_key(self.root, "  " + self.KEY + "\n")
        self.assertNotIn(self.KEY, "\n".join(cm.output))          # nie ins Log
        self.assertEqual((self.root / "secrets" / "anthropic.key").read_text(encoding="utf-8").strip(), self.KEY)
        self.assertEqual(ai_template.key_status(self.root), {"set": True})
        self.assertEqual(list((self.root / "secrets").iterdir()), [self.root / "secrets" / "anthropic.key"])   # kein .tmp
        ai_template.delete_key(self.root)
        self.assertEqual(ai_template.key_status(self.root), {"set": False})
        ai_template.delete_key(self.root)                          # zweimal ist kein Fehler

    def test_falsches_format_abgelehnt_ohne_echo(self):
        for bad in (None, 42, "", "abc", "sk-ant-kurz", "sk-ant-" + "x" * 30 + " mit leerzeichen", "sk-proj-" + "x" * 40):
            with self.assertRaises(ValueError) as cm:
                ai_template.save_key(self.root, bad)
            if isinstance(bad, str) and bad:
                self.assertNotIn(bad, str(cm.exception))
        self.assertFalse((self.root / "secrets" / "anthropic.key").exists())

    def test_pruefen(self):
        import anthropic
        ok = NS(models=NS(list=lambda limit: []))
        self.assertEqual(ai_template.check_key(self.root, ok)["ok"], True)

        def deny(limit):
            raise anthropic.AuthenticationError("nein", response=NS(status_code=401, headers={}, request=None), body=None)
        res = ai_template.check_key(self.root, NS(models=NS(list=deny)))
        self.assertEqual(res, {"ok": False, "msg": "Schlüssel ungültig oder widerrufen"})
        with self.assertRaises(ValueError):                         # ohne Schlüssel: klare Meldung
            ai_template.check_key(self.root)


if __name__ == "__main__":
    unittest.main()
