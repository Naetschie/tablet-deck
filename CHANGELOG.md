# Änderungen

## 5.1 – 23.11.2026

Karten für alle installierten Spiele, ein Karten-Reiter im Editor und ein **Light-Modus** für schwache Tablets.
Anlass war ein Samsung Tab A 10.1 (2 GB, Mali-Grafik) im Begleit-Modus, bei dem die 3D-Sternenkarte die App
sekundenlang blockierte, bis Android „App reagiert nicht“ meldete.

### Karten
- Der Hub schlägt **alle installierten Spiele** (Steam, Epic, GOG …) im Hintergrund bei Map Genie nach, nicht erst
  das laufende. Gefundene Karten stehen sofort im Kartenmenü und bleiben nach einem Hub-Neustart erhalten
  (`mapgenie_cache.json`, 30 Tage). Eine Anfrage nach der anderen, nach einem Netzfehler 30 Minuten Pause.
- Map Genie wird **direkt auf die Karte** verlinkt (z. B. Enshrouded → „Embervale“), bei mehreren Karten je ein
  Eintrag. Bisher landete man auf der Übersichtsseite.
- Die Karten-Kachel lädt keine Werbe- und Messdienste mehr (spart Speicher und Rechenzeit).

### Editor: Reiter „Karten“
- Kartenliste je Spiel bearbeiten: hinzufügen, umbenennen, löschen, sortieren (erste = Standard), als „schwer“
  markieren, **Bei Map Genie suchen**, **Zeigen** (öffnet die Karte sofort am Tablet), **Standard** (eigene Liste
  verwerfen).
- Gespeichert wird in `maps.json` (nicht im Git, nicht im Zip). `games.json` bleibt unverändert und darf beim
  Update überschrieben werden.
- Kartenadressen werden strenger geprüft (nur `https`, Host aus Buchstaben/Ziffern/Punkt/Minus, keine doppelten,
  höchstens 30). Eine eigene `games.json`, die dagegen verstößt, meldet der Hub als fehlerhaft.
- Der Hinweis „Mitgeliefert und schreibgeschützt“ erscheint nur noch im Reiter Panels.

### Light-Modus (schwache Tablets)
- Pro Gerät, Standard aus: Kartenseiten sehen die Pixeldichte 1 (eine 3D-Karte zeichnet bei Dichte 1,5 nur noch
  etwa 44 % der Pixel), schwere Karten (z. B. Ark Starmap) werden nicht von selbst gewählt, verdeckte Seiten
  werden freigegeben, solange die Karte offen ist, Hub-Seiten ohne Schatten und Übergänge.
- Einschalten: `.\install.ps1 -Light`, im Editor unter **⚙ Einstellungen → Geräte**, oder direkt am Tablet: Hängt
  die Karte mehrmals, zeigt die Kachel „Die Karte bremst dieses Gerät“ mit **Light-Modus einschalten**.
- Unabhängig davon gibt die App verdeckte Ansichten frei, wenn Android knappen Speicher meldet.
- Kartenwahl: Eine im Menü (oder per „Zeigen“) gewählte Karte gilt als bewusste Wahl und bleibt, auch im
  Light-Modus. Was vor 5.1 gewählt wurde, zählt als „zuletzt gezeigt“ – im Light-Modus kann daher einmalig eine
  leichte Karte statt einer früher gewählten schweren erscheinen.

### Aktualisieren
- Launcher-App: `.\install.ps1` (lädt `tablet-deck.apk` aus dem Release v5.1, falls `tools\jdk` und
  `tools\android-sdk` fehlen), oder `python android/build.py`, dann
  `tools\platform-tools\adb.exe install -r --no-streaming android\build\tablet-deck.apk`.
- Hub: Bridge neu starten (Taskleisten-Symbol → Beenden, dann geplante Aufgabe „Tablet Deck Bridge“ starten).
  Beim ersten Start schlägt er alle installierten Spiele bei Map Genie nach (einige Minuten im Hintergrund).
- Schwaches Tablet: `.\install.ps1 -Light` (mit angestecktem Tablet; bei Bedarf zusammen mit `-Companion`).

## 5.0.1 – 22.11.2026

Fehlerbehebungen aus der ersten Einrichtung auf einem fremden PC.

### Installation
- APK-Installation brach auf manchen Tablets mit `failed to write; splice failed: EINVAL` ab (neuere adb-Versionen
  übertragen per „Streamed Install“). `tablet\setup-launcher.ps1` versucht es dann selbst mit `--no-streaming`.
  Hinweis in `docs/install.md` (Fehlerbehebung).

