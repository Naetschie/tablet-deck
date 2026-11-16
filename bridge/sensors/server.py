"""HTTP-Endpunkt des Sensor-Helfers: nur 127.0.0.1, nur mit Token.

GET  /values                  -> {"time", "values": [{id, name, value, unit, min, max}], "sources": {…}}
POST /target {"pid": n} | {"exe": "Spiel.exe"} | {}   -> Ziel für PresentMon setzen bzw. löschen
"""
import hmac
import json
import logging
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .presentmon_src import clean_target

log = logging.getLogger("sensors")

HOST = "127.0.0.1"      # bewusst fest: der Dienst läuft später mit Adminrechten
MAX_BODY = 1024


def load_or_create_token(path):
    """Token aus Datei (bleibt über Neustarts gleich; neu erzeugen = Datei löschen). Nie loggen."""
    try:
        s = path.read_text(encoding="ascii").strip()
        if len(s) >= 32:
            return s
    except (OSError, ValueError):
        pass
    s = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s + "\n", encoding="ascii")
    log.info("Neu erzeugt: %s (Token für den Hub)", path)
    return s


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False     # unter Windows dürfte sonst ein zweiter Prozess denselben Port belegen


def make_server(collector, token, port, presentmon=None):
    expected = ("Bearer " + token).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "sensord"
        sys_version = ""
        timeout = 15                # hängende Verbindungen nicht ewig halten

        def log_message(self, fmt, *args):      # kein Zugriffslog (jede Sekunde eine Abfrage)
            pass

        def _send(self, status, obj):
            body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if status >= 400:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            self.wfile.write(body)

        def _allowed_quiet(self):
            given = self.headers.get("Authorization", "").encode("utf-8", "replace")
            return hmac.compare_digest(given, expected)

        def _allowed(self):
            if self._allowed_quiet():
                return True
            self._send(401, {"error": "Token fehlt oder falsch"})
            return False

        def do_GET(self):
            if not self._allowed():
                return
            if self.path.split("?", 1)[0] == "/values":
                self._send(200, collector.snapshot())
            else:
                self._send(404, {"error": "unbekannt"})

        def do_POST(self):
            # Körper zuerst lesen (höchstens MAX_BODY): Ungelesene Daten beim Schließen lassen Windows die
            # Verbindung mit RST abbrechen - der Client sähe dann statt 401/404 nur "Verbindung abgebrochen".
            try:
                n = int(self.headers.get("Content-Length", ""))
                if not 0 <= n <= MAX_BODY:
                    raise ValueError
            except ValueError:
                self._send(400 if self._allowed_quiet() else 401, {"error": "Länge"})
                return
            body = self.rfile.read(n)
            if not self._allowed():
                return
            if self.path.split("?", 1)[0] != "/target" or presentmon is None:
                self._send(404, {"error": "unbekannt"})
                return
            try:
                target = clean_target(json.loads(body or b"{}"))
            except ValueError as e:     # auch json.JSONDecodeError, UnicodeDecodeError
                self._send(400, {"error": str(e) if str(e).startswith(("pid", "exe", "Objekt")) else "ungültig"})
                return
            presentmon.set_target(target)
            self._send(200, {"ok": True, "target": dict([target]) if target else None})

    return _Server((HOST, port), Handler)
