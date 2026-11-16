# Mitmachen

Am meisten helfen **Panels für Spiele** und **Dashboards für die PC-Werte**. Beides sind JSON-Dateien, die
der Hub prüft – Programmieren ist dafür nicht nötig.

## Panel für ein Spiel
1. Spiel in `games.json` eintragen (falls noch nicht da): `id`, `name`, `exe` (Programmname des Spiels).
2. Panel anlegen: am einfachsten im Panel-Editor (Taskleisten-Symbol → „Panel-Editor öffnen“) oder mit dem
   Generator (`bridge/generate.py`, Vorlagen in `bridge/templates/`). Die Datei liegt dann unter
   `profiles/<spiel-id>/<panel>.json`.
3. **Tastenbelegungen nur aus einer Quelle** – der Standardbelegung des Spiels, dem Handbuch oder der
   offiziellen Seite. Nie raten. Die Quelle bitte im Pull Request nennen.
4. Prüfen: `python scripts/check_contrib.py profiles/<spiel-id>/<panel>.json`

### Was in beigetragenen Panels nicht erlaubt ist
Ein Panel aus fremder Hand darf am PC nichts tun, was über Tastendrücke im Spiel hinausgeht:
- **kein `open`** (Programme, Pfade oder Webseiten öffnen) – das trägt jeder nur für sich selbst ein
- **`text` in Makros** nur kurz (höchstens 60 Zeichen), nur Buchstaben, Ziffern, Leerzeichen und harmlose
  Satzzeichen, keine Befehlsnamen. Chat-Grüße wie „o7“ gehen, Befehle nicht.

Die Prüfung läuft bei jedem Pull Request automatisch. Sie ist eine Hürde, keine Garantie: **Jeder Beitrag
wird zusätzlich von Hand gelesen**, bevor er übernommen wird.

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