### Launcher-App
- Begleit-Modus: Die Zurück-Taste schickt die App jetzt in den Hintergrund. Bisher tat sie nichts (richtig nur für
  den Startbildschirm-Modus), und weil die App die Systemleisten ausblendet, kam man je nach Gerät nicht mehr aus
  ihr heraus. Im Startbildschirm-Modus bleibt die Taste ohne Wirkung.

### Aktualisieren
- Launcher-App: `.\install.ps1` (lädt `tablet-deck.apk` aus dem Release v5.0.1, falls `tools\jdk` und
  `tools\android-sdk` fehlen), oder `python android/build.py`, dann
  `tools\platform-tools\adb.exe install -r --no-streaming android\build\tablet-deck.apk`.
- Hub und Webseiten sind unverändert.

## 5.0 – 21.11.2026

Mit 5.0 ist der Betrieb mit **mehreren Geräten** vollständig: Tablet und Handy (oder zwei Tablets) gleichzeitig,
jedes mit eigener Betriebsart, eigenen Kacheln und eigenem Start-Panel, eins davon Hauptgerät für „An Tablet
senden“. Die Grundlagen kamen mit 4.4, jetzt auch die Einrichtung.

### Installation
- `.\install.ps1 -ListDevices` zeigt alle angesteckten Android-Geräte mit Seriennummer, Modell und ob der
  Launcher schon installiert ist. Ändert nichts und läuft vor der Python-Einrichtung.
- `.\install.ps1 -Serial <Seriennummer>` richtet nur dieses Gerät ein. Sind mehrere angesteckt und fehlt
  `-Serial`, fragt das Skript per Nummer, welches (bisher brach es ab).
- `-Companion` setzt den Begleit-Modus für das eingerichtete Gerät (`tablet_modes` in `config.json`), andere
  Geräte bleiben unverändert. Nur beim allerersten Gerät (allein angesteckt, ohne `-Serial`) wird er zusätzlich
  Standard für alle (`tablet_mode`), mit `-SkipTablet` nur Standard. Wurde kein Gerät eingerichtet, meldet das
  Skript, dass `-Companion` nicht eingetragen ist.
- Spacedesk-Prüfung, Magisk-Module (`tablet\install-module.ps1 -Serial`) und Neustart treffen das gewählte Gerät.
- Per WLAN-adb verbundene Geräte (`IP:Port`, `adb-…`) richtet das Skript nicht ein (der Hub koppelt per USB).
- `-Check` prüft das eine angesteckte Gerät gezielt, auch wenn daneben ein Gerät `unauthorized`/`offline` hängt.
- `docs/install.md`: Abschnitt „Weiteres Gerät“ (Schritt für Schritt), Schalter-Tabelle ergänzt.

### Aktualisieren
- Launcher-App auf jedem Gerät: `.\install.ps1 -Serial <Seriennummer>` (baut die APK, wenn `tools\jdk` und
  `tools\android-sdk` im Projekt liegen, sonst lädt es `tablet-deck.apk` aus dem Release v5.0), oder
  `python android/build.py`, dann `tools\platform-tools\adb.exe -s <Seriennummer> install -r android\build\tablet-deck.apk`. Die App selbst ist
  gegenüber 4.4 unverändert (nur die Versionsnummer).
- Hub und Webseiten sind unverändert.

## 4.4 – 21.11.2026

### Mehrere Geräte
- Der Hub führt eine Geräteliste (`devices.json`, nicht im Git): Jedes per USB gekoppelte Gerät mit Launcher wird
  eingetragen, das erste wird **Hauptgerät**. Der Launcher bekommt dabei seine Kennung und meldet sich damit auch
  im WLAN.
- „An Tablet senden“ geht ab zwei Geräten nur ans Hauptgerät. Ist es nicht verbunden, kommt eine Fehlermeldung,
  die Seite geht nicht an ein anderes Gerät. Umstellen: Taskleisten-Symbol → „Webseiten senden an“.
- Pro Gerät in `devices.json` einstellbar: `name`, `mode` (`home` oder `companion`, geht `tablet_modes` vor),
  `rotation` (0-3, `null` = nicht anfassen), `tiles` (welche Kacheln die Leiste zeigt) und `panel` (Start-Panel).
  Wirksam nach Hub-Neustart, die Betriebsart beim nächsten Anstecken per USB. Ansichtswechsel bekommen nur Geräte
  mit der Kachel. Mit nur einem Gerät ändert sich nichts. Details: `docs/install.md`.
