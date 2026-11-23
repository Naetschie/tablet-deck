"""config.json für install.ps1 anpassen:  python scripts/set_config.py <config.json> use|skip|companion|home
                                          python scripts/set_config.py <config.json> device <serial> companion|home
                                          python scripts/set_config.py <config.json> device <serial> light on|off

skip: spacedesk_usb und spacedesk_silence aus (ohne Zweitbildschirm).
use:  spacedesk_usb wieder an; spacedesk_silence bleibt, wie der Benutzer es gesetzt hat.
companion / home: tablet_mode setzen (Begleit-Modus ohne Root bzw. Startbildschirm-Modus).
Ohne diese Modi bleibt tablet_mode unverändert.
device <serial> companion|home: Betriebsart nur dieses Geräts (tablet_modes[serial]); andere bleiben, wie sie sind.
device <serial> light on|off: Light-Modus nur dieses Geräts (tablet_lights[serial]). Steht das Gerät schon in
    devices.json daneben (hat Vorrang), wird es dort ebenso gesetzt - nur bei beendeter Bridge aufrufen.
Schreibt nur bei einer Änderung, atomar (tmp + os.replace).
"""
import json
import os
import re
import sys


def set_device_light(dev_path, serial, on):
    """devices.json: light beim bekannten Gerät setzen; fehlt die Datei oder das Gerät, nichts tun."""
    try:
        with open(dev_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as e:
        sys.exit(f"devices.json nicht lesbar ({e}) - Light-Modus nicht gesetzt")
    devs = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(devs, dict) or not isinstance(devs.get(serial), dict) or devs[serial].get("light") is on:
        return
    devs[serial]["light"] = on
    tmp = dev_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, dev_path)


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
        if light:
            set_device_light(os.path.join(os.path.dirname(os.path.abspath(path)), "devices.json"), serial,
                             sys.argv[5] == "on")
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
