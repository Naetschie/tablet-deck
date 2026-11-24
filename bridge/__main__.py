"""Tablet-Bridge: liefert die Webseite aus, nimmt Tasten per WebSocket an und gibt sie aus.

Start:  python -m bridge            (aus dem Projektordner)
"""
import asyncio
import ctypes
import ipaddress
import json
import logging
import mimetypes
import re
import secrets
import hmac
import os
import shutil
import sys
import time
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

from .audio import Audio, AudioWorker, mixer_changed
from .quiet import silence_spacedesk
from . import proxy
from .session import watch_session_end
from .tls import ServerTLS
from .autoprofile import auto_modes
from .firstrun import ensure_from_example
from .outputs import make_output
from .keys import ALIASES, MEDIA_VK, SCANCODES
from .games import watch_games
from .generate import (actions_message, ai_draft, binding_status, draft, learn_finish, learn_snapshot,
                       library_entry, list_templates, save_web_template, set_learned)
from .bindings.web import lookup as web_lookup
from . import ai_providers, ai_template
from .profiles import Exists, Profiles
from .layout import button_for_press, needed_keys
from .webhome import WebHome
from .pcinput import PcInput
from .stats import Stats
from . import dashboard
from . import themes
from .tray import Tray
from .devices import Devices, valid_id
from .usermaps import UserMaps
from . import mapgenie

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def web_version(web=None):
    """Kennung des Stands von web/ (Pfade, Größen, Änderungszeiten). Die Seiten laden sich neu, wenn sie sich
    nach einem Neuverbinden geändert hat - sonst liefe am Tablet nach einem Update weiter das alte app.js."""
    import hashlib
    web = web or WEB
    h = hashlib.sha1()
    for f in sorted(web.rglob("*")):
        if f.is_file():
            st = f.stat()
            h.update(f"{f.relative_to(web).as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:12]


PULSE_S = 0.08   # Dauer eines Tasten-Impulses (Panel-Tasten ohne "hold")
PULSE_GAP_S = 0.03   # Pause zwischen zwei Impulsen derselben Taste
PULSE_MAX_QUEUE = 40
# Exit-Codes, bei denen der Wächter (supervise.py) NICHT neu startet
EXIT_RUNNING = 75   # Port belegt: Bridge läuft schon
EXIT_CONFIG = 78    # Konfigurationsfehler: Neustart würde nichts ändern
# Hub-Seiten laden nur eigene Inhalte (keine fremden Skripte/Frames; WebSocket nur zum Hub selbst)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self' ws://localhost:8765 ws://127.0.0.1:8765; frame-src 'none'; object-src 'none'; "
       "base-uri 'none'; form-action 'self'")
log = logging.getLogger("bridge")
mimetypes.add_type("font/woff2", ".woff2")   # fehlt in Pythons Liste; nosniff verlangt den richtigen Typ


def load_or_create_secret(path, note="Kopplungsgeheimnis - Launcher neu einrichten: tablet\\setup-launcher.ps1"):
    """Geheimnis aus Datei (bleibt über Neustarts gleich; neu erzeugen = Datei löschen)."""
    try:
        s = path.read_text(encoding="ascii").strip()
        if len(s) >= 32:
            return s
    except OSError:
        pass
    s = secrets.token_urlsafe(32)
    path.write_text(s + "\n", encoding="ascii")
    log.info("Neu erzeugt: %s (%s)", path, note)
    return s


def cookie_value(header, name):
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return ""