- Ungültige Werte in `devices.json` werden mit Logeintrag ignoriert. Ist die Datei nicht lesbar, überschreibt
  der Hub sie nicht.

### Launcher
- Läuft ab Android 10 (im Begleit-Modus), getestet mit einem Huawei-Handy (EMUI 10). EMUI braucht dafür die
  Freigabe unter Akku → App-Start (siehe `docs/install.md`).
- Hochkant steht die Leiste unten statt links. Handys mit Notch: Inhalt reicht bis in den Kamera-Ausschnitt.

### Panel und Touchpad
- Neues Star-Citizen-Panel **Handy (hochkant)**: Seite „Schilde“ mit großem Schildfeld, Energieverteilung und
  Abwehr, Seite „Komfort“ mit Systemen, Schiff und Pilot.
- Das Schildfeld passt sich der Fläche an, statt fest im Format 3:2 zu zeichnen. Im Cockpit füllt es seinen
  Rahmen.
- Welches Panel ein Gerät zeigt: Wahl von Hand an diesem Gerät, sonst sein Start-Panel, sonst das zuletzt
  gezeigte.
- Touchpad-Seite hochkant: Touchpad oben, Tasten und Medien darunter, die Seite scrollt.

### Aktualisieren
- Launcher-App auf **jedem** Gerät: `python android/build.py`, dann
  `tools\platform-tools\adb.exe -s <Seriennummer> install -r android\build\tablet-deck.apk`, oder `.\install.ps1`
  (lädt `tablet-deck.apk` aus dem Release v4.4). Danach jedes Gerät einmal per USB anstecken (Kennung).
  Huawei/EMUI: vorher die App-Start-Freigabe setzen (`docs/install.md`).
- Hub neu starten (geplante Aufgabe „Tablet Deck Bridge“ beenden und starten).

## 4.3 – 21.11.2026

### Verbindung
- Tablet blieb nach dem PC-Start auf „getrennt“, obwohl die Bridge es per USB erreichte: Der WebView-Renderer
  hing nach Tagen Laufzeit mit vollem Speicher, das Neuladen der Steuerseite half nicht. Der Launcher erkennt
  das jetzt (Hub antwortet, Steuerseite bleibt 60 s getrennt) und ersetzt den Renderer selbst, höchstens
  zweimal je Ausfall. Ohne erreichbaren PC passiert das nie.
- Die Prüfung der Steuerseite alle 20 s lief nicht, solange die Verbindungsversuche schnell scheiterten.
  Sie startet jetzt auch dann.
- Die USB-Prüfung des Launchers nutzt `127.0.0.1` statt `localhost`. Android konnte `localhost` zeitweise nicht
  auflösen, der PC galt dann als weg und der Launcher wechselte unnötig auf WLAN.
- Logcat nennt beim ersten Fehlschlag einer USB-Prüfung den Grund. Die Zeile der Seitenprüfung zeigt, ob der
  Hub erreichbar ist und den wievielten Versuch, bzw. dass die Beendigungen ausgeschöpft sind.

### Installation
- `docs/install.md`, Fehlerbehebung: „Tablet zeigt getrennt, obwohl die Bridge verbunden meldet“.

### Aktualisieren
- Launcher-App: `python android/build.py`, dann
  `tools\platform-tools\adb.exe install -r android\build\tablet-deck.apk`, oder `.\install.ps1` (lädt
  `tablet-deck.apk` aus dem Release v4.3). Hub und Webseiten sind unverändert.

## 4.2 – 19.11.2026

### Panel
- Tastenkürzel stehen nicht mehr unter jeder Taste. Das Panel drückt die Taste selbst, beim Spielen war das
  Kürzel nur zusätzlicher Text. Wer sie sehen will: Panel-Kachel in `launcher.json` mit `"path": "/?keys=1"`
  (wird gemerkt, `?keys=0` schaltet wieder aus). Der Editor zeigt sie wie bisher.
- Tasten erscheinen so, wie sie beschriftet sind („Flight Ready“ statt „FLIGHT READY“). Großbuchstaben nur
  noch für Bereichstitel, Reiter und Hinweise; die Editor-Vorschau zeigt es genauso.
- Gleich große Tasten in einem Bereich haben dieselbe Schriftgröße. Vorher stand z. B. „Entkoppeln“ kleiner
  direkt neben „Quantum“.
