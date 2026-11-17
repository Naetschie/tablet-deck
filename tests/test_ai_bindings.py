"""KI-Suche nach Standardtasten (bridge/ai_bindings.py) - ohne Netz und ohne API: Platzhalter-Client und -Seiten."""
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from bridge import ai_bindings

PAGE = """<html><body><h2>Combat</h2><table>
<tr><td>Reload</td><td>R</td></tr><tr><td>Sprint</td><td>Left Shift</td></tr><tr><td>Quick Save</td><td>F5</td></tr>
<tr><td>Open Map</td><td>M</td></tr></table></body></html>"""
URL = "https://wiki.example.com/controls"


def row(action, key, url=URL, area="Combat"):
    return {"area": area, "action": action, "key_text": key, "url": url}


class FakeClient:
    def __init__(self, responses):
        self.calls, self._r = [], list(responses)
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return self._r.pop(0)


def report(rows, stop="tool_use"):
    return NS(stop_reason=stop, content=[NS(type="tool_use", name="report_controls", input={"bindings": rows})])


class VerifyTest(unittest.TestCase):
    def test_only_rows_found_on_page(self):
        rows = [row("Reload", "R"), row("Sprint", "Left Shift"), row("Quick Save", "F5"),
                row("Jump", "Space"),                       # steht nicht auf der Seite -> erfunden
                row("Open Map", "N"),                       # falsche Taste -> verworfen
                row("Reload", "R", url="https://other.example.com/x"),   # Seite nicht abrufbar
                row("Fire", "Left Mouse Button")]           # keine Tastatur
        fetched = []

        def fake_fetch(u):
            fetched.append(u)
            if u == URL:
                return PAGE
            raise ValueError("nicht erreichbar")
        ok, urls, dropped = ai_bindings.verify(rows, fetch=fake_fetch)
        self.assertEqual([(a, k) for _, a, k, _h in ok], [("Reload", "R"), ("Sprint", "LSHIFT"), ("Quick Save", "F5")])
        self.assertEqual((urls, dropped), ([URL], 4))
        self.assertEqual(sorted(fetched), sorted([URL, "https://other.example.com/x"]))   # jede Seite nur einmal

    def test_no_partial_keys_or_cross_matches(self):
        page = """<ul><li>Copy: Ctrl + C</li><li>Use: E</li><li>Jump: Space Bar</li></ul>
        <p>Use the jump key because it helps. Press E to use and Space to jump.</p>"""
        rows = [row("Copy", "Ctrl"),             # Teil einer Kombination
                row("Use", "Space"),             # Kreuzzuordnung
                row("Jump", "Space"),            # gleiche Taste, andere Schreibweise -> bestätigt
                row("Use", "E")]
        ok, _, dropped = ai_bindings.verify(rows, fetch=lambda u: page)
        self.assertEqual([(a, k) for _, a, k, _h in ok], [("Jump", "SPACE"), ("Use", "E")])
        self.assertEqual(dropped, 2)
        q = [row("Use", "E", url=URL + "?x=1"), row("Jump", "Space", url=URL + "#a")]
        self.assertEqual(ai_bindings.verify(q, fetch=lambda u: page)[0], [])   # Links mit Query/Fragment nicht

    def test_lookup_with_pause_and_template(self):
        paused = NS(stop_reason="pause_turn", content=[NS(type="server_tool_use", name="web_search")])
        c = FakeClient([paused, report([row("Reload", "R"), row("Sprint", "Left Shift"), row("Quick Save", "F5")])])
        with mock.patch.object(ai_bindings.web, "fetch", lambda u: PAGE):
            res = ai_bindings.lookup(".", "Testspiel", client=c)
        self.assertEqual(len(c.calls), 2)                                       # pause_turn fortgesetzt
        second = c.calls[1]["messages"]
        self.assertEqual([m["role"] for m in second], ["user", "assistant"])   # kein „weiter“-Text
        tools = {t.get("type", t.get("name")) for t in c.calls[0]["tools"]}
        self.assertTrue({"web_search_20260209", "web_fetch_20260209", "report_controls"} <= tools)
        self.assertEqual(c.calls[0]["model"], "claude-opus-5-5")
        self.assertEqual(len(res["rows"]), 3)
        self.assertIn("geprüft", res["template"]["source"]["note"])
        self.assertTrue(res["template"]["source"]["site"].startswith("KI-Suche"))

    def test_too_few_confirmed_and_refusal(self):
        c = FakeClient([report([row("Jump", "Space")])])
        with mock.patch.object(ai_bindings.web, "fetch", lambda u: PAGE):
            with self.assertRaises(ValueError) as cm:
                ai_bindings.lookup(".", "Testspiel", client=c)
        self.assertIn("bestätigen", str(cm.exception))
        with self.assertRaises(ValueError):
            ai_bindings.lookup(".", "X", client=FakeClient([NS(stop_reason="refusal", content=[])]))


if __name__ == "__main__":
    unittest.main()
