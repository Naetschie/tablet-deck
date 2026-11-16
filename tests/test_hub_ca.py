"""Unit-Tests für hub_ca_bundle: WLAN-CA, die der Hub per ADB an den Launcher schickt (nur öffentliche Zertifikate).

Aufruf: python -m unittest tests.test_hub_ca
"""
import base64
import logging
import tempfile
import unittest
from pathlib import Path

from bridge.__main__ import hub_ca_bundle
from bridge.tls import ensure_ca


class HubCaTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_wurzel_und_zwischen_ca_ohne_schluessel(self):
        ensure_ca(self.d)
        pem = base64.b64decode(hub_ca_bundle(self.d))
        self.assertEqual(pem.count(b"-----BEGIN CERTIFICATE-----"), 2)
        self.assertNotIn(b"PRIVATE KEY", pem)
        self.assertTrue(pem.startswith((self.d / "ca.crt").read_bytes()))   # Reihenfolge: Wurzel, dann Zwischen-CA

    def test_fehlt_oder_enthaelt_schluessel(self):
        self.assertIsNone(hub_ca_bundle(self.d))                 # noch keine CA
        ensure_ca(self.d)
        (self.d / "inter.crt").write_bytes((self.d / "inter.crt").read_bytes() + (self.d / "inter.key").read_bytes())
        self.assertIsNone(hub_ca_bundle(self.d))                 # versehentlich ein Schlüssel dabei: nie senden


if __name__ == "__main__":
    unittest.main()
