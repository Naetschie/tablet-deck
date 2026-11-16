"""Sensor-Helfer starten: python -m bridge.sensors [--list] [--config PFAD]

Ohne Option: Server auf 127.0.0.1:8768 (config.json: "sensors_port"), GET /values mit Token aus
secrets/sensors.key. Läuft auch ohne Adminrechte und liefert dann die Grundwerte.
--list: alle gefundenen Rohsensoren als Tabelle ausgeben und beenden (zum Zuordnen in sensors.json).

Admin-Betrieb (geplante Aufgabe "Tablet Deck Sensors", scripts/install-sensors.ps1): Start aus der Kopie in
%ProgramFiles%\TabletDeck\sensors mit --installed --data <Projektordner>. Der Projektordner ist vom Nutzer
beschreibbar und wird dann nur als Daten gelesen (config.json, sensors.json, secrets/sensors.key): kein
Programmpfad daraus (presentmon_exe wird ignoriert, PresentMon kommt aus --presentmon), das Token wird nicht
angelegt, das Log liegt im Programmverzeichnis.
"""
import argparse
import json
import logging
import signal
import socket
import sys
import threading
import time
from pathlib import Path

from . import is_admin
from .collector import Collector
from .lhm_src import LhmSource
from .mapping import assigned, load_mapping
from .nvml_src import NvmlSource
from .presentmon_src import PresentMonSource
from .psutil_src import PsutilSource
from .server import HOST, load_or_create_token, make_server

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PORT = 8768
log = logging.getLogger("sensors")


def setup_logging(log_file=None):
    handlers = []
    if sys.stderr is not None:            # pythonw (geplante Aufgabe ohne Fenster) hat keine Konsole
        handlers.append(logging.StreamHandler())
    if log_file:
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s.%(msecs)03d %(message)s",
                        datefmt="%H:%M:%S", handlers=handlers, force=True)


def load_config(path):
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError) as e:
        log.warning("Konfiguration %s nicht lesbar (%s) - Standardwerte", path, type(e).__name__)
        return {}


def build(cfg, data=ROOT, presentmon_exe=None):
    """presentmon_exe gesetzt (Admin-Betrieb): fester Pfad, config.json zählt dann nicht."""
    if presentmon_exe is None:
        exe = Path(cfg.get("presentmon_exe") or "tools/presentmon/PresentMon.exe")
        presentmon_exe = exe if exe.is_absolute() else data / exe
    presentmon = PresentMonSource(Path(presentmon_exe))
    adapters = [PsutilSource(), NvmlSource(), LhmSource(), presentmon]
    return Collector(adapters, load_mapping(data / "sensors.json")), presentmon


def read_token(path):
    """Token nur lesen (Admin-Betrieb: nichts in den vom Nutzer beschreibbaren Ordner schreiben). Nie loggen."""
    try:
        s = path.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return None
    return s if len(s) >= 32 else None


def list_sensors(collector, out=None):
    """Tabelle aller Rohsensoren. Zwei Abtastungen, weil Raten (Netz, CPU-Last) einen Bezugspunkt brauchen."""
    out = out or sys.stdout
    try:
        collector.sample()
        time.sleep(1)
        raws = collector.sample()
        snap = collector.snapshot()
    finally:
        collector.close()
    ids = assigned(collector.mapping, raws)
    rows = [("Quelle", "Typ", "Name", "Wert", "Einheit", "ID", "Pfad")]     # Pfad zuletzt: kann sehr lang sein
    for r in raws:
        rows.append((r.source, r.kind, r.name, f"{r.value:.3f}".rstrip("0").rstrip("."), r.unit,
                     ", ".join(ids.get((r.source, r.path), [])), r.path))
    width = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)] + [4]
    for n, row in enumerate(rows):
        print("  ".join(c.ljust(w) for c, w in zip(row, width)).rstrip(), file=out)
        if n == 0:
            print("  ".join("-" * w for w in width), file=out)
    print(file=out)
    print("Quellen:", ", ".join(f"{k}: {v}" for k, v in snap["sources"].items()), file=out)
    have = {v["id"] for v in snap["values"]}
    missing = [i for i in collector.mapping if i not in have]
    if missing:
        print("IDs ohne Wert:", ", ".join(missing), file=out)
    if not is_admin():
        print("Hinweis: ohne Adminrechte fehlen Kerntakte, CPU-Temperaturen und die Mainboard-Sensoren.", file=out)


def get_port(cfg):
    port = cfg.get("sensors_port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        log.error("sensors_port ungültig - nehme %d", DEFAULT_PORT)
        return DEFAULT_PORT
    return port


def _port_in_use(port):
    try:
        with socket.create_connection((HOST, port), timeout=0.5):
            return True
    except OSError:
        return False


def main(argv=None):
    """Jeder Startfehler landet im Log (pythonw hat kein stderr, sonst bliebe er unsichtbar)."""
    try:
        return _main(argv)
    except Exception:  # noqa: BLE001
        if not logging.getLogger().handlers:
            setup_logging(ROOT / "sensors.log")
        log.exception("Sensor-Helfer: Start fehlgeschlagen")
        return 1


def _main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m bridge.sensors", description="Sensor-Helfer für Tablet Deck")
    ap.add_argument("--list", action="store_true", help="alle Rohsensoren auflisten und beenden")
    ap.add_argument("--config", type=Path, help="Pfad zur config.json (Standard: <data>/config.json)")
    ap.add_argument("--data", type=Path, default=ROOT,
                    help="Projektordner mit config.json, sensors.json und secrets/sensors.key")
    ap.add_argument("--installed", action="store_true",
                    help="Admin-Betrieb aus dem Programmverzeichnis (braucht --presentmon und --log)")
    ap.add_argument("--presentmon", type=Path, help="PresentMon.exe (ersetzt presentmon_exe aus config.json)")
    ap.add_argument("--log", type=Path, help="Logdatei (Standard: <data>/sensors.log)")
    args = ap.parse_args(argv)
    data = args.data.resolve()
    if args.config is None:
        args.config = data / "config.json"
    if args.installed and (args.presentmon is None or args.log is None):
        ap.error("--installed braucht --presentmon und --log")

    if args.list:
        for stream in (sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")      # „°C“ auch in alten Konsolen
        setup_logging()
        cfg = load_config(args.config)
        if _port_in_use(get_port(cfg)):
            print("Helfer läuft – vorher beenden (er belegt PresentMon und die Sensoren).")
            return 1
        collector, _ = build(cfg, data, args.presentmon)
        list_sensors(collector)
        return 0

    setup_logging(args.log or data / "sensors.log")
    cfg = load_config(args.config)
    port = get_port(cfg)
    key = data / "secrets" / "sensors.key"
    if args.installed:
        token = read_token(key)
        if token is None:
            log.error("Kein Token in %s - install.ps1 legt es an (oder einmal den Hub starten)", key)
            return 1
    else:
        token = load_or_create_token(key)
    collector, presentmon = build(cfg, data, args.presentmon)
    try:
        server = make_server(collector, token, port, presentmon)
    except OSError as e:
        log.error("Port %d nicht frei (%s) - läuft der Sensor-Helfer schon?", port, e)
        return 1

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    for sig in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, sig):
            signal.signal(getattr(signal, sig), stop)
    collector.start()
    log.info("Sensor-Helfer: http://%s:%d/values (%s%s)", HOST, port, "mit Admin" if is_admin() else "ohne Admin",
             ", installiert" if args.installed else "")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        collector.stop()            # schließt die Quellen, beendet PresentMon
        log.info("Sensor-Helfer beendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
