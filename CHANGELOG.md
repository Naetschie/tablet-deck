# Änderungen

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
- Logcat nennt den Grund einer gescheiterten USB-Prüfung. Die Zeile der Seitenprüfung zeigt, ob der Hub
  erreichbar ist und den wievielten Versuch.

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
