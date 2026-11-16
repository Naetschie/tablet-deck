# Mitmachen

Am meisten helfen **Panels für Spiele** und **Dashboards für die PC-Werte**. Beides sind JSON-Dateien, die
der Hub prüft – Programmieren ist dafür nicht nötig.

## Panel für ein Spiel
1. Spiel in `games.json` eintragen (falls noch nicht da): `id`, `name`, `exe` (Programmname des Spiels).
2. Panel anlegen: am einfachsten im Panel-Editor (Taskleisten-Symbol → „Panel-Editor öffnen“) oder mit dem
   Generator (`bridge/generate.py`, Vorlagen in `bridge/templates/`). Die Datei liegt dann unter
   `profiles/<spiel-id>/<panel>.json` (eigene Panels). Mitgelieferte, schreibgeschützte Panels liegen unter
   `panels/<spiel-id>/<name>.json` und werden nur vom Projekt gepflegt; der Hub zeigt sie als „mitgeliefert“
   (Schloss), bearbeiten geht nur über eine Kopie. Ein Beitrag, der mitgeliefert werden soll, kommt nach `panels/`.
3. **Tastenbelegungen nur aus einer Quelle** – der Standardbelegung des Spiels, dem Handbuch oder der
   offiziellen Seite. Nie raten. Die Quelle bitte im Pull Request nennen.
4. Prüfen: `python scripts/check_contrib.py profiles/<spiel-id>/<panel>.json` (bzw. `panels/…`)

### Was in beigetragenen Panels nicht erlaubt ist
Ein Panel sendet Tastendrücke an das Fenster, das am PC gerade vorn ist – normalerweise das Spiel. Damit ein
Panel aus fremder Hand dabei möglichst wenig anrichten kann:
- **kein `open`** (Programme, Pfade oder Webseiten öffnen) – das trägt jeder nur für sich selbst ein
- **keine Systemkürzel** (Esc mit Zusatztaste, Alt+F4, Alt+Tab, Alt+Leertaste). Tasten, die nur
  Strg/Alt/Shift halten oder umschalten (z. B. Sprinten mit Shift halten), sind erlaubt, werden aber als
  Hinweis für die Handprüfung gemeldet
- **Makros tippen nichts:** höchstens 12 Schritte, ein `text`-Schritt, zwei einzelne Zeichentasten, zweimal
  Enter; `text` höchstens 60 Zeichen, nur Buchstaben, Ziffern, Leerzeichen und harmlose Satzzeichen, keine
  Befehlsnamen. Chat-Grüße wie „o7“ gehen, Befehle nicht.

Die Prüfung läuft bei jedem Pull Request automatisch. Sie ist eine Hürde, keine Garantie: Mehrere Tasten, die
der Nutzer nacheinander drückt, können zusammen mehr bewirken als jede einzeln, und hat ein anderes Fenster
den Fokus (Explorer, Browser), wirken auch gewöhnliche Kürzel wie Strg+L oder Entf dort. Ein Pull Request kann
außerdem Code und die Prüfung selbst ändern. **Deshalb wird jeder Beitrag von Hand gelesen**, besonders
Makros, `hold`/`toggle` und alles außerhalb von `panels/`, `profiles/` und `dashboards/`.

## Dashboard für die PC-Werte
Dateien unter `dashboards/<name>.json`, Aufbau und Widget-Arten in [docs/sensors.md](docs/sensors.md).
Nur IDs verwenden, die der Sensor-Helfer kennt (`python -m bridge.sensors --list`). Prüfen:
`python scripts/check_contrib.py dashboards/<name>.json`

## Nicht ins Repo
- Dateien aus Spielen (z. B. das Star-Citizen-Standardprofil) – die erzeugt jeder aus der eigenen Installation
- eigene Einstellungen (`config.json`, `launcher.json`, `sensors.json`), Schlüssel, Logs

## Code
Python (Hub), Java (Launcher, ohne Gradle: `python android/build.py`), HTML/JS ohne Frameworks. Vor einem
Pull Request: `python -m unittest discover -s tests -q`. Kommentare, Texte und Oberfläche auf Deutsch.

Mit einem Beitrag stimmst du zu, dass er unter der GPL-3.0 (siehe `LICENSE`) steht.