def is_loopback(addr):
    try:
        return ipaddress.ip_address(addr[0]).is_loopback
    except (TypeError, ValueError, IndexError):
        return False


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Bridge:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dashboards = dashboard.Dashboards(ROOT / "dashboards", cfg)   # cfg_path setzt main()
        self.profiles = Profiles(ROOT / cfg.get("profiles", "profiles"), ROOT / cfg.get("games", "games.json"),
                                 legacy_layout=ROOT / cfg.get("layout", "layout.json"),
                                 bundled=ROOT / cfg.get("panels_bundled", "panels"))
        self.game = None       # laufendes Spiel (games.py)
        self.ai_busy = False   # KI-Vorlage läuft (Editor)
        self.learn_snaps = {}  # Lernmodus: Spiel -> Dateizustand vor der Tastenänderung im Spiel
        self.web_pending = {}  # Standardtasten aus dem Netz: Spiel -> gelesene Vorlage bis zur Bestätigung
        self.pulse_q, self.pulse_tasks = {}, {}   # Impuls-Warteschlangen pro Taste (siehe _enqueue_pulse)
        self.hold_since, self.late_release = {}, {}   # press_ms bei Halte-Tasten: Druckbeginn, verzögertes Loslassen
        self.web = WebHome(ROOT)   # Startseite der Web-Kachel: Lesezeichen, gesendet, Verlauf
        self.usb_serials = set()   # per USB eingerichtete Tablets (adb_watch), für das Ausschalten beim Herunterfahren
        self.out = make_output(cfg)
        self.clients = {}  # ws -> {button-id: [button-snapshot, finger-anzahl]}
        self.client_panel = {}  # ws -> "spiel/panel", das diese Seite zeigt
        self.wlan_tls = None       # ServerTLS, wenn der WLAN-Zugang läuft
        self.wlan_server = None
        self.wlan_port = int(cfg.get("wlan", {}).get("port", 8767))
        self.plugged_until = 0.0   # bis dahin gilt "app:extern" als Autostart durchs Anstecken
        self.plugged_serial = None
        self.homes_left = 0        # höchstens so oft zurückholen (kein Hin und Her mit spacedesk)
        self.ctl_clients = {}  # ws -> zuletzt gemeldeter Modus (Launcher-Steuerkanal /ctl)
        self.ctl_device = {}   # ws -> Gerätekennung (Cookie deckdev, siehe devices.py) oder None
        self.devices = Devices(ROOT / cfg.get("devices", "devices.json"))
        # WLAN-Tablets (IP), die seit dem Start bzw. dem letzten Schlafbefehl schon geweckt wurden - nicht bei
        # jedem Neuverbinden (WLAN-Aussetzer) wecken, wie bei USB nur bei neuem Gerät bzw. nach Schlafen
        self.wlan_woken = set()
        self.auto_mode = None  # aktueller Wunschmodus der Automatik (autoprofile.py)
        self.auto_pending = False  # Wunschmodus geändert, aber noch an keinen Launcher gesendet
        port = int(cfg.get("port", 8765))
        self.allowed_origins = {f"http://localhost:{port}", f"http://127.0.0.1:{port}"}
        self.secret = load_or_create_secret(ROOT / "secret.key")
        # Eigener Schlüssel nur fürs Senden von Webseiten (Browser-Erweiterung): erlaubt nichts weiter
        self.send_key = load_or_create_secret(ROOT / "send.key", "Sende-Schlüssel für die Browser-Erweiterung")
        self.last_open = {}   # Tasten-ID -> Zeitpunkt (gegen doppeltes Öffnen)
        self.require_secret = cfg.get("require_secret", True)
        self.launcher_path = ROOT / cfg.get("launcher", "launcher.json")
        self.launcher_mtime = None
        self.tiles = []
        self.on_tiles_changed = None   # Rückruf (Taskleisten-Menü), wird in main() gesetzt
        self.audio = Audio()
        self.stats = Stats(ROOT, cfg, self.profiles)   # PC-Werte für /stats/ (Sensor-Helfer bzw. psutil)
        self.stats.raw_filter = self.dashboards.raw_ids   # Rohwerte ans Tablet nur, wenn ein Dashboard sie nutzt
        # Mixer (Apps, Geräte) in einem eigenen Thread mit COM: Abfragen bis ca. 70 ms blockieren sonst den Loop
        self.audio_worker = AudioWorker()
        self._audio_pending = {}   # Schlüssel -> wartender Befehl (siehe run_audio)
        self.pc = PcInput(self.audio, self.out, run_audio=self.run_audio)
        self.volume_state = None
        self.mixer_state = None   # letzter Mixer-Stand (Apps + Ausgabegeräte), siehe audio.mixer
        self.macros = {}   # Taste -> (Task, Client-WebSocket); abbrechbar bei Ansichtswechsel/Abbruch
        # Zugang zum Editor (/edit): nur über das Taskleisten-Symbol bzw. die Konsole - Tablet-Apps
        # erreichen localhost:8765 über adb reverse ebenfalls, kennen dieses Token aber nicht.
        self.editor_token = secrets.token_urlsafe(24)
        self.user_maps = UserMaps(ROOT / cfg.get("maps", "maps.json"))   # eigene Kartenlisten (Editor)
        self.user_maps.load()
        self.profiles.user_maps = self.user_maps.maps
        self.profiles.migrate()
        self.profiles.load_games()
        self.profiles.scan()
        if not self.profiles.panels:
            # Touchpad, Medien, Web usw. laufen trotzdem; ein repariertes Profil lädt der Watcher nach
            log.error("Keine gültigen Panels in profiles/ - Panel-Seite bleibt leer, bis ein Profil passt")
        if self.launcher_path == ROOT / "launcher.json":   # erster Start: Kacheln aus dem Beispiel
            ensure_from_example(self.launcher_path, ROOT / "launcher.example.json")
        try:
            self.load_launcher()
        except Exception as e:  # noqa: BLE001 – Bridge trotzdem starten, Launcher nutzt seine Standards
            log.error("launcher.json fehlerhaft, keine Kacheln vom Hub: %s", e)
            self.launcher_mtime = self.launcher_path.stat().st_mtime

    async def watch_volume(self):
        """Lautstärke am PC beobachten und Änderungen an alle Tablet-Seiten melden (Regler aktuell halten)."""
        guard = self.cfg.get("audio_output") or {}
        tick = 0
        while True:
            if guard.get("prefer") and tick % 6 == 0:   # alle 3 s
                try:
                    name = self.audio.guard_default(guard.get("avoid", "spacedesk"), guard["prefer"])
                    if name:
                        log.info("Audio-Ausgabe zurück auf %s (statt %s)", name, guard.get("avoid", "spacedesk"))
                except Exception as e:  # noqa: BLE001
                    log.error("Audio-Ausgabe umstellen: %s", e)
            tick += 1
            st = self.audio.get()
            if st and st != self.volume_state:
                self.volume_state = st
                await self.broadcast(self.volume_msg())
                await self.ctl_send(self.volume_msg())   # Ton-Knopf der Launcher (stumm/nicht stumm)
            if tick % 2 == 0:   # Mixer etwa jede Sekunde; nur bei Änderung senden
                try:
                    # hängt ein COM-Aufruf (Treiber, Gerät angesteckt): Lautstärke und Wächter laufen weiter
                    name_for = self.game_name_for()
                    mx = await asyncio.wait_for(asyncio.wrap_future(
                        self.audio_worker.submit(lambda: self.audio.mixer(name_for))), 5)
                except asyncio.TimeoutError:
                    log.error("Mixer lesen: keine Antwort nach 5 s")
                    mx = None
                except Exception as e:  # noqa: BLE001
                    log.error("Mixer lesen: %s", e)
                    mx = None
                avoid = (guard.get("avoid", "spacedesk") if guard.get("prefer") else "").lower()
                if mx and avoid:
                    # Gerät, das der Wächter ohnehin zurückstellt (spacedesk): gar nicht erst anbieten
                    mx["devices"] = [d for d in mx["devices"] if avoid not in d["name"].lower()]
                if mx and mixer_changed(self.mixer_state, mx):
                    self.mixer_state = mx
                    await self.broadcast(self.mixer_msg())
            await asyncio.sleep(0.5)

    def run_audio(self, fn, key=None):
        """Mixer-Befehl im Audio-Thread ausführen (aus dem Loop: nicht warten, Fehler loggen). Mit key wird ein
        noch wartender Befehl desselben Schlüssels ersetzt - beim Ziehen zählt nur der letzte Wert."""
        loop = asyncio.get_running_loop()

        def forget(f):
            if self._audio_pending.get(key) is f:
                del self._audio_pending[key]          # erledigt: Eintrag nicht ewig halten

        def done(f):   # läuft im Audio-Thread: das Dict nur im Loop-Thread ändern
            if key is not None:
                try:
                    loop.call_soon_threadsafe(forget, f)
                except RuntimeError:   # Loop beim Beenden schon zu
                    pass
            if not f.cancelled() and f.exception() is not None:
                log.error("Mixer-Befehl: %s", f.exception())
        if key is not None:
            old = self._audio_pending.get(key)
            if old is not None:
                old.cancel()   # wirkt nur, solange er noch nicht läuft
        f = self.audio_worker.submit(fn)
        if key is not None:
            self._audio_pending[key] = f
        f.add_done_callback(done)

    def volume_msg(self):
        return {"t": "volume", "v": self.volume_state[0], "mute": self.volume_state[1]}

    def mixer_msg(self):
        return {"t": "mixer", **self.mixer_state}

    def game_name_for(self):
        """Rückruf für audio.sessions: Anzeigename des laufenden Spiels für seine Programmnamen."""
        if not self.game:
            return None
        exes = {e.lower() for e in self.profiles.exe_names(self.game)}
        if not exes:
            return None
        name = self.profiles.summary(self.game)["name"]
        return lambda exe: name if exe.lower() in exes else None

    # ---------------- Launcher-Kacheln ----------------
    def load_launcher(self):
        """Kacheln für den Tablet-Launcher (launcher.json). Fehlt die Datei, nutzt der Launcher seine Standards."""
        try:
            mtime = self.launcher_path.stat().st_mtime
        except OSError:
            self.tiles, self.launcher_mtime = [], None
            return
        data = load_json(self.launcher_path)
        tiles = data["tiles"]
        for t in tiles:   # gleiche Regeln wie im Launcher (HomeActivity.Tile.of)
            ok = isinstance(t.get("id"), str) and t["id"] and (
                (t.get("type") == "web" and isinstance(t.get("path"), str)
                 and re.fullmatch(r"/[A-Za-z0-9/._-]*(\?[A-Za-z0-9=&._-]*)?", t["path"]) and ".." not in t["path"]
                 and type(t.get("port", 8765)) is int and 1024 <= t.get("port", 8765) <= 65535)
                or (t.get("type") == "app" and isinstance(t.get("pkg"), str)
                    and re.fullmatch(r"[A-Za-z0-9_.]+", t["pkg"]))
                or t.get("type") in ("browser", "maps"))
            if not ok:
                raise ValueError(f"Kachel ungültig: {t}")
        self.tiles, self.launcher_mtime = tiles, mtime
        log.info("Launcher: %d Kacheln", len(tiles))

    async def edit_handler(self, ws):
        """Layout-Editor: {"t":"auth","k":token} zuerst, dann get/save."""
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if not (isinstance(first, dict) and first.get("t") == "auth" and isinstance(first.get("k"), str)
                    and hmac.compare_digest(first["k"].encode(), self.editor_token.encode())):
                log.warning("Editor: falsches Token")
                await ws.close(4001, "token")
                return
            log.info("Editor verbunden")
            async for raw in ws:
                msg = json.loads(raw)
                t = msg.get("t")
                try:
                    if t == "games":
                        await ws.send(json.dumps({"t": "games", "games": self.games_info(),
                                                  "current": self.game}))
                    elif t == "get":
                        key = f"{msg.get('game')}/{msg.get('panel')}"
                        prof = self.profiles.get(key) or self.profiles.get(self.profiles.default_key(self.game))
                        key = next(k for k, v in self.profiles.panels.items() if v is prof)
                        game, panel = key.split("/", 1)
                        await ws.send(json.dumps({
                            "t": "layout", "game": game, "panel": panel, "layout": prof["layout"], "origin": prof["origin"],
                            "keys": sorted(set(SCANCODES) | set(ALIASES)), "media": sorted(MEDIA_VK)}))
                    elif t == "save":
                        key = self.profiles.save(msg.get("game"), msg.get("panel"), msg.get("layout"),
                                                 new=msg.get("new") is True)
                        log.info("Editor: Panel %s gespeichert", key)
                        await self.reload_profiles()                 # sofort, nicht erst beim Watcher
                        await ws.send('{"t":"saved"}')
                    elif t == "create":
                        copy = msg.get("copy")
                        key = self.profiles.create(msg.get("game"), msg.get("panel"), str(msg.get("title", ""))[:40]
                                                   or msg.get("panel"), copy if isinstance(copy, str) else None)
                        log.info("Editor: Panel %s angelegt", key)
                        await self.reload_profiles()
                        await ws.send(json.dumps({"t": "created", "game": msg["game"], "panel": msg["panel"],
                                                  "games": self.games_info()}))
                    elif t == "copy":
                        # mitgeliefertes Panel -> eigene Kopie; layout = schon geänderter Stand (optional)
                        new = self.profiles.copy_bundled(msg.get("game"), msg.get("panel"), msg.get("title"),
                                                         msg.get("layout"))
                        log.info("Editor: Kopie %s von %s angelegt", new, msg.get("panel"))
                        await self.reload_profiles()
                        await ws.send(json.dumps({"t": "created", "game": msg["game"],
                                                  "panel": new.split("/", 1)[1],
                                                  "games": self.games_info()}))
                    elif t == "templates":
                        g = msg.get("game")
                        gi = self.profiles.game(g)
                        await ws.send(json.dumps({"t": "templates", "game": g, "templates": list_templates(ROOT, g),
                                                  "bindings": bool(gi and gi.get("bindings"))}))
                    elif t == "actions":
                        gi = self.profiles.game(msg.get("game"))
                        if not gi:
                            raise ValueError("Spiel nicht in games.json")
                        # Belegungsdatei lesen nicht im Event-Loop
                        reply = await asyncio.get_running_loop().run_in_executor(None, actions_message, ROOT, gi)
                        await ws.send(json.dumps(reply))
                    elif t == "generate":
                        gi = self.profiles.game(msg.get("game"))
                        if not gi:
                            raise ValueError("Spiel nicht in games.json")
                        pages = msg.get("pages")
                        if pages is not None and not (isinstance(pages, list) and all(isinstance(x, str) for x in pages)):
                            raise ValueError("pages muss eine Liste sein")
                        # Dateien lesen (actionmaps.xml) nicht im Event-Loop
                        style = msg.get("style", "areas")   # Darstellung semantischer Vorlagen: areas | grid
                        skip_dev = msg.get("skip_device") is True   # optional: was auf Joystick/Gamepad liegt, weglassen
                        layout, report, source = await asyncio.get_running_loop().run_in_executor(
                            None, draft, ROOT, gi, msg.get("template"), pages, style, skip_dev)
                        log.info("Editor: Entwurf %s/%s erzeugt (%s)", gi["id"], msg.get("template"), source)
                        await ws.send(json.dumps({"t": "draft", "game": gi["id"], "template": msg.get("template"),
                                                  "layout": layout, "report": report, "source": source}))
                    elif t == "ai":
                        g = msg.get("game")
                        gi = self.profiles.game(g) or (
                            {"id": g, "name": g} if isinstance(g, str) and re.fullmatch(r"[a-z0-9-]{1,40}", g) else None)
                        if not gi:
                            raise ValueError("Spiel fehlt oder ungültig")
                        if self.ai_busy:
                            raise ValueError("KI erstellt gerade schon eine Vorlage")
                        hint = msg.get("hint") if isinstance(msg.get("hint"), str) else ""
                        # änderbarer Teil des Prompts (None = Voreinstellung); der feste Teil gilt immer
                        sprompt = msg.get("prompt") if isinstance(msg.get("prompt"), str) else None
                        style = msg.get("style", "areas")
                        skip_dev = msg.get("skip_device") is True
                        log.info("Editor: KI-Vorlage für %s angefragt", gi["id"])
                        # kostenpflichtig: nie zwei Anfragen gleichzeitig. Die Sperre endet erst, wenn der
                        # Aufruf im Hintergrund-Thread wirklich fertig ist - auch wenn der Editor vorher geht.
                        # Freigabe im Thread selbst: der asyncio-Future wird beim Abbruch des Handlers sofort
                        # storniert, der Aufruf läuft aber weiter.
                        def run_ai(gi=gi, hint=hint[:2000], sprompt=sprompt, style=style, skip_dev=skip_dev):
                            try:
                                return ai_draft(ROOT, gi, hint, sprompt, style, skip_dev)
                            finally:
                                self.ai_busy = False
                        self.ai_busy = True
                        try:
                            fut = asyncio.get_running_loop().run_in_executor(None, run_ai)
                        except Exception:
                            self.ai_busy = False
                            raise
                        try:
                            layout, report, source = await asyncio.shield(fut)   # Abbruch des Handlers storniert den Auftrag nicht
                        except ValueError:
                            raise
                        except Exception as e:  # noqa: BLE001 - Editor bekommt eine Meldung statt Abbruch
                            log.error("KI-Vorlage fehlgeschlagen: %s", type(e).__name__)
                            raise ValueError(f"KI-Vorlage fehlgeschlagen ({type(e).__name__})") from None
                        await ws.send(json.dumps({"t": "draft", "game": gi["id"], "template": "ki",
                                                  "layout": layout, "report": report, "source": source}))
                    elif t == "bind_status":
                        # woher die Tasten kommen (Adapter, Rückfall-Suche in den Spielordnern) - vor dem Erzeugen zeigen
                        g = msg.get("game")
                        gi = self.profiles.game(g) or (
                            {"id": g, "name": g} if isinstance(g, str) and re.fullmatch(r"[a-z0-9-]{1,40}", g) else None)
                        if not gi:
                            raise ValueError("Spiel fehlt oder ungültig")
                        st = await asyncio.get_running_loop().run_in_executor(None, binding_status, ROOT, gi)
                        await ws.send(json.dumps({"t": "bind_status", "game": gi["id"], **st}))
                    elif t in ("bind_learn_start", "bind_learn_done", "bind_learn_forget"):
                        # Lernmodus: Dateien merken -> Nutzer ändert im Spiel eine Taste -> geänderte Datei finden
                        g = msg.get("game")
                        gi = self.profiles.game(g) or (
                            {"id": g, "name": g} if isinstance(g, str) and re.fullmatch(r"[a-z0-9-]{1,40}", g) else None)
                        if not gi:
                            raise ValueError("Spiel fehlt oder ungültig")
                        loop = asyncio.get_running_loop()
                        if t == "bind_learn_start":
                            snap = await loop.run_in_executor(None, learn_snapshot, gi)
                            while len(self.learn_snaps) >= 4:   # nie beendete Lernläufe begrenzen
                                self.learn_snaps.pop(next(iter(self.learn_snaps)))
                            self.learn_snaps[gi["id"]] = snap
                            await ws.send(json.dumps({"t": "bind_learn", "game": gi["id"], "step": "started",
                                                      "files": len(self.learn_snaps[gi["id"]])}))
                        elif t == "bind_learn_done":
                            snap = self.learn_snaps.pop(gi["id"], None)
                            if snap is None:
                                raise ValueError("Lernmodus nicht gestartet")
                            res = await loop.run_in_executor(None, learn_finish, ROOT, gi, snap)
                            await ws.send(json.dumps({"t": "bind_learn", "game": gi["id"], "step": "done", **res}))
                        else:
                            await loop.run_in_executor(None, set_learned, ROOT, gi["id"], None)
                            await ws.send(json.dumps({"t": "bind_learn", "game": gi["id"], "step": "forgotten"}))
                    elif t in ("web_find", "web_save"):
                        # Standardtasten aus einer Steuerungs-Seite im Netz (nur Spielname bzw. genannte Adresse)
                        g = msg.get("game")
                        gi = self.profiles.game(g) or (
                            {"id": g, "name": g} if isinstance(g, str) and re.fullmatch(r"[a-z0-9-]{1,40}", g) else None)
                        if not gi:
                            raise ValueError("Spiel fehlt oder ungültig")
                        loop = asyncio.get_running_loop()
                        if t == "web_find":
                            url = msg.get("url") if isinstance(msg.get("url"), str) and msg.get("url").strip() else None
                            lib_name = (await loop.run_in_executor(None, library_entry, gi)).get("name")
                            name = gi.get("name") or lib_name or g
                            if msg.get("ai") is True:
                                # KI-Suche (kostenpflichtig): nie zwei gleichzeitig, Sperre endet im Thread selbst
                                if self.ai_busy:
                                    raise ValueError("KI arbeitet gerade schon")
                                from .ai_bindings import lookup as ai_web_lookup

                                def run_ai_web(name=name):
                                    try:
                                        return ai_web_lookup(ROOT, name)
                                    finally:
                                        self.ai_busy = False
                                self.ai_busy = True
                                log.info("Editor: KI-Suche nach Standardtasten für %s", gi["id"])
                                try:
                                    res = await asyncio.shield(loop.run_in_executor(None, run_ai_web))
                                except ValueError:
                                    raise
                                except Exception as e:  # noqa: BLE001 - API-Fehler als Meldung, nie mit Schlüssel
                                    log.error("KI-Suche fehlgeschlagen: %s", type(e).__name__)
                                    raise ValueError(f"KI-Suche fehlgeschlagen ({type(e).__name__})") from None
                            else:
                                res = await loop.run_in_executor(None, web_lookup, name, url[:500] if url else None,
                                                                 lib_name)
                            self.web_pending[gi["id"]] = res["template"]
                            await ws.send(json.dumps({"t": "web_found", "game": gi["id"], "site": res["site"],
                                                      "url": res["url"], "title": res["title"], "count": len(res["rows"]),
                                                      "rows": [[a, r, k] for a, r, k, _h in res["rows"][:80]],
                                                      "others": res["others"]}))
                        else:
                            tpl = self.web_pending.pop(gi["id"], None)
                            if not tpl:
                                raise ValueError("nichts zum Speichern – erst suchen")
                            tid = await loop.run_in_executor(None, save_web_template, ROOT, gi["id"], tpl)
                            log.info("Editor: Vorlage %s/%s aus dem Netz gespeichert (%s)", gi["id"], tid,
                                     tpl.get("source", {}).get("site", ""))
                            await ws.send(json.dumps({"t": "web_saved", "game": gi["id"], "template": tid}))
                    elif t == "ai_prompt":
                        await ws.send(json.dumps({"t": "ai_prompt", **ai_template.prompt_parts()}))
                    elif t in ("ai_key_status", "ai_key_set", "ai_key_delete", "ai_key_check", "ai_settings_set"):
                        # KI-Anbieter (Anthropic/OpenAI) und Schlüssel; der Schlüssel geht nur Editor -> Datei
                        if t == "ai_settings_set":
                            ai_providers.save_settings(ROOT, msg.get("provider"), msg.get("openai_model"))
                        st = ai_providers.settings(ROOT)
                        raw_prov = msg.get("provider")
                        if t in ("ai_key_set", "ai_key_delete", "ai_key_check") and not (
                                isinstance(raw_prov, str) and raw_prov in ai_providers.PROVIDERS):
                            raise ValueError("Anbieter fehlt oder unbekannt")   # nie still beim falschen Anbieter
                        prov = raw_prov if isinstance(raw_prov, str) and raw_prov in ai_providers.PROVIDERS else st["provider"]
                        extra = {}
                        if t == "ai_key_set":
                            ai_providers.save_key(ROOT, prov, msg.get("key"))
                            extra["msg"] = "Gespeichert"
                        elif t == "ai_key_delete":
                            ai_providers.delete_key(ROOT, prov)
                            extra["msg"] = "Entfernt"
                        elif t == "ai_key_check":
                            fn = ai_template.check_key if prov == "anthropic" else ai_providers.check_openai
                            extra["check"] = await asyncio.get_running_loop().run_in_executor(None, fn, ROOT)
                        elif t == "ai_settings_set":
                            extra["msg"] = "Einstellung gespeichert"
                        await ws.send(json.dumps({"t": "ai_key", "provider": prov, "active": st["provider"],
                                                  "openai_model": st["openai_model"],
                                                  "active_set": ai_providers.key_status(ROOT, st["provider"])["set"],
                                                  **ai_providers.key_status(ROOT, prov), **extra}))
                    elif t == "dash_sensors":
                        values, meta, sources = await self.stats.sample()
                        await ws.send(json.dumps({"t": "dash_sensors", "sensors": dashboard.sensor_list(values, meta),
                                                  "sources": sources}))
                    elif t == "devices":
                        await ws.send(json.dumps(self.devices_info(), ensure_ascii=False))
                    elif t == "device_light":
                        dev = msg.get("id")
                        if not (valid_id(dev) and isinstance(msg.get("on"), bool) and self.devices.set_light(dev, msg["on"])):
                            raise ValueError("Gerät unbekannt oder Datei devices.json fehlerhaft")
                        await self.send_light(dev)
                        await ws.send(json.dumps(self.devices_info(), ensure_ascii=False))
                    elif t == "device_theme":
                        dev = msg.get("id")
                        if not (valid_id(dev) and self.devices.set_theme(dev, msg.get("theme"))):
                            raise ValueError("Gerät oder Farbschema unbekannt oder Datei devices.json fehlerhaft")
                        await self.send_theme(dev)
                        await ws.send(json.dumps(self.devices_info(), ensure_ascii=False))
                    elif t in ("maps_list", "maps_save", "maps_reset", "maps_lookup", "maps_show"):
                        await ws.send(json.dumps(await self.maps_edit(msg), ensure_ascii=False))
                    elif isinstance(t, str) and t.startswith("dash_"):
                        await ws.send(json.dumps(self.dashboards.handle(msg), ensure_ascii=False))
                    elif t == "delete":
                        self.profiles.delete(msg.get("game"), msg.get("panel"))
                        log.info("Editor: Panel %s/%s in den Papierkorb", msg.get("game"), msg.get("panel"))
                        await self.reload_profiles()
                        await ws.send(json.dumps({"t": "deleted", "games": self.games_info()}))
                except (ValueError, TypeError, OSError, StopIteration, RuntimeError) as e:
                    await ws.send(json.dumps({"t": "error", "req": t, "msg": str(e) or e.__class__.__name__,
                                              "code": "exists" if isinstance(e, Exists) else None}))
        except (asyncio.TimeoutError, ValueError, AttributeError):
            pass
        except Exception as e:  # noqa: BLE001
            log.info("Editor getrennt: %s", e.__class__.__name__)

    async def send_url(self, url, from_pc=True):
        """Webseite am Tablet öffnen (Web-Kachel). Gibt eine Fehlermeldung zurück oder None.
        from_pc: vom PC gesendet (erscheint auf der Startseite unter "Vom PC gesendet")."""
        if not isinstance(url, str) or len(url) > 4096:
            return "ungültige URL"
        url = url.strip()
        if not re.match(r"(?i)^https?://[^\s/]+", url):
            return "nur http(s)-Adressen"
        targets = self.send_targets()
        if not targets:
            if self.devices.multi():
                return f"{self.devices.name(self.devices.main())} nicht verbunden"
            return "Tablet nicht verbunden"
        data = json.dumps({"t": "open", "url": url})
        for ws in targets:
            try:
                await ws.send(data)
            except Exception:  # noqa: BLE001
                pass
        log.info("Webseite ans Tablet: %s", url.split("/")[2])   # nur den Host ins Log
        if from_pc and self.web.add_sent(url):
            await self.broadcast_web()
        return None

    def send_targets(self):
        """Launcher, die gesendete Webseiten bekommen: nur das Hauptgerät, sobald mehrere Geräte gekoppelt
        sind (kein Ausweichen auf ein anderes). Ein Gerät: alle Launcher wie bisher (auch ohne Kennung)."""
        if not self.devices.multi():
            return list(self.ctl_clients)
        main = self.devices.main()
        return [ws for ws in self.ctl_clients if self.ctl_device.get(ws) == main]

    async def broadcast_web(self):
        await self.broadcast(dict(self.web.data(), t="web"))

    async def send_handler(self, ws):
        """PC-Programme (bridge.send, Taskleiste): {"t":"auth","k":secret}, dann {"t":"open","url":...}."""
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), 10))
            # PC-Programme ohne Origin: Kopplungsgeheimnis oder Sende-Schlüssel; Erweiterungen nur Sende-Schlüssel
            from_ext = ws.request.headers.get("Origin") is not None
            keys_ok = [self.send_key] if from_ext else [self.secret, self.send_key]
            if not (isinstance(first, dict) and first.get("t") == "auth" and isinstance(first.get("k"), str)
                    and any(hmac.compare_digest(first["k"].encode(), k.encode()) for k in keys_ok)):
                log.warning("Senden: falscher Schlüssel")
                await ws.close(4001, "key")
                return
            async for raw in ws:
                msg = json.loads(raw)
                if isinstance(msg, dict) and msg.get("t") == "open":
                    err = await self.send_url(msg.get("url"))
                    await ws.send(json.dumps({"t": "error", "msg": err} if err else {"t": "ok"}))
        except (asyncio.TimeoutError, ValueError):
            pass
        except Exception as e:  # noqa: BLE001
            log.info("Senden getrennt: %s", e.__class__.__name__)

    async def back_from_autostart(self, ws):
        """Nach dem Anstecken von selbst gestartetes spacedesk: zurück zum Launcher - aber nur, wenn wirklich
        spacedesk vorn ist (kein Systemdialog wie "USB-Zubehör erlauben?" verdecken)."""
        await asyncio.sleep(2)
        if self.ctl_clients.get(ws) != "app:extern":
            return   # inzwischen zurück im Launcher oder andere Ansicht
        adb = find_adb(self.cfg)
        if not adb:
            return
        sel = ["-s", self.plugged_serial] if self.plugged_serial else []
        _, out = await run(adb, *sel, "shell", "dumpsys activity activities | grep -m1 topResumedActivity")
        if AUTOSTART_PKG in out and self.homes_left > 0:
            self.homes_left -= 1
            log.info("%s nach dem Anstecken von selbst gestartet - zurück zum Launcher", AUTOSTART_PKG)
            try:
                await ws.send('{"t":"home"}')
            except Exception:  # noqa: BLE001
                pass

    async def wake_wlan(self, ws, peer):
        """Im WLAN beim Herunterfahren des PCs schlafen gelegt -> beim Verbinden wieder wecken (per USB:
        adb_watch). Nur einmal je IP seit Start bzw. Schlafbefehl, nicht nach jedem WLAN-Aussetzer."""
        if (is_loopback(ws.remote_address) or not self.cfg.get("tablet_sleep_with_pc", True)
                or peer in self.wlan_woken):
            return False
        # vor dem Senden eintragen: leert wlan_slept() die Menge während des await, gilt das (danach kommt
        # "sleep", beim nächsten Verbinden wird wieder geweckt)
        self.wlan_woken.add(peer)
        try:
            await ws.send(json.dumps({"t": "power", "action": "wake"}))
        except Exception:
            self.wlan_woken.discard(peer)   # nicht angekommen: beim nächsten Verbinden erneut
            raise
        return True

    def wlan_slept(self):
        """PC legt Tablets schlafen: WLAN-Tablets beim nächsten Verbinden wieder wecken (auch gerade getrennte)."""
        self.wlan_woken.clear()

    async def power_wlan(self, action):
        """Tablets, die nur per WLAN verbunden sind (per USB erledigt das adb) schlafen legen ("sleep").
        wlan_slept() ruft notify() getrennt davon auf (auch ohne verbundenes WLAN-Tablet)."""
        for ws in list(self.ctl_clients):
            if not is_loopback(ws.remote_address):
                await ws.send(json.dumps({"t": "power", "action": action}))
                log.info("Tablet im WLAN: %s", action)

    def rotation_msg(self, dev=None):
        rot = device_rotation(self.cfg, dev, getattr(self, "devices", None))
        return {"t": "rotation", "r": -1 if rot is None else rot}

    def tablet_mode_msg(self, dev=None):
        devs = getattr(self, "devices", None)
        mode = device_mode(self.cfg, dev, devs) if dev else tablet_mode(self.cfg)
        return {"t": "tablet_mode", "mode": mode}

    def light_msg(self, dev=None):
        return {"t": "light", "on": device_light(self.cfg, dev, getattr(self, "devices", None))}

    async def send_light(self, dev):
        """Light-Modus an alle verbundenen Launcher dieses Geräts."""
        for ws, d in list(self.ctl_device.items()):
            if d == dev:
                try:
                    await ws.send(json.dumps(self.light_msg(dev)))
                except Exception:  # noqa: BLE001
                    pass

    def theme_msg(self, dev=None):
        return {"t": "theme", "colors": themes.colors(device_theme(self.cfg, dev, getattr(self, "devices", None)))}

    async def send_theme(self, dev):
        """Farbschema an alle verbundenen Launcher dieses Geräts."""
        for ws, d in list(self.ctl_device.items()):
            if d == dev:
                try:
                    await ws.send(json.dumps(self.theme_msg(dev)))
                except Exception:  # noqa: BLE001
                    pass

    def request_theme(self, request):
        """Farbschema zur Gerätekennung einer Anfrage (ohne Kennung, z. B. Editor am PC: Standard)."""
        dev = cookie_value(request.headers.get("Cookie", ""), "deckdev")
        return device_theme(self.cfg, dev, self.devices) if valid_id(dev) else themes.DEFAULT

    def devices_info(self):
        """Editor, Einstellungen → Geräte: gekoppelte Geräte mit Light-Modus, Farbschema und Verbindung."""
        online = set(self.ctl_device.values())
        return {"t": "devices", "themes": themes.choices(), "devices": [
            {"id": d, "name": self.devices.name(d), "model": v.get("model") or "", "main": bool(v.get("main")),
             "light": device_light(self.cfg, d, self.devices), "theme": device_theme(self.cfg, d, self.devices),
             "connected": d in online}
            for d, v in self.devices.data.items()]}

    def wlan_msg(self):
        return {"t": "wlan", "hosts": self.wlan_tls.ips, "port": self.wlan_port}

    async def watch_wlan(self):
        """LAN-Adressen beobachten: bei Wechsel neues Zertifikat und neue Adressen an den Launcher."""
        while True:
            await asyncio.sleep(60)
            try:
                if self.wlan_tls.reload():
                    for ws in list(self.ctl_clients):
                        if is_loopback(ws.remote_address):
                            await ws.send(json.dumps(self.wlan_msg()))
            except Exception as e:  # noqa: BLE001
                log.error("WLAN-Zertifikat: %s", e)

    def device_panels(self, dev):
        """Start-Panels eines Geräts je Spiel (devices.json panel, z. B. "star-citizen/handy"): {spiel: panel}.
        Nur vorhandene Panels; die Seite nimmt sie, solange am Gerät nichts anderes gewählt wurde."""
        key = self.devices.panel(dev) if dev else None
        if not key or key not in self.profiles.panels:
            return {}
        g, _, p = key.partition("/")
        return {g: p}

    def tiles_for(self, dev):
        """Kacheln eines Geräts: devices.json tiles (IDs) filtert launcher.json, sonst alle."""
        ids = self.devices.tiles(dev) if dev else None
        return self.tiles if ids is None else [t for t in self.tiles if t.get("id") in ids]

    async def ctl_send(self, msg):
        """Befehl an alle verbundenen Launcher (z. B. {"t":"mode","mode":"panel"}). Kacheln bekommt jedes Gerät
        gefiltert (tiles_for); einen Ansichtswechsel nur Geräte, die die Kachel haben."""
        data = json.dumps(msg)
        for ws in list(self.ctl_clients):
            dev = self.ctl_device.get(ws)
            out = data
            if msg.get("t") == "tiles":
                out = json.dumps(dict(msg, tiles=self.tiles_for(dev)))
            elif (msg.get("t") == "mode" and self.tiles
                  and not any(t.get("id") == msg.get("mode") for t in self.tiles_for(dev))):
                continue   # Gerät ohne diese Kachel (ohne launcher.json-Kacheln: wie bisher an alle)
            try:
                await ws.send(out)
            except Exception:  # noqa: BLE001
                pass

    async def ctl_handler(self, ws):
        peer = ws.remote_address[0] if ws.remote_address else "?"
        self.ctl_clients[ws] = None
        dev = device_cookie(ws)
        self.ctl_device[ws] = dev
        log.info("Launcher verbunden: %s%s", peer, f" ({self.devices.name(dev)})" if dev else "")
        try:
            if self.tiles:
                await ws.send(json.dumps({"t": "tiles", "tiles": self.tiles_for(dev)}))
            await ws.send(json.dumps(self.maps_msg()))
            # Feste Ausrichtung: der Launcher stellt sie selbst wieder her, sobald er nach vorn kommt
            # (spacedesk schaltet beim Start die automatische Drehung mit Hochformat ein). -1 = nicht anfassen
            await ws.send(json.dumps(self.rotation_msg(dev)))
            # Betriebsart: Startbildschirm (Standard) oder Begleit-Modus (ohne Root)
            await ws.send(json.dumps(self.tablet_mode_msg(dev)))
            # Light-Modus für schwache Geräte (Standard aus)
            await ws.send(json.dumps(self.light_msg(dev)))
            await ws.send(json.dumps(self.theme_msg(dev)))
            if self.volume_state:
                await ws.send(json.dumps(self.volume_msg()))
            # WLAN-Adressen für den Launcher (nur über USB/loopback mitteilen - dort ist die Kopplung physisch)
            if self.wlan_tls and is_loopback(ws.remote_address):
                await ws.send(json.dumps(self.wlan_msg()))
            await self.wake_wlan(ws, peer)
            # Wunsch der Automatik auch für später verbundene Launcher (nur Web-Ansichten, damit eine
            # App-Kachel nicht bei jedem Neuverbinden gestartet wird)
            # Nur nach einer Änderung, die noch kein Launcher bekommen hat - ein Wechsel von Hand bleibt
            # sonst über ein Neuverbinden hinweg bestehen.
            if self.auto_pending and any(t.get("id") == self.auto_mode and t.get("type") == "web"
                                         for t in self.tiles_for(dev)):
                await ws.send(json.dumps({"t": "mode", "mode": self.auto_mode}))
                self.auto_pending = False
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if msg.get("t") == "ping":
                    await ws.send('{"t":"pong"}')
                elif msg.get("t") == "light_set" and isinstance(msg.get("on"), bool):
                    # Hinweis „Karte bremst das Gerät“ am Tablet: Light-Modus für dieses Gerät merken
                    if dev and self.devices.set_light(dev, msg["on"]):
                        await self.send_light(dev)
                    else:
                        log.warning("Light-Modus: Gerät unbekannt (nicht per USB gekoppelt) - nicht gespeichert")
                        await ws.send(json.dumps(self.light_msg(dev)))
                elif msg.get("t") == "visited":
                    # Web-Kachel hat eine Seite geladen -> Verlauf (am PC, auf der Startseite löschbar)
                    if self.web.add_history(msg.get("url"), msg.get("title")):
                        await self.broadcast_web()
                elif msg.get("t") == "state" and isinstance(msg.get("mode"), str):
                    prev = self.ctl_clients.get(ws)
                    self.ctl_clients[ws] = msg["mode"]
                    if prev != msg["mode"]:
                        log.info("Launcher-Modus: %s", msg["mode"])
                        # Android startet spacedesk beim USB-Zubehör-Wechsel von selbst ("Immer"-Wahl). Kurz
                        # nach dem Anstecken zurück zum Launcher; per Kachel gestartet heißt es "app:screen".
                        if (msg["mode"] == "app:extern" and time.monotonic() < self.plugged_until
                                and self.cfg.get("launcher_after_plug", True)):
                            asyncio.get_running_loop().create_task(self.back_from_autostart(ws))
                        # Ansicht gewechselt oder App gestartet ("app:<id>"): Die bisherigen Seiten laufen im
                        # Hintergrund weiter und bekommen kein pointerup mehr - alles Gehaltene freigeben.
                        # (Die neue Ansicht war verdeckt und hält noch nichts.)
                        if prev is not None:
                            await self.release_everything()
        except Exception as e:  # noqa: BLE001
            log.info("Launcher %s getrennt: %s", peer, e.__class__.__name__)
        finally:
            self.ctl_clients.pop(ws, None)
            self.ctl_device.pop(ws, None)

    # ---------------- Profile ----------------
    def unmapped(self, key):
        prof = self.profiles.get(key)
        if not prof:
            return []
        def mapped(b):
            need = needed_keys(b)
            if need is not None:
                return all(k and self.out.can({"key": k}) for k in need)
            return self.out.can(b) or "macro" in b or "open" in b or "page" in b
        return [i for i, b in prof["buttons"].items() if not mapped(b)]

    def maps_msg(self):
        """Karten-Kachel: Spiele mit Anbietern (games.json) und das laufende Spiel."""
        return {"t": "maps", "current": self.game,
                "games": [{"id": g["id"], "name": g["name"], "maps": g["maps"]} for g in self.profiles.map_games()]}

    def maps_list(self):
        """Editor, Reiter „Karten“: alle Spiele mit aktueller und Standard-Kartenliste."""
        p = self.profiles
        in_json = {g["id"] for g in p.games}
        out = []
        for gid in p.game_ids():
            g = p.game(gid)
            if not g:
                continue
            out.append({"id": gid, "name": g["name"], "maps": g["maps"], "default": p.default_maps(gid),
                        "custom": gid in self.user_maps.maps, "source": "games" if gid in in_json else "library"})
        return {"t": "maps_list", "games": out, "current": self.game}

    async def maps_edit(self, msg):
        """maps_* aus dem Editor; gibt die Antwort zurück."""
        t, gid = msg.get("t"), msg.get("game")
        g = self.profiles.game(gid) if isinstance(gid, str) else None
        if t == "maps_list":
            return self.maps_list()
        if not g:
            raise ValueError("Spiel unbekannt")
        if t in ("maps_save", "maps_reset"):
            if t == "maps_save" and not isinstance(msg.get("maps"), list):
                raise ValueError("maps muss eine Liste sein")
            self.user_maps.set(gid, msg["maps"] if t == "maps_save" else None)
            self.profiles.user_maps = self.user_maps.maps
            log.info("Editor: Karten für %s %s", gid, "gespeichert" if t == "maps_save" else "zurückgesetzt")
            await self.ctl_send(self.maps_msg())
            return dict(self.maps_list(), saved=gid)
        if t == "maps_lookup":
            try:
                maps = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: mapgenie.lookup(g["name"], force=True))
            except Exception as e:  # noqa: BLE001 - jeder Netzfehler als Meldung, Editor bleibt verbunden
                raise ValueError(f"Map Genie nicht erreichbar ({e.__class__.__name__})") from e
            return {"t": "maps_found", "game": gid, "maps": maps}
        if t == "maps_show":
            url = msg.get("url")
            if not any(m["url"] == url for m in g["maps"]):
                raise ValueError("Karte erst speichern, dann zeigen")
            targets = [ws for ws, dev in list(self.ctl_device.items())
                       if any(t2.get("type") == "maps" for t2 in self.tiles_for(dev))]
            if not targets:
                raise ValueError("Kein verbundenes Tablet mit Karten-Kachel")
            data = json.dumps({"t": "map_show", "game": gid, "url": url})
            for ws in targets:
                try:
                    await ws.send(data)
                except Exception:  # noqa: BLE001
                    pass
            return {"t": "maps_shown", "game": gid}
        raise ValueError("unbekannte Anfrage")

    def games_info(self):
        return [self.profiles.summary(g) for g in self.profiles.game_ids()]

    def panel_of(self, ws):
        key = self.client_panel.get(ws)
        return key if key in self.profiles.panels else self.profiles.default_key(self.game)

    async def reload_profiles(self):
        games_changed = self.profiles.load_games()
        if self.user_maps.load():
            self.profiles.user_maps = self.user_maps.maps
            games_changed = True
        changed = self.profiles.scan()
        if games_changed:
            await self.ctl_send(self.maps_msg())
        if not changed and not games_changed:
            return
        await self.broadcast({"t": "profiles", "changed": changed,
                              "game": self.profiles.summary(self.game) if self.game else None})

    async def watch_layout(self):
        while True:
            await asyncio.sleep(1)
            await self.check_launcher()
            try:
                await self.reload_profiles()
            except Exception as e:  # noqa: BLE001
                log.error("Profile: %s", e)

    async def check_launcher(self):
        try:
            mtime = self.launcher_path.stat().st_mtime
        except OSError:
            return
        if mtime == self.launcher_mtime:
            return
        try:
            self.load_launcher()
        except Exception as e:  # noqa: BLE001 – kaputte Datei: alte Kacheln behalten
            log.error("launcher.json fehlerhaft, alte Kacheln bleiben: %s", e)
            self.launcher_mtime = mtime
            return
        await self.ctl_send({"t": "tiles", "tiles": self.tiles})
        if self.on_tiles_changed:
            self.on_tiles_changed()

    async def web_message(self, ws, msg):
        """Startseite der Web-Kachel (/ws): öffnen, Lesezeichen setzen/entfernen, Verlauf löschen."""
        t = msg.get("t")
        try:
            if t == "web_open":
                err = await self.send_url(msg.get("url"), from_pc=False)
                if err:
                    await ws.send(json.dumps({"t": "web_error", "msg": err}))
                return
            if t == "web_bookmark":
                self.web.bookmark(msg.get("url"), msg.get("title"), add=msg.get("add") is not False)
            elif t == "web_clear":
                self.web.clear_history()
                log.info("Web-Verlauf gelöscht")
            await self.broadcast_web()
        except (ValueError, OSError) as e:
            await ws.send(json.dumps({"t": "web_error", "msg": str(e)}))

    async def broadcast(self, msg):
        data = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send(data)
            except Exception:  # noqa: BLE001
                pass

    # ---------------- HTTP ----------------
    def origin_ok(self, origin, host):
        if origin in self.allowed_origins:
            return True
        # WLAN-Zugang (TLS): Seite wurde über eine LAN-Adresse des PCs geladen - genau diese Adressen und
        # dieser Port, keine Hostnamen (DNS-Rebinding)
        if self.wlan_tls:
            return origin in {f"https://{ip}:{self.wlan_port}" for ip in self.wlan_tls.ips}
        return False

    def http(self, connection, request):
        path = request.path.split("?", 1)[0]
        # WLAN: begrenzte Zahl gleichzeitiger Verbindungen (ein Gerät im LAN soll den Hub nicht lahmlegen)
        if (not is_loopback(connection.remote_address) and self.wlan_server is not None
                and len(self.wlan_server.connections) > WLAN_MAX_CONN):
            return connection.respond(503, "busy\n")
        if path == "/edit":
            # Editor am PC: nur eigene Herkunft (exakt) und nur loopback; Anmeldung per Token im 1. Paket
            if request.headers.get("Origin") not in self.allowed_origins or not is_loopback(connection.remote_address):
                log.warning("Editor-Verbindung abgelehnt (Origin %s)", request.headers.get("Origin"))
                return connection.respond(403, "forbidden\n")
            return None
        if path == "/send":
            # Nur PC-Programme: loopback, keine Webseite (Origin), dazu der Schlüssel aus secret.key im
            # ersten Paket. Das Tablet erreicht den Hub per adb reverse ebenfalls über loopback, kennt den
            # Schlüssel aber nur als HttpOnly-Cookie - Seiten-Skripte können ihn nicht lesen.
            # Browser-Erweiterungen (Origin chrome-/moz-extension://) dürfen mit dem reinen Sende-Schlüssel.
            origin = request.headers.get("Origin")
            if not is_loopback(connection.remote_address) or (
                    origin is not None and not origin.startswith(EXTENSION_ORIGINS)):
                log.warning("Senden abgelehnt (Origin %s)", origin)
                return connection.respond(403, "forbidden\n")
            return None
        if path in ("/ws", "/ctl"):
            # Kopplung: Der Launcher sendet das beim Setup per ADB übergebene Geheimnis als Cookie mit.
            # Andere Apps auf dem Tablet (erreichen localhost:8765 ebenfalls) haben es nicht.
            if self.require_secret and not hmac.compare_digest(
                    cookie_value(request.headers.get("Cookie", ""), "deck").encode(), self.secret.encode()):
                log.warning("WebSocket %s ohne gültige Kopplung abgelehnt", path)
                return connection.respond(401, "unauthorized\n")
            # Fremde Webseiten (im PC- oder Tablet-Browser) dürfen keine Tasten senden.
            # Ohne Origin = native Clients (Launcher-App, Testskripte).
            origin = request.headers.get("Origin")
            if origin is not None and not self.origin_ok(origin, request.headers.get("Host", "")):
                log.warning("WebSocket von fremder Herkunft abgelehnt: %s", origin)
                return connection.respond(403, "forbidden\n")
            if origin is None and not is_loopback(connection.remote_address):
                log.warning("WebSocket ohne Origin von %s abgelehnt", connection.remote_address)
                return connection.respond(403, "forbidden\n")
            return None  # WebSocket-Handshake
        if path == "/api/web":
            if not is_loopback(connection.remote_address) and not hmac.compare_digest(
                    cookie_value(request.headers.get("Cookie", ""), "deck").encode(), self.secret.encode()):
                return connection.respond(401, "unauthorized\n")
            body = json.dumps(self.web.data()).encode()
            headers = Headers([("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))),
                               ("Cache-Control", "no-store"), ("Content-Security-Policy", CSP),
                               ("X-Content-Type-Options", "nosniff")])
            return Response(200, "OK", headers, body)
        m = re.fullmatch(r"/games/([^/]*)/cover", path)
        if m:
            # Coverbild: Pfad nur aus der Bibliothek (nie aus der Anfrage); über WLAN nur gekoppelt
            if not is_loopback(connection.remote_address) and not hmac.compare_digest(
                    cookie_value(request.headers.get("Cookie", ""), "deck").encode(), self.secret.encode()):
                return connection.respond(401, "unauthorized\n")
            cov = self.profiles.cover_file(m.group(1))
            try:
                body = Path(cov[0]).read_bytes() if cov else None
            except OSError:
                body = None
            if body is None:
                return connection.respond(404, "not found\n")
            headers = Headers([("Content-Type", cov[1]), ("Content-Length", str(len(body))),
                               ("Cache-Control", "private, max-age=86400"), ("Content-Security-Policy", CSP),
                               ("X-Content-Type-Options", "nosniff")])
            return Response(200, "OK", headers, body)
        if path == "/api/dashboards" or path.startswith("/api/dashboards/"):
            # nur Anzeigedaten (Positionen, Sensor-IDs); über WLAN nur gekoppelt wie die Profile
            if not is_loopback(connection.remote_address) and not hmac.compare_digest(
                    cookie_value(request.headers.get("Cookie", ""), "deck").encode(), self.secret.encode()):
                return connection.respond(401, "unauthorized\n")
            name = path[len("/api/dashboards/"):] if path != "/api/dashboards" else None
            try:
                if name is None:
                    data = self.dashboards.list()
                else:
                    if name == "default":       # gewählter Standard (Editor), sonst deck
                        name = self.dashboards.get_default()
                    data, origin = self.dashboards.load(name)
                    if origin == dashboard.BUNDLED and name == "deck":   # eigene und MoBro-Dashboards bleiben, wie sie sind
                        data = json.loads(themes.recolor(json.dumps(data), self.request_theme(request)))
            except FileNotFoundError:
                return connection.respond(404, "not found\n")
            except ValueError as e:
                log.warning("Dashboard %s: %s", name, e)
                return connection.respond(500, "dashboard invalid\n")
            body = json.dumps(data, ensure_ascii=False).encode()
            ctype = "application/json; charset=utf-8"
        elif path == "/api/games" or path.startswith("/profiles/"):
            # über WLAN nur gekoppelt (enthält z. B. Programmpfade der "open"-Tasten)
            if not is_loopback(connection.remote_address) and not hmac.compare_digest(
                    cookie_value(request.headers.get("Cookie", ""), "deck").encode(), self.secret.encode()):
                return connection.respond(401, "unauthorized\n")
            if path == "/api/games":
                dev = cookie_value(request.headers.get("Cookie", ""), "deckdev")
                body = json.dumps({"current": self.game, "default": self.profiles.default_key(self.game),
                                   "device": self.device_panels(dev if valid_id(dev) else None),
                                   "games": self.games_info()}).encode()
            else:
                m = re.fullmatch(r"/profiles/([a-z0-9-]+)/([a-z0-9-]+)\.json", path)
                prof = self.profiles.get(f"{m.group(1)}/{m.group(2)}") if m else None
                if not prof:
                    return connection.respond(404, "not found\n")
                body = json.dumps(dict(prof["layout"], unmapped=self.unmapped(f"{m.group(1)}/{m.group(2)}"))).encode()
            ctype = "application/json"
        elif path == "/lib/theme.css":
            body = themes.css(self.request_theme(request)).encode()
            ctype = "text/css; charset=utf-8"
        else:
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            if rel.endswith("/"):
                rel += "index.html"
            # keine Backslashes/Laufwerke/UNC (sonst öffnet Windows ggf. SMB-Freigaben)
            if "\\" in rel or ":" in rel or ".." in rel.split("/"):
                return connection.respond(404, "not found\n")
            f = (WEB / rel).resolve()
            if WEB not in f.parents or not f.is_file():
                return connection.respond(404, "not found\n")
            body = f.read_bytes()
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
                ctype += "; charset=utf-8"
        headers = Headers([("Content-Type", ctype), ("Content-Length", str(len(body))),
                           ("Cache-Control", "no-cache"), ("Content-Security-Policy", CSP),
                           ("X-Content-Type-Options", "nosniff")])
        return Response(200, "OK", headers, body)

    # ---------------- WebSocket ----------------
    async def handler(self, ws):
        p = ws.request.path.split("?", 1)[0]
        if p == "/ctl":
            return await self.ctl_handler(ws)
        if p == "/edit":
            return await self.edit_handler(ws)
        if p == "/send":
            return await self.send_handler(ws)
        peer = ws.remote_address[0] if ws.remote_address else "?"
        held = self.clients[ws] = {}
        pcst = self.pc.new_client()
        log.info("Client verbunden: %s (%d aktiv)", peer, len(self.clients))
        try:
            await ws.send(json.dumps({"t": "hello", "mode": self.out.name, "web": web_version(),
                                      "game": self.profiles.summary(self.game) if self.game else None}))
            if self.volume_state:
                await ws.send(json.dumps(self.volume_msg()))
            if self.mixer_state:
                await ws.send(json.dumps(self.mixer_msg()))
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                t, bid = msg.get("t"), msg.get("id")
                # Panel der Taste: von der Seite mitgeschickt (sicher auch direkt nach einem Neuverbinden),
                # sonst das zuletzt gemeldete bzw. Standard-Panel
                # Ein "up" nutzt den mitgeschickten Schlüssel unverändert - auch wenn das Panel inzwischen
                # gelöscht ist, findet es so den Snapshot in held und lässt die Taste los.
                pk = msg.get("panel") if isinstance(msg.get("panel"), str) else None
                if pk is not None and t == "down" and pk not in self.profiles.panels:
                    pk = ""   # unbekanntes Panel (gelöscht/umbenannt): Druck verwerfen
                pk = self.panel_of(ws) if pk is None else pk
                if t == "ping":
                    await ws.send('{"t":"pong"}')
                    continue
                if t == "stats_sub":
                    self.stats.subscribe(ws)
                    continue
                if t == "stats_unsub":
                    self.stats.unsubscribe(ws)
                    continue
                if self.pc.handle(pcst, msg):
                    continue
                if t in ("web_open", "web_bookmark", "web_clear"):
                    await self.web_message(ws, msg)
                    continue
                if t == "panel":
                    key = f"{msg.get('game')}/{msg.get('panel')}"
                    if key in self.profiles.panels and key != self.client_panel.get(ws):
                        # anderes Panel: Gehaltenes dieser Seite loslassen (gleiche IDs können anderes bedeuten)
                        self.drop_pulses(owner=ws)
                        for btn, _ in held.values():
                            self.fire(btn, False)
                        held.clear()
                        self.client_panel[ws] = key
                        log.info("Panel %s (%s)", key, peer)
                    continue
                if not isinstance(bid, str):
                    continue
                hk = f"{pk}/{bid}"
                cur = self.profiles.get(pk)
                cur_btn = cur["buttons"].get(bid) if cur else None
                if msg.get("dir") in ("up", "down") and cur_btn and "slider" in cur_btn:
                    hk += "/" + msg["dir"]   # Regler: up und down getrennt halten (nur bei Reglern)
                elif cur_btn and "segment" in cur_btn and type(msg.get("seg")) is int:
                    hk += "/s" + str(msg["seg"])   # Auswahlleiste: jeder Teil hält seine eigene Taste
                if t == "down":
                    if hk in held:          # weiterer Finger auf derselben Taste
                        held[hk][1] += 1
                    else:
                        prof = self.profiles.get(pk)
                        if not prof or bid not in prof["buttons"]:
                            continue
                        # Snapshot: Loslassen nutzt die Belegung vom Drücken, auch nach Profil-Reload
                        snap = button_for_press(prof["buttons"][bid], msg)
                        if snap is None:
                            continue
                        held[hk] = [dict(snap, _panel=pk), 1]
                        self.fire(held[hk][0], True, owner=ws)
                elif t == "up" and hk in held:
                    held[hk][1] -= 1
                    if held[hk][1] <= 0:
                        self.fire(held.pop(hk)[0], False)
        except Exception as e:  # noqa: BLE001
            log.info("Verbindung %s beendet: %s", peer, e.__class__.__name__)
        finally:
            self.stats.unsubscribe(ws)
            self.cancel_macros(owner=ws)
            self.drop_pulses(owner=ws)
            self.pc.drop_client(pcst)
            for btn, _ in held.values():
                self.fire(btn, False)
            if held:
                log.warning("Client weg - %d gehaltene Taste(n) losgelassen", len(held))
            self.clients.pop(ws, None)
            self.client_panel.pop(ws, None)
            log.info("Client getrennt: %s (%d aktiv)", peer, len(self.clients))

    async def release_everything(self):
        self.cancel_macros()
        n = self.pc.release_all() + self.release_panel_keys() + self.drop_pulses() + self.flush_late_releases()
        if n:
            await self.broadcast({"t": "released"})   # Seiten setzen ihren Tastenzustand zurück

    def release_panel_keys(self):
        """Alle von Panel-Clients gehaltenen Tasten loslassen (z. B. Launcher wechselt die Ansicht)."""
        n = 0
        for held in self.clients.values():
            for btn, _ in held.values():
                self.fire(btn, False)
                n += 1
            held.clear()
        if n:
            log.warning("Ansicht gewechselt - %d gehaltene Panel-Taste(n) losgelassen", n)
        return n

    def _macro_done(self, bid, task):
        self.macros.pop(bid, None)
        if not task.cancelled() and task.exception():
            log.error("Makro %s: %r", bid, task.exception())

    def cancel_macros(self, owner=None):
        """Laufende Makros abbrechen (alle oder nur die eines Clients). Ein key-Schritt drückt und lässt
        ohne await dazwischen los - beim Abbruch kann also keine Taste hängen bleiben."""
        for bid, (task, who) in list(self.macros.items()):
            if owner is None or who is owner:
                task.cancel()
                log.warning("Makro %s abgebrochen", bid)

    def fire(self, btn, down, owner=None):
        if not btn:
            return
        if "open" in btn:
            # Programm/Datei/URL am PC öffnen - beim Drücken einmal (Ziel stammt aus layout.json am PC)
            # Sperre 2 s: Doppeltippen, prellender Touch oder zwei Clients öffnen nicht doppelt
            now = time.monotonic()
            ok_key = f"{btn.get('_panel', '')}/{btn['id']}"
            if down and now - self.last_open.get(ok_key, -1e9) >= 2:
                self.last_open[ok_key] = now
                log.info("OPEN %-22s -> %s", btn["id"], open_label(btn["open"]))
                asyncio.get_running_loop().run_in_executor(None, open_on_pc, btn["open"])
            return
        if "macro" in btn:
            # Makro läuft beim Drücken einmal ab (Loslassen ohne Wirkung); nicht doppelt parallel
            mk = f"{btn.get('_panel', '')}/{btn['id']}"
            if down and mk not in self.macros:
                log.info("MAKRO %-21s (%d Schritte)", btn["id"], len(btn["macro"]))
                task = asyncio.get_running_loop().create_task(self.pc.run_macro(btn["macro"]))
                self.macros[mk] = (task, owner)
                task.add_done_callback(lambda t, i=mk: self._macro_done(i, t))
            return
        target = f"key {btn.get('key')}" if self.out.name == "keyboard" else f"joy {btn.get('joy')}"
        if not self.out.can(btn):
            log.info("%-4s %-22s -> (keine Belegung für %s)", "DOWN" if down else "UP", btn["id"], self.out.name)
            return
        if not btn.get("hold"):
            # Impuls: Viele Spielaktionen ("tap") lösen nur bei kurzem Druck aus - unabhängig davon,
            # wie lange der Finger liegt, die Taste PULSE_S lang drücken. "hold": true = Finger hält Taste.
            if not down:
                return
            self._enqueue_pulse(btn, target, owner)
            return
        min_s = btn.get("press_ms", 0) / 1000
        late = self.late_release.pop(target, None)
        if late:
            late[0].cancel()   # verzögertes Loslassen ersetzt (erneuter Druck oder neuer Termin)
        if down:
            self.hold_since[target] = time.monotonic()
        elif min_s:
            # Spiel wertet erst lange Drücke: frühestens nach press_ms loslassen
            rest = min_s - (time.monotonic() - self.hold_since.get(target, 0))
            if rest > 0:
                h = asyncio.get_running_loop().call_later(rest, self._late_release, btn, target)
                self.late_release[target] = (h, btn)
                return
        self._press_release(btn, down, target)

    def _late_release(self, btn, target):
        self.late_release.pop(target, None)
        self._press_release(btn, False, target)

    def flush_late_releases(self):
        """Verzögert gehaltene Tasten (press_ms) sofort loslassen - Ansichtswechsel, Hub-Ende."""
        n = 0
        for target, (h, btn) in list(self.late_release.items()):
            h.cancel()
            self.late_release.pop(target, None)
            self._press_release(btn, False, target)
            n += 1
        return n

    def _press_release(self, btn, down, target):
        try:
            (self.out.press if down else self.out.release)(btn)
            log.info("%-4s %-22s -> %s", "DOWN" if down else "UP", btn["id"], target)
        except Exception as e:  # noqa: BLE001
            log.error("Ausgabefehler %s: %s", btn["id"], e)

    def _enqueue_pulse(self, btn, target, owner=None):
        """Impulse pro Taste nacheinander (drücken PULSE_S, Pause PULSE_GAP_S). Sonst verschmelzen schnell
        aufeinanderfolgende Impulse derselben Taste (Regler über mehrere Stufen, schnelles Tippen) zu einem
        einzigen Druck. Warteschlange begrenzt (Flut)."""
        k = target
        q = self.pulse_q.setdefault(k, [])
        if btn.get("press_ms") and (q or k in self.pulse_tasks):
            # langer Druck läuft schon: weitere Tipps nicht anhängen (sonst Sekunden gedrückt, mehrfach ausgelöst)
            log.info("PULS %-22s verworfen (langer Druck läuft noch)", btn["id"])
            return
        if len(q) >= PULSE_MAX_QUEUE:
            log.warning("Impulse für %s verworfen (Warteschlange voll)", btn["id"])
            return
        q.append((btn, owner))
        if k not in self.pulse_tasks:
            self.pulse_tasks[k] = asyncio.get_running_loop().create_task(self._pulse_worker(k, target))

    async def _pulse_worker(self, k, target):
        q = self.pulse_q[k]
        try:
            while q:
                btn, _owner = q.pop(0)
                try:
                    self.out.press(btn)
                    log.info("PULS %-22s -> %s", btn["id"], target)
                except Exception as e:  # noqa: BLE001
                    log.error("Ausgabefehler %s: %s", btn["id"], e)
                    continue
                try:
                    # press_ms: Spiel wertet erst lange Drücke (z. B. delayed_press) - so lange halten
                    await asyncio.sleep(max(PULSE_S, btn.get("press_ms", 0) / 1000))
                finally:   # auch beim Abbruch nie eine Taste gedrückt lassen
                    try:
                        self.out.release(btn)
                    except Exception as e:  # noqa: BLE001
                        log.error("Ausgabefehler beim Loslassen %s: %s", btn["id"], e)
                await asyncio.sleep(PULSE_GAP_S)
        finally:
            self.pulse_tasks.pop(k, None)
            if not self.pulse_q.get(k):
                self.pulse_q.pop(k, None)

    def drop_pulses(self, owner=None, stop=False):
        """Noch nicht gesendete Impulse verwerfen - alle (Ansicht gewechselt) oder nur die eines Clients
        (getrennt, Panelwechsel). stop=True bricht auch laufende Impulse ab (Hub-Ende); deren finally lässt los."""
        n = 0
        for q in self.pulse_q.values():
            keep = [e for e in q if owner is not None and e[1] is not owner]
            n += len(q) - len(keep)
            q[:] = keep
        if stop:
            for task in list(self.pulse_tasks.values()):
                task.cancel()
        return n


# ---------------- ADB: Tablet per USB ----------------
def find_adb(cfg):
    for cand in (cfg.get("adb"), ROOT / "tools/platform-tools/adb.exe", shutil.which("adb")):
        if cand and Path(cand).is_file():
            return str(cand)
    return None


async def run(*args, timeout=10):
    # CREATE_NO_WINDOW: ohne eigene Konsole (pythonw/Autostart) öffnete sonst jeder adb-Aufruf ein Fenster
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                             stderr=asyncio.subprocess.STDOUT,
                                             stdin=asyncio.subprocess.DEVNULL, creationflags=0x08000000)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        await p.wait()
        return -1, f"Timeout: {' '.join(map(str, args[1:]))}"
    return p.returncode, out.decode(errors="replace")


