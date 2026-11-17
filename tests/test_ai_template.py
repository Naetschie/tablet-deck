"""Tests für die KI-Vorlage (bridge/ai_template.py) - ohne Netzwerk, mit Fake-Client.

Aufruf: python -m unittest tests.test_ai_template
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from bridge import ai_template
from bridge.autolayout import build, is_semantic
from bridge.layout import validate_layout


def item(label, action, kind="key", action2=None, size="m", style="", guard="none"):
    return {"kind": kind, "label": label, "action": action, "action2": action2, "size": size, "style": style,
            "guard": guard}


def reply(sections, stop="end_turn"):
    text = json.dumps({"title": "Testspiel", "sections": sections})
    return NS(stop_reason=stop, content=[NS(type="text", text=text)])


def sec(title, *areas):
    return {"title": title, "areas": [{"title": a[0], "items": list(a[1:])} for a in areas]}


class FakeClient:
    def __init__(self, response):
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))
        self._response = response

    def _create(self, **kw):
        self.calls.append(kw)
        return self._response


class AiTemplateTest(unittest.TestCase):
    def test_gueltige_antwort_wird_semantische_vorlage(self):
        s = [sec("Kampf", ("Waffen", item("Laden", "a_reload", size="l", style="accent"),
                                     item("Schild", "a_less", kind="pair", action2="a_more"),
                                     item("Zerstören", "a_boom", style="danger", guard="hold")))]
        out = ai_template.generate_template(".", "Testspiel", client=FakeClient(reply(s)))
        self.assertTrue(is_semantic(out))
        its = out["sections"][0]["areas"][0]["items"]
        self.assertEqual(its[0], {"label": "Laden", "action": "a_reload", "style": "accent", "size": "l"})
        self.assertEqual([x["action"] for x in its[1]["pair"]], ["a_less", "a_more"])
        self.assertEqual((its[2]["style"], its[2]["mode"]), ("danger", "hold-confirm"))
        for st in ("areas", "grid"):
            validate_layout(build(out, st))

    def test_nie_tasten_und_leeres_verworfen(self):
        bad = dict(item("X", "a_x"), key="F5")   # selbst wenn die KI eine Taste mitschickt
        s = [sec("A", ("B", bad, item("", ""), "kaputt")), sec("A", ("C", item("Y", "a_y"))), sec("Leer", ("D",))]
        out = ai_template.generate_template(".", "S", client=FakeClient(reply(s)))
        self.assertNotIn("key", json.dumps(out))
        titles = [x["title"] for x in out["sections"]]
        self.assertEqual(len(titles), 2)
        self.assertEqual(len(set(titles)), 2)              # doppelte Seitentitel eindeutig gemacht
        with self.assertRaises(ValueError):
            ai_template.generate_template(".", "S", client=FakeClient(reply([sec("L", ("x",))])))

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
        c = FakeClient(reply([sec("P", ("B", item("X", "v_lights")))]))
        ai_template.generate_template(".", "Stalker 2", hint="h" * 5000, client=c, style_prompt="Nur große Tasten.",
                                      actions=[{"action": "v_lights", "key": "LALT+L"},
                                               {"action": "v_boost", "key": None}])
        kw = c.calls[0]
        text = kw["messages"][0]["content"]
        self.assertIn("v_lights (LALT+L)", text)
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
        self.assertTrue(kw["system"].startswith(ai_template.FIXED_PROMPT))      # fester Teil immer
        self.assertIn("Nur große Tasten.", kw["system"])
        self.assertNotIn(ai_template.DEFAULT_STYLE_PROMPT, kw["system"])     # änderbarer Teil ersetzt
        c2 = FakeClient(reply([sec("P", ("B", item("X", "v_lights")))]))
        ai_template.generate_template(".", "S", client=c2)
        self.assertIn(ai_template.DEFAULT_STYLE_PROMPT, c2.calls[0]["system"])
        self.assertNotIn("bestem Wissen", c2.calls[0]["messages"][0]["content"])


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