- Große Hauptknöpfe („Flight Ready“, „Köder-Panik“) waren im feinen Raster nur 13 px groß, jetzt 18 px.

### Star Citizen
- Schilde: Oben und Unten entfernt (Panel und Vorlagen). Schildgeneratoren haben nur Blase, vorne/hinten oder
  Quadranten; die beiden Aktionen gibt es in der Belegung, sie wirken aber auf keine Schildseite. Die
  Schiffsansicht wird dafür größer.
- Auto-Layout: Ein Schildbereich ohne weitere Tasten füllt seinen Rahmen, auf „Flug & Kampf“ bleibt keine
  Lücke mehr.

### Installation
- `install.ps1` läuft auf einem frischen PC durch: Python wird für alle Benutzer installiert (Anfrage nach
  Administratorrechten; nur mit `-SkipSensors` für den eigenen Benutzer), der python.org-Installer ist bis
  zum Start gegen Austausch gesperrt.
- Launcher-APK aus dem Release: Prüfsumme ist Pflicht, dazu wird das Signaturzertifikat gegen
  `android/release-cert.sha256` geprüft. Eine vorhandene APK wird nur ohne Download genommen, wenn ihre
  Version passt.
- Abgelehnte Administratorrechte und andere Installer-Fehler werden klar gemeldet.
- Wechsel von einer selbst gebauten auf die Release-APK (oder umgekehrt): `tablet/setup-launcher.ps1` meldet
  die andere Signatur jetzt klar und nennt den nötigen `adb uninstall`.

### Aktualisieren
- Launcher-App (nur Versionsnummer neu, keine Funktionsänderung): `python android/build.py`, dann
  `tools\platform-tools\adb.exe install -r android\build\tablet-deck.apk`, oder `tablet-deck.apk` aus dem Release.
- Hub neu starten (geplante Aufgabe „Tablet Deck Bridge“ beenden und starten), die Tablet-Seiten laden dann neu.

## 4.1 – 18.11.2026

### Tablet schläft mit dem PC
- Beim Herunterfahren, beim Neustart und beim Abmelden von Windows wird das Tablet nur noch schlafen gelegt
  (Bildschirm aus), nicht mehr ausgeschaltet. Liefert der PC auch ausgeschaltet USB-Strom (z. B. BIOS „ErP“
  aus, nötig für Wake on LAN), startete ein ausgeschaltetes Tablet wegen `off-mode-charge 0` nach etwa einer
  Minute von selbst wieder. Beim Start des PCs weckt der Hub das Tablet wie bisher.
- Per WLAN verbundene Tablets werden nach dem PC-Start ebenfalls wieder geweckt: einmal pro Start bzw.
  Schlafbefehl, nicht nach jedem WLAN-Aussetzer. Braucht Root und das Modul `hardening` ab 1.7
  (`tablet/install-module.ps1 tablet/hardening/module -Reboot`).
- Rückfall-Abschaltung im Launcher: fährt das Tablet nur noch ohne Stromquelle herunter (mitgenommen, Akku).
  Am Strom schläft es weiter und prüft alle 30 Minuten erneut; abgesteckt geht es so spätestens 30 Minuten nach dem Abstecken aus.
- Begleit-Modus (ohne Root): per USB wird das Gerät beim Herunterfahren ebenfalls nur schlafen gelegt.

### Dokumentation
- `docs/guide.md`: Bedienungsanleitung mit Bildschirmfotos (Leiste, Spiel-Panels, Touchpad, PC-Werte,
  Editor, automatische Erzeugung, KI, Teilen eigener Panels); Link und Titelbild im README.
- `docs/install.md`: Abschnitt „Tablet schläft mit dem PC“ neu gefasst.

### Aktualisieren
- Launcher-App: `python android/build.py`, dann
  `tools\platform-tools\adb.exe install -r android\build\tablet-deck.apk`.
- Modul `hardening` 1.7 (nur für das Wecken per WLAN nötig, Tablet startet dabei neu):
  `tablet\install-module.ps1 tablet\hardening\module -Reboot`.
- Hub neu starten (geplante Aufgabe „Tablet Deck Bridge“ beenden und starten).

## 4.0 – 17.11.2026
- Spiel-Panels (Star-Citizen-Cockpit), automatische Erstellung mit Auto-Layout, generisches Einlesen der
  Spielsteuerung mit Lernmodus, Standardtasten aus dem Netz und per KI-Suche (Anthropic/OpenAI).
- DayZ-Panel „Waffen & Funk“ (Tasten aus der echten Belegung).