async def sync_time(adb, serial, cfg):
    """Setzt Uhrzeit (ms seit Epoche, UTC) und Zeitzone am Tablet - geht als normaler Shell-Nutzer."""
    tz = cfg.get("tablet_timezone", "Europe/Berlin")
    ms = int(time.time() * 1000)
    rc1, o1 = await run(adb, "-s", serial, "shell", "cmd", "alarm", "set-timezone", tz)
    rc2, o2 = await run(adb, "-s", serial, "shell", "cmd", "alarm", "set-time", str(ms))
    if rc1 or rc2 or o1.strip() or o2.strip():
        log.warning("Tablet %s: Uhrzeit setzen fehlgeschlagen: %s %s", serial, o1.strip(), o2.strip())
        return False
    log.info("Tablet %s: Uhrzeit vom PC übernommen (%s)", serial, tz)
    return True


def open_label(target):
    """Fürs Log: bei URLs nur Schema und Host (keine Zugangsdaten aus der Query), sonst der Dateiname."""
    if re.match(r"(?i)^https?://", target):
        return target.split("/")[0] + "//" + target.split("/")[2].rsplit("@", 1)[-1]
    return Path(target).name


def open_on_pc(target):
    # ShellExecute (os.startfile) braucht je nach Ziel (.lnk, Shell-Ordner) COM im aufrufenden Thread
    ole32 = ctypes.windll.ole32
    init = ole32.CoInitializeEx(None, 0x2 | 0x4)   # APARTMENTTHREADED | DISABLE_OLE1DDE
    try:
        os.startfile(target)   # URL -> Standardbrowser, Pfad -> zugehöriges Programm
    except OSError as e:
        log.error("Öffnen fehlgeschlagen (%s): %s", open_label(target), e)
    finally:
        if init in (0, 1):     # S_OK / S_FALSE -> wieder freigeben
            ole32.CoUninitialize()


