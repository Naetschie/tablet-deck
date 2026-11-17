"""KI-Anbieter (bridge/ai_providers.py): Einstellungen, Schlüssel je Anbieter, OpenAI über die Responses-API -
ohne Netz (Platzhalter-Antworten)."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from bridge import ai_bindings, ai_providers, ai_template

OKEY = "sk-proj-" + "a" * 40


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(payload, calls=None, status=None):
    def op(req, timeout=None):
        if calls is not None:
            calls.append(req)
        if status:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, io.BytesIO(b"secret echo " + OKEY.encode()))
        return FakeResp(json.dumps(payload).encode())
    return op


def message(text, kind="output_text"):
    return {"status": "completed", "output": [{"type": "web_search_call"}, {"type": "message", "content": [
        {"type": kind, "text": text, "refusal": text}]}]}


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = self.d.name

    def tearDown(self):
        self.d.cleanup()

    def test_settings_and_keys_per_provider(self):
        self.assertEqual(ai_providers.settings(self.root)["provider"], "anthropic")
        ai_providers.save_settings(self.root, "openai", "gpt-test-1")
        self.assertEqual(ai_providers.settings(self.root), {"provider": "openai", "openai_model": "gpt-test-1"})
        for bad in (("x", None), (None, "böses modell!")):
            with self.assertRaises(ValueError):
                ai_providers.save_settings(self.root, *bad)
        with self.assertRaises(ValueError):
            ai_providers.save_key(self.root, "openai", "sk-ant-" + "b" * 40)       # Anthropic-Schlüssel bei OpenAI
        ai_providers.save_key(self.root, "openai", OKEY)
        self.assertEqual(ai_providers.key_status(self.root, "openai"), {"set": True})
        self.assertEqual(ai_providers.key_status(self.root, "anthropic"), {"set": False})
        self.assertTrue((Path(self.root) / "secrets" / "openai.key").is_file())
        ai_providers.delete_key(self.root, "openai")
        self.assertEqual(ai_providers.key_status(self.root, "openai"), {"set": False})

    def test_openai_json_request_and_errors(self):
        ai_providers.save_key(self.root, "openai", OKEY)
        calls = []
        out = ai_providers.openai_json(self.root, "sys", "user", {"type": "object"}, "panel",
                                       opener=opener_for(message('{"a": 1}'), calls))
        self.assertEqual(out, {"a": 1})
        body = json.loads(calls[0].data)
        self.assertEqual(calls[0].full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(body["model"], ai_providers.DEFAULT_OPENAI_MODEL)
        with self.assertRaises(ValueError):
            ai_providers.openai_json(self.root, "s", "u", {}, opener=opener_for(message("nein", "refusal")))
        for code in (401, 429, 404, 500):
            with self.assertRaises(ValueError) as cm:
                ai_providers.openai_json(self.root, "s", "u", {}, opener=opener_for({}, status=code))
            self.assertNotIn(OKEY, str(cm.exception))                     # nie der Schlüssel in Meldungen
        self.assertEqual(ai_providers.check_openai(self.root, opener=opener_for({"data": []}))["ok"], True)

    def test_web_json_from_text(self):
        ai_providers.save_key(self.root, "openai", OKEY)
        calls = []
        txt = 'Hier: ```json\n{"bindings": [{"action": "Jump"}]}\n```'
        out = ai_providers.openai_web_json(self.root, "s", "u", opener=opener_for(message(txt), calls))
        self.assertEqual(out["bindings"][0]["action"], "Jump")
        self.assertEqual(json.loads(calls[0].data)["tools"], [{"type": "web_search"}])

    def test_features_route_to_openai(self):
        ai_providers.save_settings(self.root, "openai")
        spec = {"title": "T", "sections": [{"title": "S", "areas": [{"title": "A", "items": [
            {"kind": "key", "label": "Laden", "action": "a", "action2": None, "size": "m", "style": "",
             "guard": "none"}]}]}]}
        with mock.patch.object(ai_providers, "openai_json", return_value=spec) as oj:
            out = ai_template.generate_template(self.root, "Spiel")
        self.assertTrue(oj.called)
        self.assertEqual(out["sections"][0]["areas"][0]["items"][0]["action"], "a")
        page = "<ul><li>Reload: R</li><li>Use: E</li><li>Map: M</li></ul>"
        rows = [{"area": "", "action": a, "key_text": k, "url": "https://x.example.com/c"}
                for a, k in (("Reload", "R"), ("Use", "E"), ("Map", "M"))]
        with mock.patch.object(ai_providers, "openai_web_json", return_value={"bindings": rows}), \
                mock.patch.object(ai_bindings.web, "fetch", lambda u: page):
            res = ai_bindings.lookup(self.root, "Spiel")
        self.assertEqual(len(res["rows"]), 3)


if __name__ == "__main__":
    unittest.main()
