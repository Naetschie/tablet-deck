# Änderungen

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
