"""Erster Start: PC-gebundene Dateien (config.json, launcher.json) aus den eingecheckten Beispielen anlegen.

Vorhandene Dateien werden nie überschrieben; geschrieben wird atomar (tmp + os.replace).
Aufruf aus install.ps1:  python -m bridge.firstrun [--no-spacedesk]
  --no-spacedesk: launcher.json ohne die spacedesk-Kachel (Paket ph.spacedesk.beta)
"""
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPACEDESK_PKG = "ph.spacedesk.beta"
FILES = (("config.json", "config.example.json"), ("launcher.json", "launcher.example.json"))
log = logging.getLogger("bridge")


def ensure_from_example(path, example, drop_spacedesk=False):
    """path aus example anlegen, wenn path fehlt. True = angelegt. Fehlt auch das Beispiel: False."""
    path, example = Path(path), Path(example)
    if path.exists() or not example.is_file():
        return False
    text = example.read_text(encoding="utf-8")
    if drop_spacedesk:
        data = json.loads(text)
        data["tiles"] = [t for t in data.get("tiles", []) if t.get("pkg") != SPACEDESK_PKG]
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    # Erst vollständig in eine Temp-Datei, dann per Hardlink an den Zielnamen: atomar (nie halb geschrieben) und
    # schlägt fehl, wenn path inzwischen existiert (nie überschreiben). Ohne Hardlinks (FAT, manche
    # Netzlaufwerke) exklusiv mit "x" anlegen - dort nicht atomar, aber ebenfalls ohne Überschreiben.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    try:
        os.link(tmp, path)
    except FileExistsError:
        return False
    except OSError:
        try:
            with open(path, "x", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except FileExistsError:
            return False
    finally:
        tmp.unlink(missing_ok=True)
    log.info("%s aus %s angelegt", path.name, example.name)
    return True


def ensure_all(root=ROOT, drop_spacedesk=False):
    """Beide Dateien anlegen; Liste der neu angelegten Namen."""
    made = []
    for name, ex in FILES:
        if ensure_from_example(Path(root) / name, Path(root) / ex,
                               drop_spacedesk=drop_spacedesk and name == "launcher.json"):
            made.append(name)
    return made


if __name__ == "__main__":
    for n in ensure_all(drop_spacedesk="--no-spacedesk" in sys.argv[1:]):
        print(f"{n} angelegt")
