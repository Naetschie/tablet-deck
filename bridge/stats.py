"""PC-Werte für die Tablet-Seiten: Anbindung an den Sensor-Helfer (bridge/sensors, Port 8768).

Seiten melden sich über /ws mit {"t":"stats_sub"} an (und mit {"t":"stats_unsub"} ab; beim Trennen automatisch).
Solange mindestens eine Seite abonniert hat, fragt der Hub jede Sekunde GET /values beim Sensor-Helfer ab und
schickt den Abonnenten
    {"t":"stats", "values": {id: Wert}, "sources": {...}, "meta": {id: {name, unit, min, max}}}
"meta" kommt nur beim ersten Mal je Abonnent und wieder, wenn es sich ändert.

Ist der Helfer nicht erreichbar (Token-Datei fehlt, Dienst aus, falsches Token), liefert der Hub selbst die
Grundwerte über psutil (cpu.load, ram.*, net.*) im gleichen Format; der Helfer wird alle 5 s erneut versucht.
Fehler werden nur beim Zustandswechsel geloggt. Das Token (secrets/sensors.key) wird nie geloggt.

Spielwechsel: set_game() teilt dem Helfer das Spiel für PresentMon mit (POST /target {"exe": ...} bzw. {}).
Ein Fehler dabei stört die Spielerkennung nicht (alles läuft im Hintergrund).
"""
import asyncio
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger("stats")

DEFAULT_PORT = 8768
INTERVAL_S = 1.0
RAW_PREFIX = "lhm."     # Rohwerte des Sensor-Helfers (bridge/sensors/mapping.py raw_items)
RETRY_S = 5.0
HTTP_TIMEOUT_S = 1.5   # deutlich unter STALE_MS (4 s) der Seite, sonst flackert sie bei hängendem Helfer
SEND_TIMEOUT_S = 2.0
EXE_NAME = re.compile(r"[\w .()+&'\-]{1,120}\.exe", re.IGNORECASE)   # wie bridge/sensors/presentmon_src.py

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # nie über einen Proxy


class SensorError(Exception):
    """Helfer nicht nutzbar. Text = Kurzgrund für das Log (nie Token oder Antwortinhalt)."""

    def __init__(self, reason, code=None):
        super().__init__(reason)
        self.reason, self.code = reason, code


def read_token(path):
    """Token aus der Datei oder None. Nie loggen."""
    try:
        with open(path, encoding="ascii") as f:
            s = f.read().strip()
    except (OSError, ValueError):
        return None
    return s or None