WLAN_MAX_CONN = 16
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://")
HOME_COMPONENT = "app.tabletdeck.launcher/.HomeAlias"       # HOME-Eintrag (activity-alias im Manifest)
HOME_ACTIVITY = "app.tabletdeck.launcher/.HomeActivity"      # Ziel des Alias, auch der Start per MAIN/LAUNCHER
# resolve-activity meldet je nach Android den Alias oder sein Ziel (auch mit ausgeschriebenem Klassennamen)
HOME_NAMES = {HOME_COMPONENT, HOME_ACTIVITY,
              "app.tabletdeck.launcher/app.tabletdeck.launcher.HomeAlias",
              "app.tabletdeck.launcher/app.tabletdeck.launcher.HomeActivity"}
AUTOSTART_PKG = "ph.spacedesk.beta"   # startet per USB-Zubehör-"Immer"-Wahl von selbst


def tile_ports(bridge):
    """Ports weiterer PC-Dienste aus launcher.json (z. B. Dashboard), per adb reverse ans Tablet."""
    return sorted({t["port"] for t in bridge.tiles if t.get("type") == "web" and t.get("port", 8765) != 8765})


def tablet_rotation(cfg):
    """Feste Ausrichtung aus config.json: 0..3 wie Android user_rotation, None = nicht anfassen."""
    rot = cfg.get("tablet_rotation", 1)
    if rot is not None and not (type(rot) is int and 0 <= rot <= 3):   # bool ausschließen
        log.error("config tablet_rotation=%r ungültig (0-3 oder null) - Ausrichtung wird nicht gehalten", rot)
        rot = None
    return rot


