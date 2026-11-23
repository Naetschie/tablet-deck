"""config.json für install.ps1 anpassen:  python scripts/set_config.py <config.json> use|skip|companion|home
                                          python scripts/set_config.py <config.json> device <serial> companion|home
                                          python scripts/set_config.py <config.json> device <serial> light on|off

skip: spacedesk_usb und spacedesk_silence aus (ohne Zweitbildschirm).
use:  spacedesk_usb wieder an; spacedesk_silence bleibt, wie der Benutzer es gesetzt hat.
companion / home: tablet_mode setzen (Begleit-Modus ohne Root bzw. Startbildschirm-Modus).
Ohne diese Modi bleibt tablet_mode unverändert.
device <serial> companion|home: Betriebsart nur dieses Geräts (tablet_modes[serial]); andere bleiben, wie sie sind.
device <serial> light on|off: Light-Modus nur dieses Geräts (tablet_lights[serial]; devices.json hat Vorrang).
Schreibt nur bei einer Änderung, atomar (tmp + os.replace).
"""
import json
import os
import re
import sys


def main():
    path, mode = sys.argv[1], sys.argv[2]
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    new = dict(cfg)
    if mode == "device":
        light = len(sys.argv) == 6 and sys.argv[4] == "light" and sys.argv[5] in ("on", "off")
        if not light and (len(sys.argv) != 5 or sys.argv[4] not in ("companion", "home")):
            sys.exit("Aufruf: device <serial> companion|home  bzw.  device <serial> light on|off")
        serial = sys.argv[3]
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", serial):
            sys.exit(f"ungültige Seriennummer: {serial!r}")
        key = "tablet_lights" if light else "tablet_modes"
        vals = dict(cfg.get(key) or {}) if isinstance(cfg.get(key), dict) else {}
        vals[serial] = sys.argv[5] == "on" if light else sys.argv[4]
        new[key] = vals
    elif mode == "skip":
        new["spacedesk_usb"] = False
        new["spacedesk_silence"] = False
    elif mode == "use":
        new["spacedesk_usb"] = True
    elif mode in ("companion", "home"):
        new["tablet_mode"] = mode
    else:
        sys.exit("Modus: use|skip|companion|home|device <serial> companion|home")
    if new == cfg:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
