# Prüfliste für Commit-Reviews

Auftrag: `git show <commit>` lesen, nur lesen (nichts ändern). Ergebnis als Liste mit Schweregrad
(hoch / mittel / niedrig) und konkretem Fix, dazu kurz, was geprüft und in Ordnung ist. Aussagen ohne Beleg im
Code als Vermutung kennzeichnen. Projektüberblick: `README.md`, Beitragsregeln: `CONTRIBUTING.md`.

## Immer prüfen
- **Sicherheit:** Geheimnisse in Logs/Antworten? Neue Endpunkte: Origin, Loopback, Kopplungs-Cookie im WLAN?
  Pfade/IDs aus Eingaben per `fullmatch` geprüft (kein `..`, `\`, `:`)? Fremde Webseiten ohne JS-Schnittstelle?
- **Ende-zu-Ende:** Passen Hub, Tablet-Seite und Launcher zusammen (Nachrichtenfelder, Fehlerfälle, Neuverbinden,
  Hub-Neustart, USB↔WLAN-Wechsel)? Was passiert, wenn eine Datei fehlt oder kaputt ist?
- **Gehaltene Tasten:** Kann eine Taste hängen bleiben (Panelwechsel, Ansichtswechsel, Verbindungsabbruch,
  gelöschtes Panel)? Wird gelöst, wer gedrückt hat?
- **Touch/Android:** Schlucken unsichtbare Views Berührungen? Läuft etwas im Schlaf (Handler vs. AlarmManager)?
  Lebenszyklus (Launcher-Neustart, Vollbild, App-Kachel)?
- **Editor:** Fokusverlust beim Tippen (Container neu gezeichnet)? `layout == null`? Ungespeicherte Änderungen?
- **Windows:** Herunterfahren (keine neuen Prozesse mehr), pythonw ohne stderr (Fehler landen nur im Log),
  Job-Objekt des Wächters, adb-Timeouts.
- **Tests:** Deckt ein Test die neue Logik ab? Laufen `tests/` grün?

## Typische Fehler aus früheren Reviews
- Rückgabewert „leer“ und „Fehler“ verwechselt (z. B. `adb devices` → `[]` statt `None`).
- Gespeicherten Zustand mit einem Wert überschrieben, den ein anderer Teil gerade bewusst gesetzt hat (stayon).
- Retry-/Watchdog-Schleifen ohne Obergrenze; Log-Spam bei jeder Sekunde.
- Validierung erlaubt, was der Editor anbietet, aber das Tablet ignoriert (oder umgekehrt).
