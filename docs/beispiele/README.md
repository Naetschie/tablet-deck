# Beispiel-Panels

Nur zum Ansehen, **nicht** unter `profiles/` – der Hub lädt sie nicht von allein.

## cockpit-demo.json

Zeigt alle Bausteine des Panel-Formats (Beschreibung im Kopf von `bridge/layout.py`): freie Seite 24 × 16 mit
Bereichen (`frame`) und Beschriftungen (`text`), Kippschalter, Pfeile (einfach und doppelt), Auswahlleisten
(`segment`), großer Hauptknopf, Leisten, gesicherte Gefahrentasten (`hold-confirm` und `double`) und
Seitengruppen (`section`: Flug / Kampf / Weitere). **Alle Tasten sind Platzhalter** (F-Tasten, Numpad) –
beim Antippen gehen echte Tastendrücke an den PC. Zum Ansehen daher kein Spiel im Vordergrund haben.

Kurz einspielen (Hub läuft, Tablet verbunden):

1. Datei kopieren: `docs/beispiele/cockpit-demo.json` → `profiles/star-citizen/cockpit-demo.json`
   (oder in den Ordner eines anderen Spiels aus `games.json`).
2. Der Hub erkennt die neue Datei von selbst (Profile-Prüfung läuft laufend, `bridge.log` meldet
   „Profil … geladen“); am Tablet erscheint beim Spiel ein weiterer Reiter „DEMO Cockpit“.
3. Nach dem Ansehen die kopierte Datei wieder löschen.

Hinweise zum Gestalten freier Seiten: Ein `frame` belegt oben etwa 24 px für den Titel, die erste Tastenreihe
beginnt daher eine Zelle tiefer. Tasten innerhalb eines Bereichs bekommen am Rand eine Zelle Luft. Bei Rastern
über 12 × 8 werden Abstände und Schrift kleiner; Tasten möglichst mindestens 2 × 2 Zellen groß machen
(Trefferfläche).
