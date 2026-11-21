# Star-Citizen-Belegung für das Panel

Für ein Handy hochkant gibt es zusätzlich **Handy (hochkant)** (`panels/star-citizen/handy.json`): Seite
„Schilde“ mit großem Schildfeld, Energieverteilung und Abwehr, Seite „Komfort“ mit Systemen, Schiff und Pilot.
Als Start-Panel eines Geräts: `devices.json` → `"panel": "star-citizen/std--handy"` (siehe docs/install.md).

Mitgeliefert ist das Panel **Cockpit** (`panels/star-citizen/cockpit.json`) mit vier Bereichen: Flug & Kampf,
Start & Landung, Industrie, Zu Fuß. Es enthält bewusst nur, was nicht ohnehin auf einem HOTAS liegt (Energie,
Schilde, MFD, Systeme, Abwehr). Die Panel-Tasten verweisen über das Feld `sc` auf die Spielaktion. Die
Tastenkombination (`key`) wird **aus dem Spiel abgeleitet**:

```
python scripts/sc_bindings.py                                   # Bericht (Standard: Cockpit)
python scripts/sc_bindings.py --layout profiles/star-citizen/x.json --write   # eigenes Panel aktualisieren
```

Aktionen, die das Spiel erst nach einer Haltezeit auslöst (`delayed_press`, z. B. Autolandung,
Selbstzerstörung), hält der Hub so lange wie im Standardprofil angegeben (`pressTriggerThreshold` + 100 ms) -
ein Tipp am Tablet genügt.

**Mitgelieferte Panels** (`panels/star-citizen/*.json`) werden vom Skript nicht beschrieben: Der Hub setzt
`key` (und `hold`) von Tasten mit `sc` beim Laden aus derselben Quelle (Standardprofil + eigene
`actionmaps.xml`) und lädt neu, wenn sich eine der Dateien ändert. Aktionen ohne Tastaturbelegung oder unbekannte
Aktionen behalten, was in der Panel-Datei steht. Das Skript bleibt für eigene Panels in `profiles/`.

Quellen:
- Standardbelegung: `Data.p4k → Data/Libs/Config/defaultProfile.xml`, mit StarBreaker extrahiert und
  umgewandelt. Die Datei stammt aus den Spieldateien und liegt deshalb nicht im Repo - jeder erzeugt sie
  aus der eigenen Installation (Pfad anpassen):
  ```
  set SC_DATA_P4K=<Star-Citizen-Ordner>\LIVE\Data.p4k
  starbreaker p4k extract -o tools\sc --filter "Data/Libs/Config/defaultProfile.xml"
  starbreaker cryxml convert tools\sc\Data\Libs\Config\defaultProfile.xml tools\sc\Data\Libs\Config\defaultProfile.plain.xml
  ```
  Nach einem Spiel-Patch erneut ausführen (Belegungen ändern sich).
- Eigene Änderungen: `<Star-Citizen-Ordner>\LIVE\user\client\0\Profiles\default\actionmaps.xml`
  (nur `kb1_…`-Einträge zählen). Der Ordner wird über die Spielebibliothek gefunden; sonst `--user <Pfad>`.

## Impuls oder Halten
Viele Aktionen sind in SC „tap“: Sie lösen nur bei einem kurzen Druck aus (unter etwa 0,25 s). Panel-Tasten
senden deshalb standardmäßig einen **Impuls von 80 ms**, egal wie lange der Finger liegt. Aktionen, die
das Spiel gehalten erwartet (`activationMode` hold/smart_toggle u. a., z. B. Ping), bekommen vom Skript
`"hold": true`. Dann ist die Taste so lange gedrückt wie der Finger. Hupe ist von Hand auf `hold` gesetzt.
Belegungen per Doppeltipp (`multiTap="2"` bzw. `double_tap`) kann das Panel nicht nachbilden. Das Skript
meldet sie, solche Aktionen bitte mit einer eigenen Kombination binden.

## Bekannte Doppelbelegungen (Kontext beachten)
- `SPACE` (Hupe) ist im Raumschiff „nach oben schieben“. Die Taste ist nur im Bodenfahrzeug sinnvoll.
- `LALT+1..3` (Mining-Module) pinnt im Kampf-Kontext auch Ziele (`v_target_toggle_pin_index_*`).
- `F11` (Kontakte) schaltet im Fahrzeug zusätzlich den Cursor-Modus.
- `]` (Ablehnen) gehalten = Benachrichtigung ignorieren (durch den Impuls ausgeschlossen).
- Ziffern `4`–`7` (Zielzyklen) im Spiel prüfen: Sie sind zugleich `*_reset` derselben Zyklen.

## Wichtig: Numpad ist nicht mehr Schilde
In SC 4.x haben die Schild-Aktionen (`v_shield_raise_level_*`, `v_shield_reset_level`) **keine**
Standard-Tastaturbelegung mehr. Numpad 1–6 sind jetzt Emotes (`emote_cs_*`). Die frühere Annahme
Eine frühere Annahme „Numpad 8/2/4/6/7/1/5 = Schilde“ gilt nicht mehr. Die Schilde liegen in deinem
Profil auf dem X-56-Throttle (`js2_button20–23`, `js2_button3`).

## Fehlende Belegungen im Spiel anlegen (wie ein GameGlass-Belegungsprofil)
```
python scripts/sc_bindings.py --apply-game --write
```
Trägt für Panel-Aktionen **ohne** Tastaturbelegung freie Kombinationen (`RCTRL+Numpad`, `RCTRL+F…`,
danach `RCTRL+RSHIFT+…`) **zusätzlich** in `actionmaps.xml` ein. Bestehende Belegungen bleiben unverändert,
auch die des X-56 und eigene Doppeltipp-Belegungen. Vorher wird `actionmaps.backup-<zeit>.xml` angelegt.
Das Spiel muss geschlossen sein, weil es die Datei beim Beenden überschreibt. Wirksam beim nächsten Spielstart.

Stand 2026-11-12: angewendet, 20 Belegungen eingetragen (Schilde `RCTRL+NUMPAD1–7`, Quantum-/Raketen-Modus
`RCTRL+NUMPAD8/9`, MFD-Ansichten `RCTRL+NUMPAD0`, `RCTRL+F1–F7`, Reparieren `RCTRL+F8`, Gimbal sperren
`RCTRL+F9`, Vorhalt `RCTRL+F10`). Geprüft: 179 → 199 Einträge, keiner entfernt, Joystick unverändert.
Alle 60 Panel-Tasten sind damit belegt.

Rückgängig: Sicherung zurückkopieren (bei geschlossenem Spiel) oder die Einträge im Spiel löschen.
