# Installation

Zwei Wege, je nach Tablet:

- **Begleit-Modus** (Schnellstart): jedes Android-Tablet, ohne Root. Die Launcher-App läuft als normale App.
- **Startbildschirm-Modus** (optional): gerootetes Tablet (Lenovo TB-X505F mit Magisk), die App ersetzt den
  Android-Startbildschirm. Siehe [Tablet als Startbildschirm / Root](#tablet-als-startbildschirm--root-optional).

## Schnellstart
Voraussetzungen: Windows 10/11, das Tablet per USB am PC, am Tablet in den Entwickleroptionen
**USB-Debugging** an (beim ersten Anstecken den Dialog „USB-Debugging zulassen“ bestätigen). Python ab 3.11
installiert `install.ps1` nicht selbst: Fehlt es, `winget install -e --id Python.Python.3.13`, neues Terminal
öffnen und das Skript erneut starten.

Im Projektordner (bzw. im entpackten Zip, siehe [Weitergabe als Zip](#weitergabe-als-zip)):

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Companion
```

Ohne Zweitbildschirm per spacedesk zusätzlich `-SkipSpacedesk`. Das Skript lässt sich beliebig oft ausführen;
was schon eingerichtet ist, überspringt es. `.\install.ps1 -Check` ändert nichts und listet auf, was fehlt.

Beim ersten Mal legt das Skript (bzw. der erste Start der Bridge) `config.json` und `launcher.json` aus
`config.example.json` und `launcher.example.json` an. Diese beiden Dateien gehören zu deinem PC und stehen nicht
im Git; vorhandene Dateien werden nie überschrieben. Mit `-SkipSpacedesk` fehlt in `launcher.json` die
spacedesk-Kachel. Das WLAN-Zertifikat schickt der Hub bei jedem Anstecken per USB ans Tablet (siehe „WLAN-Betrieb“).

Danach: Taskleisten-Symbol am PC, die App „Tablet Deck“ am Tablet. Weiter mit
[Begleit-Modus](#begleit-modus-ohne-root) (was anders ist als im Startbildschirm-Modus), WLAN ohne Kabel
([WLAN-Betrieb](#wlan-betrieb-ohne-kabel)) und den [Einstellungen](#einstellungen-configjson).

## Schalter von `install.ps1`
| Schalter | Wirkung |
|---|---|
| `-SkipTablet` | nur den PC einrichten |
| `-SkipSpacedesk` | ohne Zweitbildschirm: kein Treiber, kein MTP-Umschalten, kein Dialog-Wächter |
| `-SkipAutostart` | Bridge nur jetzt starten, keine geplante Aufgabe |
| `-SkipSensors` | ohne Sensor-Helfer: keine UAC-Abfrage dafür, PC-Werte zeigen nur die Grundwerte (CPU-Last, RAM, Netz, NVIDIA-GPU) |
| `-AllowLocalChanges` | Sensor-Helfer auch mit nicht eingecheckten Änderungen an seinen Dateien einrichten |
| `-Check` | nichts ändern, nur prüfen und auflisten, was fehlt (Exit-Code 1, wenn etwas offen ist) |
| `-Companion` | Begleit-Modus ohne Root: kein Startbildschirm, `tablet_mode` = `companion` (siehe unten) |
| `-Modules` | zusätzlich die Magisk-Module `chargectl` (Akku 45–55 %) und `hardening`, danach Tablet-Neustart |

## Was das Skript macht

**PC**
1. Python ab 3.11 suchen und die Pakete aus `requirements.txt` installieren (`pip --user`).
   Fehlt Python: `winget install -e --id Python.Python.3.13`, neues Terminal öffnen, Skript erneut starten.
2. adb (Android platform-tools) nach `tools\platform-tools` laden, falls es dort fehlt. Die Google-Signatur
   von `adb.exe` wird geprüft.
3. spacedesk-Treiber per `winget` installieren und „USB Cable Android“ einschalten. Windows fragt dabei
   nach Administratorrechten.
4. Autostart einrichten: geplante Aufgabe „Tablet Deck Bridge“ beim Anmelden, mit Wächter, der nach einem
   Absturz neu startet. Danach die Bridge starten. Sie legt beim ersten Start `secret.key` an (Kopplung).
5. Sensor-Helfer für die PC-Werte (ohne `-SkipSensors`, Einzelheiten unten):
   - Token `secrets\sensors.key` anlegen (ohne Adminrechte)
   - PawnIO-Treiber per `winget install -e --id namazso.PawnIO`, falls er fehlt (UAC-Abfrage)
   - `scripts\install-sensors.ps1` mit Administratorrechten (UAC-Abfrage): Kopie nach
     `%ProgramFiles%\TabletDeck\sensors`, Pakete, PresentMon, geplante Aufgabe „Tablet Deck Sensors“
   - Läuft der Helfer schon mit aktueller Kopie, entfällt die Abfrage. Nach einem Update von `bridge\sensors`
     meldet `install.ps1 -Check` „veraltet“ – dann `install.ps1` erneut ausführen.

**Tablet** (nur wenn es per USB verbunden und USB-Debugging erlaubt ist)
6. Launcher-App bauen, falls JDK und Android-SDK in `tools\` liegen, sonst eine vorhandene
   `android\build\tablet-deck.apk` nehmen. Danach installieren, als Startbildschirm setzen, Overlay-Recht
   geben, Sperrbildschirm aus, Querformat fest, mit dem PC koppeln (`tablet\setup-launcher.ps1`).
7. Mit `-Modules`: Magisk-Module installieren.
8. Smoke-Test gegen die laufende Bridge.

## Sensor-Helfer (PC-Werte mit Adminrechten)
Kerntakte, CPU-Temperaturen und -Leistung, Mainboard-Lüfter und -Spannungen (LibreHardwareMonitor) sowie FPS
und Frametime (PresentMon) gibt es nur mit Adminrechten. Der Hub selbst bleibt ohne; ein eigener Helfer läuft
als geplante Aufgabe „Tablet Deck Sensors“ mit höchsten Rechten. Damit kein normaler Prozess in deiner
Sitzung über ihn Adminrechte bekommt, startet er nichts, was ein solcher Prozess ändern kann:

| Teil | Ort | Warum |
|---|---|---|
| Code (`bridge\sensors`, `run.py`) | `%ProgramFiles%\TabletDeck\sensors\app`, `run.py` | nur Admin beschreibbar; aus dem Projektordner kopiert |
| Pakete (psutil, nvidia-ml-py, HardwareMonitor, pythonnet …) | `…\sensors\lib` | `pip --isolated --require-hashes --no-deps`, nur von pypi.org: feste Versionen mit SHA-256 (`bridge\sensors\requirements.txt`), nur Wheels; ohne pip-Cache, pip-Konfiguration und `PIP_*`-Variablen des Nutzers; entpackt in `…\sensors\tmp` statt im `%TEMP%` des Nutzers |
| PresentMon 2.6.0 | `…\sensors\PresentMon.exe` | aus dem GitHub-Release, SHA-256 und Intel-Signatur geprüft (Download ebenfalls in `…\sensors\tmp`); `presentmon_exe` in `config.json` gilt hier nicht |
| Python | dein Python (z. B. `C:\Python313`) | wird geprüft: alle Dateien, Besitzer und übergeordnete Ordner nur für Admins änderbar, keine venv, sonst Abbruch; Start mit `-I` (ohne Nutzer-site-packages und `PYTHON*`-Variablen) |
| Umgebung | `run.py` | feste Liste statt der geerbten Nutzer-Umgebung (`HKCU\Environment`): kein `COR_PROFILER`/`DOTNET_*` für .NET, `PATH` nur System32 und Python, `TEMP` im Programmverzeichnis |
| Daten | Projektordner | nur gelesen: `config.json`, `sensors.json`, `secrets\sensors.key` (Token wird nicht angelegt) |
| Log | `…\sensors\logs\sensors.log`, Einrichtung: `install.log` | |

Vor der UAC-Abfrage zeigt `install.ps1` den Stand (letzter Commit) der Dateien, die kopiert werden, und bricht
bei nicht eingecheckten Änderungen an `bridge\sensors`, `scripts\install-sensors.ps1` oder
`scripts\sensors-run.py` ab (bewusst trotzdem: `-AllowLocalChanges`) - was dort steht, läuft danach mit
Adminrechten. Das schützt vor versehentlichen Änderungen, nicht vor Schadsoftware in deiner Sitzung: Die
Skripte liegen im Projektordner, den jeder deiner Prozesse ändern kann (auch `install.ps1` selbst). Die
UAC-Abfrage beim Einrichten ist deshalb die eigentliche Grenze - nur bestätigen, wenn du `install.ps1` gerade
selbst gestartet hast. Nach der Einrichtung gilt das nicht mehr: Die Aufgabe startet nur noch die geprüfte
Kopie im Programmverzeichnis.

Eigene PC-Werte-Dashboards (Editor) liegen in `dashboards\eigene\`; sie sind nicht im Git und nicht im
Weitergabe-Paket, Updates lassen sie unberührt (sichern: den Ordner kopieren).

Liegt Python unter `%LOCALAPPDATA%` (Standard bei „nur für mich“), bricht die Einrichtung ab. Dann Python für
alle Benutzer installieren: `winget install -e --id Python.Python.3.13 --scope machine`, neues Terminal,
`install.ps1` erneut.

Von Hand (PowerShell als Administrator):
```
.\scripts\install-sensors.ps1 -Python C:\Python313\python.exe -Repo P:\…\touchtabletexpansion_PC
.\scripts\install-sensors.ps1 -Remove        # Aufgabe und Programmordner entfernen
```
PawnIO wieder entfernen: `winget uninstall namazso.PawnIO`. Zuordnung der Sensoren für andere Mainboards:
[sensors.md](sensors.md) (`python -m bridge.sensors --list`, vorher die Aufgabe beenden:
`Stop-ScheduledTask -TaskName "Tablet Deck Sensors"` als Administrator).

## Begleit-Modus (ohne Root)
Die Launcher-App läuft auch als normale App auf einem Tablet ohne Root und ohne eigenen Startbildschirm. Der
bisherige Betrieb heißt **Startbildschirm-Modus** und bleibt Standard (`tablet_mode` = `home`).

**Voraussetzungen:** USB-Debugging am Tablet an, der PC ist per adb gekoppelt (Dialog „USB-Debugging zulassen“
bestätigen), Python und adb wie oben. Root, Magisk und SELinux-Änderungen sind nicht nötig.

**Einrichten:**
```
.\install.ps1 -Companion
```
oder nur das Tablet: `python android\build.py`, dann `tablet\setup-launcher.ps1 -Companion`, und in `config.json`
`"tablet_mode": "companion"` setzen (`python scripts\set_config.py config.json companion`; zurück mit `home`).
Ohne `-Companion` bleibt der Wert in `config.json` unverändert. Der Hub schickt die Betriebsart beim Verbinden an
die App, die danach ihren HOME-Eintrag selbst abschaltet bzw. wieder einschaltet.

**Was anders ist:**
- Die App ist kein Startbildschirm: kein `set-home-activity`, keine Prüfung des Startbildschirms, kein
  Rücksprung-Griff über anderen Apps. Beim Anstecken startet der Hub sie wie einen Tipp auf das App-Symbol.
- Das Skript fasst Sperrbildschirm, Browser (`org.lineageos.jelly`) und feste Ausrichtung per `settings` nicht an.
  Die App hält die Ausrichtung weiter selbst (`WRITE_SETTINGS` wird erteilt).
- Ohne Verbindung zum PC (weder USB noch WLAN) blendet die App nach 60 s einen Hinweis ein und schließt sich
  10 s später; „Offen lassen“ setzt den Zähler zurück.
- Adb-Teil des Hubs bleibt: `adb reverse`, Proxy, Ausrichtung, Uhrzeit, „Wach bleiben beim Laden“.

**Was ohne Root fehlt:**
- Firewall-Modul `hardening` (nur ausgehender Verkehr zum PC/Internet über den Proxy) und Akku-Modul `chargectl`
  (Ladegrenze) - `-Modules` wird im Begleit-Modus mit Warnung übersprungen.
- Ausschalten und Schlafen legen: per USB erledigt das der Hub über adb (`tablet_sleep_with_pc`); im WLAN gibt es
  ohne Root kein Ausschalten, die Anfrage des PCs bleibt wirkungslos (nur Logeintrag). Auch der Rückfall „nach
  5 min ohne PC herunterfahren“ entfällt.
- Der Startbildschirm: HOME-Taste führt zum normalen Android-Launcher, die App startet man über ihr Symbol.

## Tablet als Startbildschirm / Root (optional)
Nur für den Startbildschirm-Modus (`tablet_mode` = `home`, Standard ohne `-Companion`). Das Tablet (Lenovo
TB-X505F) bekommt LineageOS als GSI mit Magisk; die Firewall- und Akku-Module (`install.ps1 -Modules`) gibt es
nur mit Root. Die genaue Abfolge steht in [tablet-setup.md](tablet-setup.md).

### Tablet einmalig vorbereiten
Das Tablet (Lenovo TB-X505F) bekommt LineageOS als GSI mit Magisk. Diese Schritte löschen das Tablet und
werden nicht automatisch gemacht, die genaue Abfolge steht in [tablet-setup.md](tablet-setup.md):
Bootloader entsperren, vbmeta, GSI flashen, Magisk-Boot-Image, `fastboot oem off-mode-charge 0`.
Danach in den Entwickleroptionen USB-Debugging einschalten und den PC einmal am Tablet bestätigen.

### spacedesk-App
Die Android-App `ph.spacedesk.beta` gibt es ohne Play Store nur als XAPK (z. B. APKPure). Entpacken und
die Teile gemeinsam installieren:

```powershell
tools\platform-tools\adb.exe install-multiple base.apk split_*.apk
```

Vorher die Signatur jedes Teils prüfen (`apksigner verify --print-certs`), erwartet ist das Zertifikat mit
SHA-256 `69572e37…aa8c48`. Beim ersten Verbinden fragt Android einmal nach der USB-Berechtigung, dabei
„Immer“ wählen.

### Launcher selbst bauen
`android\build.py` braucht JDK 17 unter `tools\jdk\jdk-17*` und das Android-SDK unter `tools\android-sdk`
(platform `android-36`, build-tools `36.0.0`). Beides ist nicht im Git. Die Bezugsquellen stehen in
[tablet-setup.md](tablet-setup.md).

## Tablet mit dem PC aus
- **Herunterfahren/Neustart von Windows:** Der Wächter (bzw. ohne Wächter die Bridge) schaltet das Tablet
  über eine vorgehaltene adb-Shell aus - beim Herunterfahren startet Windows keine neuen Programme mehr.
  Kappt der PC den
  USB-Strom, bleibt es aus und startet mit dem PC wieder. Liefert der PC auch ausgeschaltet Strom (BIOS,
  z. B. „ErP“ aus), startet das Tablet nach etwa einer Minute neu und wird nach der Zeitsperre dunkel.
- **Abmelden:** nur Bildschirm aus. Nach der Anmeldung weckt die Bridge das Tablet.
- **Rückfall am Tablet:** War es seit dem Einschalten mit dem PC verbunden und ist dann 5 Minuten weder
  per USB noch per WLAN verbunden, fährt es herunter - aber nur bei ausgeschaltetem Bildschirm (in
  Benutzung bleibt es an). „PC aus“ und „Tablet mitgenommen“ lassen sich nicht unterscheiden: Ohne
  erreichbaren PC geht das Tablet im Standby also nach spätestens 5 Minuten aus. Solange es wartet, ist
  „Wach bleiben beim Laden“ aus; beim Wiederverbinden setzt die Bridge es wieder.
- `tablet_sleep_with_pc: false` in `config.json` schaltet das ab.

## Nach der Installation
- Taskleisten-Symbol: Modus am Tablet wählen, Panel-Editor öffnen, beenden.
- Logs: `bridge.log`, `supervise.log` im Projektordner.
- Autostart entfernen: `scripts\install-autostart.ps1 -Remove`.

## Einstellungen (`config.json`)

| Feld | Standard | Bedeutung |
|---|---|---|
| `tablet_mode` | `"home"` | `"home"` = Startbildschirm-Modus (gerootetes Tablet, Launcher ersetzt den Android-Startbildschirm), `"companion"` = Begleit-Modus ohne Root, siehe unten. Ungültige Werte gelten als `home` (mit Logeintrag). Setzen: `install.ps1 -Companion` oder von Hand |
| `tablet_rotation` | `1` | feste Ausrichtung (0–3 wie Android `user_rotation`). spacedesk schaltet beim Start die automatische Drehung mit Hochformat ein: Der Launcher stellt die Ausrichtung wieder her, sobald er vorn ist (braucht `appops … WRITE_SETTINGS allow`, setzt `setup-launcher.ps1`), die Bridge prüft zusätzlich alle 30 s. `null` = nicht anfassen |
| `spacedesk_usb` | `true` | Tablet beim Verbinden auf MTP+ADB stellen, damit der spacedesk-Treiber es übernehmen kann. Dadurch erscheint das Tablet im Explorer als Gerät |
| `spacedesk_silence` | `true` | den Dialog „spacedesk Connection Notification“ ausblenden, der sonst bei jedem Anstecken mitten auf dem Hauptmonitor erscheint |
| `web` / `web_proxy_port` | `true` / `8766` | Web-Kachel: Internet für das Tablet über einen Proxy der Bridge (per USB). Erreichbar ist nur das öffentliche Internet, nicht das Heimnetz oder der PC |
| `wlan` | `{"enabled": true, "port": 8767}` | WLAN-Zugang mit TLS, siehe oben |
| `auto_modes` / `auto_default` | `[]` / `null` | Tablet-Modus nach laufenden Programmen wechseln, z. B. `[{"process": "StarCitizen.exe", "mode": "panel"}]` |
| `tablet_sleep_with_pc` | `true` | Beim Herunterfahren oder Abmelden von Windows den Tablet-Bildschirm ausschalten. Beim nächsten Verbinden wird es wieder geweckt |
| `audio_output` | `{"avoid": "spacedesk", "prefer": null}` | Macht spacedesk seinen virtuellen Lautsprecher zum Standard, stellt die Bridge auf `prefer` zurück (ohne `prefer` bleibt es, wie es ist), z. B. `"Lautsprecher (Realtek USB Audio)"`. Den Gerätenamen findest du unter Windows-Einstellungen → Sound. Wechselst du selbst auf ein anderes Gerät, bleibt das unberührt |

Weitere Felder stehen in der [README](../README.md#konfiguration).

## WLAN-Betrieb (ohne Kabel)
Touchpad mit Medien, Panel, PC-Werte und die Web-Kachel laufen auch über WLAN. PC-Werte laufen über den Hub (Seite `/stats/`). spacedesk hat ein
eigenes WLAN in seiner App.

**Einrichten**
1. Tablet einmal ins WLAN bringen: Kachel „Android“ → Netzwerk & Internet → WLAN. Das Passwort gibst du
   am Tablet selbst ein.
2. Tablet einmal per USB anstecken: Die Bridge teilt dem Launcher dabei die WLAN-Adresse des PCs mit.
3. Kabel ab: Nach etwa 9 s wechselt der Launcher auf WLAN, der Statuspunkt wird **blau** (grün = USB,
   rot = getrennt). Kabel wieder dran: zurück auf USB.
4. Empfehlung: Im Router dem PC eine feste IP geben (DHCP-Reservierung). Der Launcher erfährt die
   Adresse nur per USB. Ändert sie sich, findet er den PC erst nach dem nächsten Anstecken wieder.

**Sicherheit**
- Verschlüsselt mit TLS. Die Bridge erzeugt dafür einmalig eine eigene CA in `tls/` (nicht im Git). Die
  APK enthält sie nicht (eine APK für alle PCs): Bei jedem Anstecken per USB schickt der Hub die öffentlichen
  Zertifikate (Wurzel und Zwischen-CA, nie einen Schlüssel) per ADB an den Launcher. Nur die ADB-Shell darf
  diesen Empfänger aufrufen. Wird `tls/` gelöscht, entsteht eine neue CA; das Tablet bekommt sie beim
  nächsten Anstecken.
- Jeder PC, dem du am Tablet USB-Debugging erlaubst, kann seine eigene CA setzen (er steuert das Tablet per
  ADB ohnehin). USB-Debugging deshalb nur für den eigenen PC bestätigen.
- Der Launcher prüft die Kette nur für die WLAN-Adresse des Hubs (Wurzel, Zwischen-CA, IP-Adresse im
  Zertifikat). Die Web-Kachel und alle anderen Verbindungen vertrauen nur den System-CAs.
- Die Zwischen-CA darf nur private IP-Adressen beglaubigen (auf dem Tablet geprüft). Selbst mit ihrem
  Schlüssel lassen sich keine fremden Webseiten fälschen.
- Ohne Kopplungsgeheimnis nimmt die Bridge über WLAN keine Steuerverbindung an. Editor und Senden bleiben
  nur am PC selbst erreichbar.
- Im WLAN geht die Web-Kachel direkt ins Internet. Geräte im Heimnetz (Router, NAS, der PC) sind für
  den Launcher gesperrt, ausgenommen der Hub-Port 8767 (Modul `hardening`).

**Windows-Firewall**
Der WLAN-Zugang lauscht auf TCP 8767. Er muss nur im **privaten** Netz erreichbar sein. Eine passende
Regel (PowerShell als Administrator):

```powershell
New-NetFirewallRule -DisplayName "Tablet Deck (WLAN)" -Direction Inbound -Action Allow -Protocol TCP `
  -LocalPort 8767 -Profile Private -RemoteAddress LocalSubnet -Program "C:\Python313\pythonw.exe"
```

`-Program` muss das pythonw sein, mit dem die Bridge läuft (siehe geplante Aufgabe „Tablet Deck
Bridge“). Alternativ `-Program` weglassen, Port, `Private` und `LocalSubnet` grenzen bereits ein.

Hast du früher den Windows-Dialog „python.exe zulassen“ bestätigt, gibt es schon Regeln namens
„Python“. Sie erlauben **jeden** Port, auch in öffentlichen Netzen. Prüfen und auf „Privat“ beschränken
(oder löschen und die Regel oben verwenden). Solange sie gelten, ist die eingeschränkte Regel oben
wirkungslos:

```powershell
Get-NetFirewallRule -DisplayName Python | Format-Table DisplayName, Profile, Action
Get-NetFirewallRule -DisplayName Python | Set-NetFirewallRule -Profile Private
```

## Webseiten ans Tablet schicken
- Taskleisten-Symbol → „URL aus Zwischenablage ans Tablet“
- Kommandozeile: `python -m bridge.send https://…`
- Browser-Erweiterung (Chrome, Edge, Firefox): Rechtsklick → „Seite/Link/Bild ans Tablet senden“ oder das
  Symbol in der Leiste. Einrichten:
  1. Chrome/Edge: `chrome://extensions` bzw. `edge://extensions` → Entwicklermodus an → „Entpackte
     Erweiterung laden“ → Ordner `extension`. Firefox: `about:debugging` → „Temporäres Add-on laden“ →
     `extension\manifest.json` (bleibt nur bis zum Neustart von Firefox).
  2. Taskleisten-Symbol → „Schlüssel für Browser-Erweiterung kopieren“, in den Optionen der Erweiterung
     einfügen. Der Schlüssel (`send.key`) erlaubt nur das Senden von Webseiten, keine Tasten oder Maus.

Das Tablet wechselt dann in die Kachel „Web“. Dort lässt sich auch direkt eine Adresse eintippen.

## Weitergabe als Zip
Für Weitergabe an andere, die das Repo nicht klonen:

```powershell
python scripts\make_zip.py          # -> dist\TabletDeck-<git describe oder Datum>.zip
```

Das Paket enthält alle von git verwalteten Dateien plus `android\build\tablet-deck.apk` (fehlt sie, gibt es eine
Warnung; vorher `python android\build.py`). Nie enthalten sind `secrets\`, `tls\`, `*.key`, Logs, Zwischenspeicher,
Signierschlüssel (`*.keystore`), `tools\`, Lesezeichen und Verlauf (`bookmarks.json`, `web_history.json`),
`sensors.json`, die PC-gebundenen `config.json` und `launcher.json` (statt ihrer liegen die `*.example.json`
bei) sowie lokale Entwicklungsnotizen (`CLAUDE.md`, `PLAN.md`, `docs\weiter.md`, `docs\review.md`, falls vorhanden). Eine Prüfliste bricht den Bau ab, wenn eine Datei mit geheimnisverdächtigem Namen (`*.pem`, `.env` …)
oder Inhalt (privater Schlüssel, `sk-ant-…`) ins Paket käme; gemeldet werden nur Dateiname und Art des Fundes.

Empfänger: Zip entpacken, Schnellstart oben. Kopplungsgeheimnis (`secret.key`) und WLAN-Zertifikat entstehen
neu auf dem PC des Empfängers.

## Fehlerbehebung
- **`su` wird verweigert** (`install-module.ps1` bricht ab): In der Magisk-App unter „Superuser“ den
  Eintrag „Shell“ erlauben.
- **Tablet wird nicht erkannt:** `tools\platform-tools\adb.exe devices`. Bei `unauthorized` den Dialog am
  Tablet bestätigen.
- **„Bildschirm“ bleibt schwarz:** In der „spacedesk DRIVER Console“ muss unter COMMUNICATION INTERFACES
  „USB Cable Android“ an sein. Das Tablet einmal ab- und wieder anstecken.
- **PC-Ton kommt aus dem Tablet:** `audio_output.prefer` prüfen, er muss den Gerätenamen exakt enthalten.
- **Zustand des Tablets im Log:** Die Bridge schreibt alle 5 Minuten in `bridge.log`, wie viel Speicher frei
  ist und wie lange das Tablet läuft, dazu neue Android-Ereignisse (Neustart `SYSTEM_BOOT`, Abstürze, hängende
  Apps `…_anr`, System-Hänger `system_server_pre_watchdog`). Beim Anstecken stehen dort die letzten drei Starts.
  Suchbegriff: `Tablet <Seriennummer>:`.
- **Tablet geht mit dem PC nicht aus:** Im Wächter-Log (`supervise.log`) steht „Tablet … ausgeschaltet“. Zeigt
  `bridge.log` beim nächsten Start einen Android-Start etwa 80 s danach, hat das Tablet ausgeschaltet und ist
  am weiter stromführenden USB-Anschluss wieder hochgefahren (`fastboot oem off-mode-charge 0` aus der
  Einrichtung startet es am Ladegerät). Steht dort „kein Tablet per USB/adb gefunden“, war es beim
  Herunterfahren nicht per adb verbunden.
- **Tablet zeigt Hochformat:** Der Launcher korrigiert das sofort, wenn er vorn ist, die Bridge spätestens nach 30 s. Sonst `tablet_rotation` und `adb shell appops get app.tabletdeck.launcher WRITE_SETTINGS` (muss `allow` sein, sonst `tablet\setup-launcher.ps1` erneut) prüfen.
- **`config.json`/`launcher.json` fehlen:** `python -m bridge.firstrun` legt sie aus den Beispielen an (die
  Bridge tut das beim Start ebenfalls). Kaputte Dateien: löschen und neu anlegen lassen.
- **Sensor-Werte fehlen:** `.\install.ps1 -Check`, Abschnitt „Sensor-Helfer“; Zuordnung: [sensors.md](sensors.md).
- **Logs:** `bridge.log`, `supervise.log` im Projektordner.
