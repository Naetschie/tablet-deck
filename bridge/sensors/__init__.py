"""Sensor-Helfer („sensord“): sammelt PC-Messwerte aus freien Quellen und stellt sie dem Hub lokal bereit.

Start: python -m bridge.sensors          (Server auf 127.0.0.1, siehe docs/sensors.md)
       python -m bridge.sensors --list   (alle Rohsensoren zum Zuordnen auflisten)

Jede Quelle ist ein Adapter mit start/read/close. read() liefert Rohsensoren (Raw); mapping.py ordnet sie
den stabilen IDs zu (cpu.load, gpu.temp, fan.sys1, …).
"""
import ctypes
from dataclasses import dataclass


@dataclass
class Raw:
    """Ein Rohsensor einer Quelle. path ist innerhalb der Quelle eindeutig."""
    source: str
    path: str
    name: str
    value: float
    unit: str = ""
    kind: str = ""      # Sensortyp, z. B. bei LHM „Temperature“, „Fan“, „Voltage“


class Unavailable(Exception):
    """Quelle dauerhaft nicht nutzbar (Paket/Programm fehlt). Der Text landet in „sources“."""


class Adapter:
    """Gemeinsame Schnittstelle der Quellen. Fehler fängt der Collector ab, nicht der Adapter."""
    name = "?"
    status = "ok"       # Text für „sources“, solange die Quelle läuft (z. B. „kein Admin“ bei Teilwerten)

    def start(self):
        pass

    def read(self):
        return []

    def close(self):
        pass


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - z. B. kein Windows
        return False
