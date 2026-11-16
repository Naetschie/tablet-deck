"""Panel-Tasten aus der Star-Citizen-Belegung ableiten.

Jede Taste in einem Panel-Profil (Standard profiles/star-citizen/main.json) kann ein Feld "sc" mit dem Namen der Spielaktion haben (z. B.
"v_target_cycle_hostile_fwd"). Dieses Skript ermittelt die *tatsächliche* Tastaturbelegung
(Standardprofil des Spiels + eigene Änderungen aus actionmaps.xml) und trägt sie als "key" ein.
Aktionen ohne Tastaturbelegung werden gemeldet, mit Vorschlag einer freien Kombination.

Aufruf:
  python scripts/sc_bindings.py                 # Bericht, nichts ändern
  python scripts/sc_bindings.py --write         # Panel-Profil aktualisieren
Mitgelieferte Panels (panels/) werden hier NICHT beschrieben: der Hub setzt deren Tasten beim Laden selbst aus
der echten Belegung (bridge/bindings apply_sc); --layout auf panels/… schreibt das Skript nicht (Abbruch bei --write).
Standardprofil: tools/sc/Data/Libs/Config/defaultProfile.plain.xml (StarBreaker: p4k extract + cryxml convert)
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bridge.layout import save_layout  # noqa: E402

DEFAULT_PROFILE = ROOT / "tools/sc/Data/Libs/Config/defaultProfile.plain.xml"
from bridge.bindings.cryengine import (  # noqa: E402  (gemeinsam mit dem Panel-Generator)
    FREE_POOL, HOLD_MODES, MULTI_MODES, effective_bindings, find_user_actionmaps, key_to_sc, sc_to_key)


def apply_to_game(user_path, default_path, layout_path, eff, free):
    """Wie ein GameGlass-Belegungsprofil: fehlende Tastaturbelegungen für Panel-Aktionen im Spielprofil
    anlegen. Nur Aktionen ganz ohne Tastaturbelegung; bestehende Belegungen (auch Joystick/X-56 und
    eigene Doppeltipp-Belegungen) bleiben unverändert."""
    import datetime
    import shutil
    import subprocess
    from collections import defaultdict

    tl = subprocess.run(["tasklist", "/fi", "imagename eq StarCitizen.exe", "/fo", "csv", "/nh"],
                        capture_output=True, encoding="oem", errors="replace",
                        creationflags=0x08000000).stdout or ""
    if "starcitizen.exe" in tl.lower():
        sys.exit("Star Citizen läuft - bitte erst beenden (das Spiel überschreibt actionmaps.xml beim Beenden).")

    layout = json.loads(Path(layout_path).read_text(encoding="utf-8"))
    wanted = []
    for page in layout["pages"]:
        for b in page["buttons"]:
            act = b.get("sc")
            if act and act in eff and not eff[act][0] and act not in [w[0] for w in wanted]:
                wanted.append((act, b["label"]))
    if not wanted:
        print("Alle Panel-Aktionen haben bereits eine Tastaturbelegung.")
        return
    if len(wanted) > len(free):
        sys.exit(f"Nicht genug freie Kombinationen ({len(free)}) für {len(wanted)} Aktionen.")

    maps = defaultdict(list)   # Aktion -> actionmaps, in denen sie im Standardprofil vorkommt
    for am in ET.parse(default_path).getroot().iter("actionmap"):
        for a in am.iter("action"):
            maps[a.get("name")].append(am.get("name"))

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = user_path.with_name(f"actionmaps.backup-{stamp}.xml")
    shutil.copy2(user_path, backup)
    tree = ET.parse(user_path)
    prof = tree.getroot().find("ActionProfiles")
    if prof is None:
        sys.exit("actionmaps.xml hat unerwarteten Aufbau (kein ActionProfiles) - nichts geändert.")
    print(f"Sicherung: {backup}")
    for (act, label), key in zip(wanted, free):
        for mname in maps[act]:
            am = prof.find(f"actionmap[@name='{mname}']")
            if am is None:
                am = ET.SubElement(prof, "actionmap", name=mname)
            a = am.find(f"action[@name='{act}']")
            if a is None:
                a = ET.SubElement(am, "action", name=act)
            for rb in a.findall("rebind"):
                if rb.get("input", "").strip() == "kb1_":
                    a.remove(rb)       # nur leere (bewusst entfernte) Tastatur-Einträge
            if any(rb.get("input", "").startswith("kb1_") for rb in a.findall("rebind")):
                continue               # in dieser Map schon eine echte Tastaturbelegung - nicht anfassen
            ET.SubElement(a, "rebind", input="kb1_" + key_to_sc(key))
        print(f"  {act:48} {key:22} ({label})")
    ET.indent(tree, space=" ")
    tree.write(user_path, encoding="utf-8")
    print(f"{len(wanted)} Belegungen in {user_path} eingetragen. Wirksam beim nächsten Spielstart.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", default=str(ROOT / "profiles" / "star-citizen" / "main.json"))
    ap.add_argument("--default", default=str(DEFAULT_PROFILE))
    ap.add_argument("--user", default=None,
                    help="actionmaps.xml (Standard: über die Spielebibliothek gefunden)")
    ap.add_argument("--write", action="store_true", help="Panel-Profil aktualisieren")
    ap.add_argument("--apply-game", action="store_true",
                    help="unbelegte Panel-Aktionen mit freien Kombinationen in actionmaps.xml eintragen "
                         "(Spiel muss geschlossen sein; Sicherung wird angelegt)")
    args = ap.parse_args()
    if args.user is None:
        args.user = find_user_actionmaps()
        if args.user is None and args.apply_game:
            sys.exit("actionmaps.xml nicht gefunden - Pfad mit --user angeben")

    eff = effective_bindings(args.default, args.user)
    used = {sc_to_key(v[0]) for v in eff.values() if v[0] and sc_to_key(v[0])}
    free = [k for k in FREE_POOL if k not in used]

    if args.apply_game:
        apply_to_game(Path(args.user), Path(args.default), args.layout, eff, free)
        eff = effective_bindings(args.default, args.user)   # neu einlesen, dann Layout wie gewohnt

    if args.write and Path(args.layout).resolve().is_relative_to((ROOT / "panels").resolve()):
        sys.exit("panels/ ist mitgeliefert und schreibgeschützt: der Hub setzt die Tasten dort zur Laufzeit aus der "
                 "Belegung. Für eigene Anpassungen im Editor eine Kopie anlegen (profiles/) und diese beschreiben.")
    layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    missing, changed = [], 0
    print(f"{'Taste':22} {'SC-Aktion':48} Belegung")
    for page in layout["pages"]:
        for b in page["buttons"]:
            act = b.get("sc")
            if not act:
                continue
            if act not in eff:
                print(f"{b['id']:22} {act:48} !! Aktion gibt es im Spiel nicht")
                continue
            sc, mode, multi = eff[act]
            key = sc_to_key(sc) if sc else None
            if key and (multi not in ("", "1") or mode in MULTI_MODES):
                print(f"{b['id']:22} {act:48} !! {key} nur per Doppeltipp - nicht abbildbar, bitte anders binden")
                missing.append((b, act))
                continue
            if key:
                if b.get("key") != key:
                    b["key"] = key
                    changed += 1
                if mode in HOLD_MODES and not b.get("hold"):
                    b["hold"] = True   # Spiel erwartet gehaltene Taste (sonst kurzer Impuls)
                    changed += 1
                print(f"{b['id']:22} {act:48} {key}{'  (halten)' if b.get('hold') else ''}")
            else:
                missing.append((b, act))
                hint = f", Panel nutzt weiter {b['key']}" if b.get("key") else ""
                print(f"{b['id']:22} {act:48} -- keine Tastatur-Belegung ({sc or 'leer'}{hint})")

    # Doppelbelegungen: dieselbe Kombination für mehrere Spielaktionen (Panel-Taste löst ggf. beides aus)
    by_key = {}
    for act, (sc, _mode, _multi) in eff.items():
        k = sc_to_key(sc) if sc else None
        if k:
            by_key.setdefault(k, set()).add(act)
    for page in layout["pages"]:
        for b in page["buttons"]:
            # nur Fahrzeug-Aktionen (v_*): andere Kontexte (zu Fuß, Menüs) trennt das Spiel selbst
            others = {a for a in by_key.get(b.get("key"), set()) - {b.get("sc")} if a.startswith("v_")}
            if b.get("sc") and others:
                print(f"Hinweis: {b['id']} ({b.get('key')}) ist im Spiel auch: {', '.join(sorted(others)[:4])}")

    if missing:
        print(f"\n{len(missing)} Aktionen ohne Tastatur-Belegung. Vorschlag (freie Kombinationen) - im Spiel unter "
              "Optionen > Tastenbelegung binden, danach dieses Skript erneut mit --write:")
        for (b, act), k in zip(missing, free):
            print(f"  {act:48} {k:16} (SC: kb1_{key_to_sc(k)})  -> Panel '{b['label']}'")
    if args.write:
        save_layout(Path(args.layout), layout)   # prüft und schreibt atomar
        print(f"\nPanel-Profil aktualisiert ({changed} Änderungen).")


if __name__ == "__main__":
    main()