def _request(port, token, path, body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", headers={"Authorization": "Bearer " + token},
        data=None if body is None else json.dumps(body).encode("utf-8"),
        method="GET" if body is None else "POST")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with _opener.open(req, timeout=HTTP_TIMEOUT_S) as r:
            return json.loads(r.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SensorError("Token abgelehnt" if e.code == 401 else f"HTTP {e.code}", e.code) from None
    except (OSError, ValueError) as e:     # URLError/Timeout sind OSError, JSON-Fehler ValueError
        raise SensorError("nicht erreichbar" if isinstance(e, OSError) else "ungültige Antwort") from None


def fetch_values(port, token):
    """GET /values -> {"values": [...], "sources": {...}} (blockierend, für den Executor)."""
    data = _request(port, token, "/values")
    if not isinstance(data, dict) or not isinstance(data.get("values"), list):
        raise SensorError("ungültige Antwort")
    return data


def post_target(port, token, exe):
    """POST /target {"exe": name} bzw. {} (blockierend, für den Executor)."""
    _request(port, token, "/target", {"exe": exe} if exe else {})


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else None


def convert(items):
    """Werteliste des Helfers [{id,name,value,unit,min,max}] -> (values {id: Wert}, meta {id: {...}}).
    Unbrauchbare Einträge (keine Zahl, keine ID) werden übersprungen."""
    values, meta = {}, {}
    for it in items or []:
        if not isinstance(it, dict) or not isinstance(it.get("id"), str):
            continue
        v = _num(it.get("value"))
        if v is None:
            continue
        values[it["id"]] = v
        meta[it["id"]] = {"name": it.get("name") if isinstance(it.get("name"), str) else it["id"],
                          "unit": it.get("unit") if isinstance(it.get("unit"), str) else "",
                          "min": _num(it.get("min")), "max": _num(it.get("max"))}
        if isinstance(it.get("group"), str) and it["group"]:
            meta[it["id"]]["group"] = it["group"][:80]     # Bauteil der Rohwerte (lhm.*), Gruppe im Editor
    return values, meta


def psutil_fallback():
    """Grundwerte ohne Sensor-Helfer: gleiche Quellen und Zuordnung wie im Helfer - psutil und, falls
    vorhanden, NVML (GPU-Werte brauchen keine Adminrechte). Fällt NVML aus, bleiben die psutil-Werte."""
    from .sensors.mapping import DEFAULTS, resolve
    from .sensors.psutil_src import PsutilSource
    src = PsutilSource()
    src.start()
    state = {"gpu": None, "next": 0.0, "logged": False}

    def start_gpu():
        # Autostart: der Treiber ist evtl. noch nicht bereit - alle 60 s neu versuchen statt nie wieder
        state["next"] = time.monotonic() + 60
        try:
            from .sensors.nvml_src import NvmlSource
            gpu = NvmlSource()
            gpu.start()
            state["gpu"] = gpu
        except Exception as e:  # noqa: BLE001 - kein Paket, keine Karte, Treiber noch nicht bereit
            if not state["logged"]:
                log.info("Rückfall ohne GPU-Werte (%s)", e.__class__.__name__)
                state["logged"] = True

    start_gpu()

    def read():
        raw = src.read()
        if state["gpu"] is None and time.monotonic() >= state["next"]:
            start_gpu()
        if state["gpu"] is not None:
            try:
                raw = raw + state["gpu"].read()
            except Exception:  # noqa: BLE001 - GPU-Werte fehlen dann in diesem Durchlauf
                pass
        return resolve(DEFAULTS, raw)
    return read


def pick_exe(names, procs):
    """Programmname fürs Ziel: bevorzugt ein gerade laufender (procs: kleingeschriebene Namen), sonst der erste
    brauchbare. Nur reine Dateinamen (der Name landet auf einer Befehlszeile des Helfers)."""
    ok = [n for n in names if isinstance(n, str) and "\\" not in n and "/" not in n and EXE_NAME.fullmatch(n)]
    for n in ok:
        if procs and n.lower() in procs:
            return n
    return ok[0] if ok else None


def exe_from_paths(paths, folder):
    """Laufendes Programm unterhalb des Spielordners (Bibliotheksspiele ohne bekannten exe-Namen)."""
    from . import library
    if not folder:
        return None
    base = os.path.normcase(os.path.normpath(folder)).rstrip("\\/") + os.sep
    for p in paths or []:
        if os.path.normcase(os.path.normpath(p)).startswith(base) and not library.is_helper(p):
            return pick_exe([os.path.basename(p)], None)
    return None


class Stats:
    def __init__(self, root, cfg, profiles=None, fetch=fetch_values, post=post_target, fallback=None,
                 paths=None, interval=INTERVAL_S, retry=RETRY_S, clock=time.monotonic):
        port = cfg.get("sensors_port", DEFAULT_PORT)
        self.port = port if isinstance(port, int) and not isinstance(port, bool) and 1024 <= port <= 65535 \
            else DEFAULT_PORT
        self.token_path = os.path.join(str(root), "secrets", "sensors.key")
        self.profiles = profiles
        self._fetch, self._post = fetch, post
        self._fallback_make = fallback if fallback is not None else psutil_fallback
        self._fallback = None            # Lesefunktion, wird beim ersten Bedarf erzeugt
        self._fb_failed = False
        self._paths = paths
        self.interval, self.retry, self.clock = interval, retry, clock
        self.subs = {}                   # ws -> zuletzt gesendeter Meta-Stand
        # Rohwerte (lhm.*, bis zu 600) gehen ans Tablet nur, wenn ein Dashboard sie nutzt; die volle Liste bekommt
        # der Editor über sample(). raw_filter() -> Menge der benutzten lhm.*-IDs (vom Hub gesetzt).
        self.raw_filter = None
        self.meta, self.meta_ver = {}, 0
        self.ok = None                   # Helfer erreichbar? (None = noch unbekannt)
        self.reason = None
        self.next_try = 0.0              # frühester nächster Versuch beim Helfer
        self.target, self.target_dirty = None, False
        self._wake = asyncio.Event()
        self._bg = set()
        self._game_gen = 0
        self._deliver_lock = asyncio.Lock()

    # ---------------- Abos ----------------
    def subscribe(self, ws):
        self.subs[ws] = 0
        self._wake.set()

    def unsubscribe(self, ws):
        self.subs.pop(ws, None)

    # ---------------- Helfer abfragen ----------------
    def _log_state(self, ok, reason=None):
        if (ok, reason) == (self.ok, self.reason):
            return
        if ok:
            log.info("Sensor-Helfer erreichbar")
            if self.target is not None:
                self.target_dirty = True     # ein neu gestarteter Helfer kennt das Spiel nicht
        else:
            log.warning("Sensor-Helfer nicht nutzbar (%s) - Hub liefert nur Grundwerte", reason)
        self.ok, self.reason = ok, reason

    def _query(self):
        """Blockierend (Executor): Werte vom Helfer holen. SensorError bei jedem Problem."""
        token = read_token(self.token_path)
        if not token:
            raise SensorError("kein Token (secrets/sensors.key)")
        return self._fetch(self.port, token)

    def _read_fallback(self):
        if self._fallback is None:
            self._fallback = self._fallback_make()
        return self._fallback()

    async def sample(self):
        """Ein Durchlauf: (values, meta, sources). Der Helfer wird höchstens alle `retry` s neu versucht,
        solange er fehlt; dazwischen kommen die Grundwerte vom Hub."""
        loop = asyncio.get_running_loop()
        now = self.clock()
        if now >= self.next_try:
            try:
                data = await loop.run_in_executor(None, self._query)
                values, meta = convert(data["values"])
                sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
                self._log_state(True)
                self.next_try = 0.0
                return values, meta, sources
            except SensorError as e:
                self._log_state(False, e.reason)
            except Exception as e:  # noqa: BLE001 - nie die Anzeige beenden
                self._log_state(False, e.__class__.__name__)
            self.next_try = now + self.retry
        try:
            values, meta = convert(await loop.run_in_executor(None, self._read_fallback))
        except Exception as e:  # noqa: BLE001 - z. B. psutil fehlt
            if not self._fb_failed:
                log.warning("Grundwerte vom Hub nicht lesbar: %s", e.__class__.__name__)
            self._fb_failed = True
            return {}, {}, {"sensord": self.reason or "nicht erreichbar", "psutil": "Fehler"}
        self._fb_failed = False
        return values, meta, {"sensord": self.reason or "nicht erreichbar", "psutil": "ok (Rückfall)"}

    async def tick(self):
        """Werte holen und an alle Abonnenten verteilen."""
        values, meta, sources = await self.sample()
        if meta != self.meta:
            self.meta, self.meta_ver = meta, self.meta_ver + 1
        await self._distribute(values, meta, sources)
        if self.target_dirty and self.ok:
            await self._deliver()

    def _wanted_raw(self):
        if self.raw_filter is None:
            return frozenset()
        try:
            return frozenset(self.raw_filter())
        except Exception as e:  # noqa: BLE001 - kaputte Dashboard-Datei darf die Werte nicht stoppen
            log.warning("Benutzte Rohwerte nicht ermittelbar: %s", e.__class__.__name__)
            return frozenset()

    async def _distribute(self, values, meta, sources):
        if any(k.startswith(RAW_PREFIX) for k in values):
            wanted = self._wanted_raw()
            values = {k: v for k, v in values.items() if not k.startswith(RAW_PREFIX) or k in wanted}
            meta = {k: v for k, v in meta.items() if not k.startswith(RAW_PREFIX) or k in wanted}
        else:
            wanted = frozenset()
        state = (self.meta_ver, wanted)          # Meta neu schicken, wenn sie sich ändert oder neue Rohwerte dazukommen
        base = {"t": "stats", "values": values, "sources": sources}
        sends = []
        for ws, ver in list(self.subs.items()):
            msg = base if ver == state else dict(base, meta=meta)
            self.subs[ws] = state
            sends.append(self._send(ws, json.dumps(msg, separators=(",", ":"))))
        if sends:
            await asyncio.gather(*sends)

    async def _send(self, ws, data):
        try:
            await asyncio.wait_for(ws.send(data), SEND_TIMEOUT_S)
        except Exception:  # noqa: BLE001 - getrennt oder zu langsam: abmelden, die Verbindung räumt sich selbst
            self.subs.pop(ws, None)

    # ---------------- Spiel -> PresentMon ----------------
    def set_game(self, gid, procs=None):
        """Spielwechsel melden (gid oder None). Kehrt sofort zurück; Auflösen und Senden laufen im Hintergrund."""
        self._game_gen += 1     # ein späterer Wechsel macht eine noch laufende Auflösung ungültig
        t = asyncio.ensure_future(self._set_game(gid, procs, self._game_gen))
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    async def _set_game(self, gid, procs, gen):
        try:
            exe = None
            if gid and self.profiles is not None:
                exe = pick_exe(self.profiles.exe_names(gid), procs)
                if exe is None:
                    g = self.profiles.game(gid) or {}
                    paths = self._paths
                    if paths is None:
                        from . import library
                        paths = library.running_game_paths
                    found = await asyncio.get_running_loop().run_in_executor(None, paths)
                    exe = exe_from_paths(found, g.get("dir"))
            if gen != self._game_gen:
                return          # inzwischen ein anderes Spiel (oder keins) - das gilt
            self.target, self.target_dirty = exe, True
            self._wake.set()
            if self.ok is not False:
                await self._deliver()
        except Exception as e:  # noqa: BLE001
            log.warning("Spiel an den Sensor-Helfer melden: %s", e.__class__.__name__)

    async def _deliver(self):
        """Ziel an den Helfer senden. Scheitert es, bleibt es offen und wird mit dem nächsten Durchlauf versucht
        (Helfer noch nicht gestartet, neu gestartet). 400/404 = Helfer kann es nicht (kein PresentMon): aufgeben."""
        # Nacheinander: zwei Posts parallel im Executor kämen sonst evtl. in falscher Reihenfolge an
        async with self._deliver_lock:
            token = read_token(self.token_path)
            if not token or not self.target_dirty:
                return
            sent = self.target
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._post, self.port, token, sent)
            except SensorError as e:
                if e.code in (400, 404) and self.target == sent:   # sonst bleibt das neue Ziel offen
                    self.target_dirty = False
                    log.info("Sensor-Helfer nimmt kein Spielziel an (%s)", e.reason)
                return
            except Exception:  # noqa: BLE001
                return
            if self.target != sent:
                return          # währenddessen gewechselt: bleibt offen, der nächste Aufruf schickt das neue Ziel
            self.target_dirty = False
            log.info("PresentMon-Ziel: %s", sent or "keins")

    # ---------------- Hintergrundaufgabe ----------------
    async def run(self):
        """Läuft mit dem Hub: fragt nur ab, solange jemand abonniert hat; sonst wartet sie (oder liefert nur
        ein offenes Spielziel nach)."""
        while True:
            self._wake.clear()           # vor der Arbeit: ein Abo währenddessen löst den nächsten Durchlauf sofort aus
            try:
                if self.subs:
                    await self.tick()
                    wait = self.interval
                elif self.target_dirty:
                    await self._deliver()
                    wait = self.retry
                else:
                    wait = None
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - die Anzeige darf nicht dauerhaft stehen bleiben
                log.exception("PC-Werte: Durchlauf fehlgeschlagen")
                wait = self.retry
            try:
                await asyncio.wait_for(self._wake.wait(), wait)
            except asyncio.TimeoutError:
                pass
