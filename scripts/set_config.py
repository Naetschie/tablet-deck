"""config.json für install.ps1 anpassen:  python scripts/set_config.py <config.json> use|skip|companion|home

skip: spacedesk_usb und spacedesk_silence aus (ohne Zweitbildschirm).
use:  spacedesk_usb wieder an; spacedesk_silence bleibt, wie der Benutzer es gesetzt hat.
companion / home: tablet_mode setzen (Begleit-Modus ohne Root bzw. Startbildschirm-Modus).
Ohne diese Modi bleibt tablet_mode unverändert.
Schreibt nur bei einer Änderung, atomar (tmp + os.replace).
"""
import json
import os
import sys


def main():
    path, mode = sys.argv[1], sys.argv[2]
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    new = dict(cfg)
    if mode == "skip":
        new["spacedesk_usb"] = False
        new["spacedesk_silence"] = False
    elif mode == "use":
        new["spacedesk_usb"] = True
    elif mode in ("companion", "home"):
        new["tablet_mode"] = mode
    else:
        sys.exit("Modus: use|skip|companion|home")
    if new == cfg:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