PAIRING_RECEIVER = "app.tabletdeck.launcher/.PairingReceiver"


def hub_ca_bundle(tls_dir):
    """Öffentliche WLAN-CA (Wurzel + Zwischen-CA) als Base64 für den PairingReceiver des Launchers, oder None.
    Nur die beiden .crt-Dateien - nie ein Schlüssel (zusätzliche Prüfung auf "PRIVATE KEY")."""
    import base64
    try:
        pem = (Path(tls_dir) / "ca.crt").read_bytes() + (Path(tls_dir) / "inter.crt").read_bytes()
    except OSError:
        return None
    parts = [(Path(tls_dir) / n).read_bytes() for n in ("ca.crt", "inter.crt")]
    if b"PRIVATE KEY" in pem or any(p.count(b"-----BEGIN CERTIFICATE-----") != 1 for p in parts):
        log.error("WLAN-CA: tls/ca.crt bzw. inter.crt unerwartet aufgebaut - nicht ans Tablet geschickt")
        return None
    return base64.b64encode(pem).decode("ascii")


LAUNCHER_PKG = "app.tabletdeck.launcher"


def device_cookie(ws):
    """Gerätekennung aus dem Cookie deckdev (setzt der Launcher, siehe devices.py) oder None."""
    try:
        v = cookie_value(ws.request.headers.get("Cookie", ""), "deckdev")
    except AttributeError:
        return None
    return v if valid_id(v) else None


def device_rotation(cfg, serial, devices=None):
    """Ausrichtung eines Geräts: devices.json rotation, sonst tablet_rotation aus config.json."""
    rot = tablet_rotation(cfg)
    return devices.rotation(serial, rot) if devices is not None and serial else rot


def device_theme(cfg, serial, devices=None):
    """Farbschema eines Geräts: devices.json theme, sonst tablet_theme aus config.json, sonst Standard."""
    base = cfg.get("tablet_theme", themes.DEFAULT)
    if not themes.valid(base):
        log.error("config tablet_theme=%r ungültig - nehme Standard", base)
        base = themes.DEFAULT
    return devices.theme(serial, base) if devices is not None and serial else base


def device_light(cfg, serial, devices=None):
    """Light-Modus eines Geräts: devices.json light, sonst tablet_lights[serial] aus config.json, sonst aus."""
    lights = cfg.get("tablet_lights")
    base = False
    if isinstance(lights, dict) and serial in lights:
        if isinstance(lights[serial], bool):
            base = lights[serial]
        else:
            log.error("config tablet_lights[%s]=%r ungültig (true oder false) - nehme aus", serial, lights[serial])
    return devices.light(serial, base) if devices is not None and serial else base


def device_mode(cfg, serial, devices=None):
    """Betriebsart eines Tablets: devices.json mode, sonst tablet_modes[serial] aus config.json, sonst
    tablet_mode (Standard home).
    So kann ein gerootetes Tablet Startbildschirm sein und ein zweites gleichzeitig im Begleit-Modus laufen."""
    base = None
    modes = cfg.get("tablet_modes")
    if isinstance(modes, dict) and serial in modes:
        if modes[serial] in ("home", "companion"):
            base = modes[serial]
        else:
            log.error("config tablet_modes[%s]=%r ungültig (home oder companion) - nehme tablet_mode", serial,
                      modes[serial])
    if base is None:
        base = tablet_mode(cfg)
    return devices.mode(serial, base) if devices is not None and serial else base


def tablet_mode(cfg):
    """Betriebsart aus config.json: "home" (Startbildschirm, Standard) oder "companion" (normale App, ohne Root)."""
    mode = cfg.get("tablet_mode", "home")
    if mode not in ("home", "companion"):
        log.error("config tablet_mode=%r ungültig (home oder companion) - nehme home", mode)
        mode = "home"
    return mode


def home_is_launcher(resolved):
    """Ist der gemeldete Startbildschirm (letzte Zeile von resolve-activity --brief) unser Launcher?"""
    return resolved.strip() in HOME_NAMES


def launcher_start_args():
    """am-start-Argumente für die Launcher-App: MAIN/LAUNCHER, in beiden Betriebsarten gleich."""
    return ("am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
            "-n", HOME_ACTIVITY)


def home_start_args():
    """am-start-Argumente für den Startbildschirm-Modus: HOME holt ihn auch aus anderen Apps nach vorn."""
    return ("am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME",
            "-n", HOME_ACTIVITY)


async def adb_watch(cfg, port, bridge):
    """Richtet für jedes per USB angesteckte Tablet 'adb reverse' ein (geht beim Abstecken verloren)."""
    adb = find_adb(cfg)
    if not adb:
        log.warning("adb nicht gefunden - USB-Weiterleitung aus. Tablet dann per WLAN verbinden.")
        return
    ready, warned, known = set(), set(), set()
    ca_sent = set()   # Tablets, die die WLAN-CA seit dem Anstecken bestätigt haben
    from .tablet_health import TabletHealth
    health = TabletHealth()   # Speicher, Laufzeit, Android-Ereignisse fürs Log (spacedesk, Ausschalten)
    usb_switched = set()   # USB-Modus schon umgestellt (nur einmal pro Anstecken)
    last_sync, last_seen = {}, {}
    last_home = -1e9
    proxy_port = int(cfg.get("web_proxy_port", 8766)) if cfg.get("web", True) else 0
    ports = [port] + ([proxy_port] if proxy_port else [])
    def companion(serial):
        return device_mode(cfg, serial, bridge.devices) == "companion"
    # serial -> [installiert?, Prüfzeit, zuletzt gesehen, keine Antwort seit] - fremde Geräte bleiben unangetastet
    launcher_seen = {}
    mode_sent = set()    # Tablets, die ihre Betriebsart seit dem Anstecken bestätigt haben
    id_sent = set()      # Tablets, die ihre Gerätekennung (devices.py) seit dem Anstecken bestätigt haben
    id_tries = {}        # Versuche je Anstecken (alte App ohne device_id antwortet nie mit result=1)

    async def send_id(serial):
        """Gerät eintragen (erstes = Hauptgerät) und ihm seine Kennung schicken (Cookie deckdev im Launcher)."""
        _, model = await run(adb, "-s", serial, "shell", "getprop", "ro.product.model")
        if bridge.devices.see(serial, model.strip()[:64] or None) and bridge.on_tiles_changed:
            bridge.on_tiles_changed()   # Taskleisten-Menü: Auswahl des Hauptgeräts
        rc, o = await run(adb, "-s", serial, "shell", "am", "broadcast", "--include-stopped-packages",
                          "-n", PAIRING_RECEIVER, "--es", "device_id", serial)
        if rc == 0 and "result=1" in o:
            id_sent.add(serial)
            return
        id_tries[serial] = id_tries.get(serial, 0) + 1
        if id_tries[serial] >= 5:
            id_sent.add(serial)   # aufgeben bis zum nächsten Anstecken
            log.warning("Tablet %s: Gerätekennung nicht übernommen - Launcher-App aktualisieren "
                        "(python android/build.py, adb install -r)", serial)
    GONE_S = 15  # erst nach so langer Abwesenheit gilt das Tablet als abgesteckt
    while True:
        try:
            _, out = await run(adb, "devices")
            now, unauth = set(), set()
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) == 2:
                    serial, state = parts
                    if state == "device":
                        now.add(serial)
                    elif state == "unauthorized":
                        unauth.add(serial)
                        if serial not in warned:
                            log.warning("Tablet %s: USB-Debugging am Tablet bestätigen!", serial)
            warned = unauth
            # Nur Geräte mit dem Tablet-Deck-Launcher einrichten. Andere (Handy zum Laden, zweites Tablet vor
            # der Installation) bekämen sonst Proxy, Daueranzeige, Ausrichtung und Startbildschirm verstellt.
            t_chk = asyncio.get_running_loop().time()
            for serial in list(now):
                st = launcher_seen.setdefault(serial, [None, -1e9, t_chk, None])
                st[2] = t_chk                                  # zuletzt gesehen (für das Aufräumen unten)
                need = st[0] is None or (st[0] is False and t_chk - st[1] >= 60)   # nachinstalliert? jede Minute
                if st[0] is None and st[3] is not None and t_chk - st[3] >= 60 and t_chk - st[1] < 60:
                    need = False                               # Paketdienst hängt: nur noch minütlich fragen
                if need:
                    rc, o = await run(adb, "-s", serial, "shell", "pm", "path", LAUNCHER_PKG)
                    if "package:" in o:
                        found = True
                    elif rc == 1 and not o.strip():            # sauber beantwortet: nicht installiert
                        found = False
                    else:                                      # Paketdienst noch nicht bereit, Zeitüberschreitung …
                        found = None                           # nichts merken, nächste Runde erneut
                    if found is False and st[0] is None:
                        log.info("Gerät %s: kein Tablet-Deck-Launcher installiert - wird nicht eingerichtet", serial)
                    if found is not None:
                        st[0], st[1], st[3] = found, t_chk, None
                    elif st[3] is None:
                        st[3] = t_chk                          # seit wann keine Antwort
                    elif t_chk - st[3] >= 60:
                        if st[1] < st[3]:
                            log.warning("Gerät %s: Paketabfrage beantwortet seit einer Minute nicht (%s) - "
                                        "wird nicht eingerichtet, prüfe minütlich", serial, o.strip()[-80:])
                        st[1] = t_chk
                if not st[0]:
                    now.discard(serial)
            for serial in list(launcher_seen):
                if t_chk - launcher_seen[serial][2] > 120:
                    del launcher_seen[serial]   # zwei Minuten nicht gesehen: beim nächsten Anstecken neu prüfen
            ready &= now
            bridge.usb_serials = set(ready)
            # Abgesteckt -> beim nächsten Anstecken wieder komplett einrichten. Kurze USB-Neuanmeldungen
            # (MTP-/Zubehör-Wechsel für spacedesk) zählen nicht, sonst holt der HOME-Start den Launcher
            # nach vorne und verdrängt spacedesk.
            t_now = asyncio.get_running_loop().time()
            for serial in now:
                last_seen[serial] = t_now
            for serial in list(last_seen):
                if t_now - last_seen[serial] > GONE_S:
                    del last_seen[serial]
                    known.discard(serial)
                    ca_sent.discard(serial)
                    mode_sent.discard(serial)
                    id_sent.discard(serial)
                    id_tries.pop(serial, None)
                    health.forget(serial)
                    usb_switched.discard(serial)
            # Weiterleitung prüfen: geht verloren, wenn der adb-Server neu startet
            for serial in list(ready):
                rc, lst = await run(adb, "-s", serial, "reverse", "--list")
                if rc != 0:
                    continue  # adb hakt gerade - nächste Runde erneut prüfen
                have = [ln.split()[1:] for ln in lst.splitlines()]   # Zeilen wie "UsbFfs tcp:8765 tcp:8765"
                if any([f"tcp:{p}", f"tcp:{p}"] not in have for p in ports + tile_ports(bridge)):
                    log.warning("Tablet %s: Weiterleitung verloren, richte neu ein", serial)
                    ready.discard(serial)
            for serial in now - ready:
                # spacedesk (Zweitbildschirm per USB): Der Windows-Treiber holt das Tablet nur dann in den
                # Zubehör-Modus, wenn es nicht im reinen ADB-Modus steht (nach einem Neustart der Fall).
                # VOR der Weiterleitung umstellen: Das Tablet meldet sich dabei am USB neu an - danach
                # eingerichtete Verbindungen brächen sonst mitten im Laden der Seiten ab.
                if serial not in known and serial not in usb_switched and cfg.get("spacedesk_usb", True):
                    _, conf = await run(adb, "-s", serial, "shell", "getprop", "sys.usb.config")
                    if conf.strip() == "adb":
                        log.info("Tablet %s: USB auf MTP+ADB (für spacedesk)", serial)
                        usb_switched.add(serial)
                        await run(adb, "-s", serial, "shell", "svc", "usb", "setFunctions", "mtp")
                        continue   # nach der Neuanmeldung (nächste Runde) weiter
                rc, o = 0, ""
                for p in ports + tile_ports(bridge):   # Hub, Web-Proxy, Dienste der Kacheln
                    rc, o = await run(adb, "-s", serial, "reverse", f"tcp:{p}", f"tcp:{p}")
                    if rc != 0:
                        break
                if rc != 0:
                    log.error("adb reverse fehlgeschlagen: %s", o.strip())
                    continue
                ready.add(serial)
                log.info("Tablet %s per USB verbunden -> http://localhost:%d", serial, port)
                if serial in known:
                    # nur Weiterleitung erneuert, Tablet läuft weiter. Neuanmeldung kurz nach dem Anstecken
                    # (Zubehör-Wechsel für spacedesk): Fenster für "zurück zum Launcher" verlängern.
                    if time.monotonic() < bridge.plugged_until:
                        bridge.plugged_until = time.monotonic() + 30
                    continue
                known.add(serial)
                # Betriebsart gleich beim Verbinden (sonst setzte der Steuerkanal bis zur 30-s-Runde evtl. den
                # Standard für alle Tablets); die 30-s-Runde unten wiederholt, falls das hier scheitert
                await send_id(serial)
                rc, o = await run(adb, "-s", serial, "shell", "am", "broadcast", "--include-stopped-packages",
                                  "-n", PAIRING_RECEIVER, "--es", "tablet_mode",
                                  device_mode(cfg, serial, bridge.devices))
                if rc == 0 and "result=1" in o:
                    mode_sent.add(serial)
                bridge.plugged_until = time.monotonic() + 30
                bridge.plugged_serial, bridge.homes_left = serial, 3
                await run(adb, "-s", serial, "shell", "svc", "power", "stayon", "true")  # AC+USB+kabellos
                # beim Herunterfahren des PCs schlafen gelegt (bridge/session.py) -> wieder aufwecken
                await run(adb, "-s", serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
                # Internet für die Web-Kachel über den Proxy der Bridge (localhost am Tablet -> adb reverse).
                # Chromium nimmt localhost selbst vom Proxy aus, der Hub bleibt direkt erreichbar.
                await run(adb, "-s", serial, "shell", "settings", "put", "global", "http_proxy",
                          f"localhost:{proxy_port}" if proxy_port else ":0")
                if not companion(serial):
                    # Ein App-Update (adb install -r) setzt die Startbildschirm-Wahl zurück - immer neu setzen.
                    # War der Alias aus dem Begleit-Modus noch aus (die Shell darf ihn unter Android 16 nicht
                    # einschalten), schaltet ihn der Launcher nach der ctl-Nachricht ein; die 30-s-Prüfung
                    # unten setzt den Startbildschirm dann nach.
                    await run(adb, "-s", serial, "shell", "cmd", "package", "set-home-activity",
                              HOME_COMPONENT)
                if cfg.get("tablet_autostart", True):
                    # Launcher-App in den Vordergrund. Startbildschirm-Modus: per HOME (holt ihn aus anderen
                    # Apps); Begleit-Modus: wie ein Tipp auf das App-Symbol
                    args = launcher_start_args() if companion(serial) else home_start_args()
                    await run(adb, "-s", serial, "shell", *args)
            # Uhrzeit vom PC übernehmen (Tablet hat ohne Netz keine Zeitquelle): beim Verbinden + stündlich
            loop_t = asyncio.get_running_loop().time()
            # Startbildschirm-Wahl prüfen (adb install -r von Hand setzt sie ohne Neuanmeldung zurück)
            if loop_t - last_home >= 30:
                last_home = loop_t
                for serial in ready:
                    # WLAN-CA an den Launcher (öffentliche Zertifikate; die APK enthält sie nicht, siehe
                    # HubTrust.java) - einmal je Anstecken, bis er sie bestätigt. Hier statt direkt beim
                    # Verbinden: beim Hub-Start legt der WLAN-Zugang die CA evtl. gerade erst an.
                    if serial not in ca_sent and bridge.wlan_tls:
                        ca = hub_ca_bundle(ROOT / "tls")
                        if ca:
                            rc, o = await run(adb, "-s", serial, "shell", "am", "broadcast",
                                              "--include-stopped-packages", "-n", PAIRING_RECEIVER,
                                              "--es", "hub_ca", ca)
                            if rc == 0 and "result=1" in o:
                                ca_sent.add(serial)
                            else:
                                log.warning("Tablet %s: WLAN-CA nicht übernommen (%s)", serial, o.strip()[-120:])
                    # Betriebsart pro Tablet per ADB (der Steuerkanal kann Tablets per USB nicht unterscheiden -
                    # alle kommen über adb reverse von 127.0.0.1); der Launcher übernimmt sie fest
                    if serial not in id_sent:
                        await send_id(serial)
                    if serial not in mode_sent:
                        rc, o = await run(adb, "-s", serial, "shell", "am", "broadcast", "--include-stopped-packages",
                                          "-n", PAIRING_RECEIVER, "--es", "tablet_mode",
                                          device_mode(cfg, serial, bridge.devices))
                        if rc == 0 and "result=1" in o:
                            mode_sent.add(serial)
                    if not companion(serial):
                        rc, o = await run(adb, "-s", serial, "shell", "cmd", "package", "resolve-activity",
                                          "--brief", "-a", "android.intent.action.MAIN",
                                          "-c", "android.intent.category.HOME")
                        lines = o.strip().splitlines()
                        if rc == 0 and lines and not home_is_launcher(lines[-1]):
                            log.warning("Tablet %s: Startbildschirm war %s, setze Launcher", serial, lines[-1].strip())
                            await run(adb, "-s", serial, "shell", "cmd", "package", "set-home-activity", HOME_COMPONENT)
                    # Feste Ausrichtung halten: spacedesk schaltet die automatische Drehung wieder ein
                    rot = device_rotation(cfg, serial, bridge.devices)
                    if rot is not None:
                        _, auto = await run(adb, "-s", serial, "shell", "settings", "get", "system",
                                            "accelerometer_rotation")
                        _, user = await run(adb, "-s", serial, "shell", "settings", "get", "system",
                                            "user_rotation")
                        if auto.strip() != "0" or user.strip() != str(rot):
                            log.info("Tablet %s: Ausrichtung zurückgesetzt (auto=%s, user=%s)",
                                     serial, auto.strip(), user.strip())
                            await run(adb, "-s", serial, "shell", "settings", "put", "system",
                                      "accelerometer_rotation", "0")
                            await run(adb, "-s", serial, "shell", "settings", "put", "system",
                                      "user_rotation", str(rot))
            for serial in ready:
                if loop_t - last_sync.get(serial, -1e9) >= 3600:
                    ok = await sync_time(adb, serial, cfg)
                    # fehlgeschlagen (z. B. Tablet bootet noch): in 30 s erneut, sonst stündlich
                    last_sync[serial] = loop_t if ok else loop_t - 3600 + 30
            for serial in list(last_sync):
                if serial not in ready:
                    del last_sync[serial]
            for serial in ready:
                if health.due(serial):
                    try:
                        await health.check(run, adb, serial)
                    except Exception as e:  # noqa: BLE001 - nur Diagnose, darf nichts anderes stören
                        log.info("Tablet %s: Zustand nicht lesbar (%s)", serial, e.__class__.__name__)
        except Exception as e:  # noqa: BLE001
            log.error("adb: %s", e)
        await asyncio.sleep(3)


def _log_task_end(task):
    if not task.cancelled() and task.exception():
        log.error("Hintergrundaufgabe abgestürzt: %r", task.exception())


_close_handler = None


def install_close_handler(out):
    """Konsolenfenster per X geschlossen / abgemeldet: vorher alle Tasten loslassen."""
    global _close_handler
    import ctypes
    from ctypes import wintypes

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    def handler(event):
        if event in (2, 5, 6):  # CLOSE, LOGOFF, SHUTDOWN
            out.closing = True  # keine neuen Tastendrücke mehr annehmen
            try:
                out.release_all()
            except Exception:  # noqa: BLE001
                pass
        return False  # Standardbehandlung weiterlaufen lassen

    _close_handler = handler  # Referenz halten, sonst räumt der GC den Callback weg
    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)


def setup_logging(log_file):
    handlers = []
    if sys.stderr is not None:            # pythonw (Autostart ohne Fenster) hat keine Konsole
        handlers.append(logging.StreamHandler())
    if log_file:
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(ROOT / log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s.%(msecs)03d %(message)s",
                        datefmt="%H:%M:%S", handlers=handlers, force=True)
    logging.getLogger("websockets").setLevel(logging.WARNING)


async def serve_wlan(bridge):
    """Zweiter Zugang für das Tablet im WLAN: TLS auf allen Schnittstellen (Windows-Firewall: nur privates
    Netz, siehe docs/install.md). /edit und /send bleiben loopback-only, /ws und /ctl verlangen die Kopplung."""
    bridge.wlan_tls = ServerTLS(ROOT / "tls")
    # WLAN: längere Ping-Zeiten (Energiesparen/Funklöcher), kurzer TLS-Handshake gegen hängende Verbindungen
    async with serve(bridge.handler, "0.0.0.0", bridge.wlan_port, ssl=bridge.wlan_tls.ctx,
                     process_request=bridge.http, ping_interval=5, ping_timeout=8, compression=None,
                     ssl_handshake_timeout=10) as server:
        bridge.wlan_server = server
        log.info("WLAN-Zugang: https://%s:%d", ", ".join(bridge.wlan_tls.ips) or "?", bridge.wlan_port)
        await bridge.watch_wlan()


async def main():
    setup_logging("bridge.log")          # sofort, damit auch Fehler beim Lesen der Konfiguration im Log landen
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "config.json"
    if cfg_path == ROOT / "config.json":   # erster Start: Einstellungen aus dem Beispiel
        ensure_from_example(cfg_path, ROOT / "config.example.json")
    cfg = load_json(cfg_path)
    if cfg.get("log_file", "bridge.log") != "bridge.log":
        setup_logging(cfg.get("log_file"))
    bridge = Bridge(cfg)
    bridge.dashboards.cfg_path = cfg_path
    port = int(cfg.get("port", 8765))
    host = cfg.get("host", "127.0.0.1")
    # /ws steuert Maus und Tastatur des PCs vollständig. Ohne Kopplung (docs/install.md, WLAN-Betrieb) nur lokal lauschen.
    if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
        raise SystemExit(f"host={host}: Zugriff aus dem Netz ist erst mit Kopplung erlaubt (docs/install.md, WLAN-Betrieb). "
                         "Bitte host=127.0.0.1 verwenden.")
    install_close_handler(bridge.out)
    stop = asyncio.Event()
    tray = Tray(bridge, asyncio.get_running_loop(), stop) if cfg.get("tray", True) else None
    bridge.on_tiles_changed = tray.refresh if tray else None
    try:
        async with serve(bridge.handler, host, port, process_request=bridge.http,
                         ping_interval=2, ping_timeout=3, compression=None):
            log.info("Bridge läuft: http://%s:%d  (Modus: %s)", host, port, bridge.out.name)
            bridge.editor_url = f"http://localhost:{port}/editor/#k={bridge.editor_token}"
            # Token nur in die Konsole, nicht in die Logdatei
            if sys.stderr is not None:
                print(f"Panel-Editor: {bridge.editor_url}", file=sys.stderr, flush=True)
            log.info("Panel-Editor: über das Taskleisten-Symbol öffnen")
            tasks = [asyncio.create_task(bridge.watch_layout()), asyncio.create_task(bridge.watch_volume()),
                     asyncio.create_task(auto_modes(bridge, cfg)), asyncio.create_task(watch_games(bridge, cfg)),
                     asyncio.create_task(bridge.stats.run())]
            if cfg.get("web", True):
                tasks.append(asyncio.create_task(proxy.serve(int(cfg.get("web_proxy_port", 8766)))))
            if cfg.get("wlan", {}).get("enabled", False):
                tasks.append(asyncio.create_task(serve_wlan(bridge)))
            if cfg.get("tablet_sleep_with_pc", True):
                loop = asyncio.get_running_loop()

                def notify(action):   # aus einem Hilfs-Thread: Befehl an Tablets im WLAN, max. 1 s
                    if action == "sleep":   # auch gerade getrennte WLAN-Tablets beim Verbinden wieder wecken
                        loop.call_soon_threadsafe(bridge.wlan_slept)
                    if not any(not is_loopback(ws.remote_address) for ws in list(bridge.ctl_clients)):
                        return        # kein Tablet im WLAN - nichts zu tun
                    asyncio.run_coroutine_threadsafe(bridge.power_wlan(action), loop).result(1.0)
                # Unter dem Wächter (supervise) schaltet dieser das Tablet per adb - nur ein Prozess, sonst
                # könnten sich Schlaf- und Weckbefehle bei einem abgebrochenen Herunterfahren überholen.
                # Die Bridge meldet dann nur noch die Tablets im WLAN (Steuerkanal).
                supervised = os.environ.get("TABLETDECK_SUPERVISED") == "1"
                watch_session_end(None if supervised else find_adb(cfg), notify,
                                  serials=lambda: list(bridge.usb_serials))
            if cfg.get("spacedesk_silence", True):
                tasks.append(asyncio.create_task(silence_spacedesk()))
            if cfg.get("usb", True):
                tasks.append(asyncio.create_task(adb_watch(cfg, port, bridge)))
            for t in tasks:
                t.add_done_callback(_log_task_end)
            if tray:
                tray.start()
            await stop.wait()   # Beenden über Taskleisten-Symbol (Strg+C beendet asyncio.run direkt)
            for t in tasks:
                t.cancel()
    finally:
        bridge.cancel_macros()
        bridge.drop_pulses(stop=True)   # wartende Impulse verwerfen; out.close() lässt alles Gedrückte los
        bridge.flush_late_releases()
        if tray:
            tray.close()
        bridge.out.close()


if __name__ == "__main__":
    if os.name != "nt":
        sys.exit("Nur Windows")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except SystemExit as e:
        if e.code in (None, 0):
            raise
        log.error("Bridge beendet: %s", e)
        sys.exit(EXIT_CONFIG)          # Host-Guard u. Ä.: Neustart würde nichts ändern
    except OSError as e:
        # Port belegt (Autostart + manueller Start) - unter pythonw sonst unsichtbar
        if getattr(e, "winerror", None) == 10048 or e.errno in (98, 10048):
            log.error("Bridge konnte nicht starten: Port belegt - läuft sie schon (Taskleisten-Symbol)? (%s)", e)
            sys.exit(EXIT_RUNNING)
        if isinstance(e, FileNotFoundError):
            log.error("Bridge konnte nicht starten: %s", e)
            sys.exit(EXIT_CONFIG)
        log.exception("Bridge konnte nicht starten")
        raise
    except ValueError as e:            # z. B. kaputte config.json / layout.json beim Start
        log.error("Bridge konnte nicht starten (Konfiguration): %s", e)
        sys.exit(EXIT_CONFIG)
    except BaseException:
        log.exception("Bridge abgestürzt")
        raise
