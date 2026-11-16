# Sensor-Helfer (PC-Messwerte)

Eigener Prozess neben dem Hub. Er sammelt Messwerte aus freien Quellen (kein HWiNFO, kein MoBro) und stellt
sie dem Hub lokal bereit. Der Hub selbst bleibt ohne Adminrechte.

```
python -m bridge.sensors            # Server auf 127.0.0.1:8768
python -m bridge.sensors --list     # alle Rohsensoren auflisten und beenden
```

Pakete: `pip install nvidia-ml-py HardwareMonitor` (psutil ist schon da). Fehlt eines, läuft der Rest weiter.

**Im Alltag** läuft der Helfer nicht aus dem Projektordner, sondern als geplante Aufgabe „Tablet Deck Sensors“
mit Adminrechten aus `%ProgramFiles%\TabletDeck\sensors` (eingerichtet von `install.ps1`, Gründe und Aufbau
in [install.md](install.md#sensor-helfer-pc-werte-mit-adminrechten)):
```
pythonw.exe -I run.py --data <Projektordner>      # run.py ergänzt --installed --presentmon … --log …
```
`--installed` liest den Projektordner nur (config.json, sensors.json, Token), nimmt PresentMon nur aus
`--presentmon` und bricht ohne `secrets/sensors.key` ab. Nach Änderungen an `bridge/sensors` die Kopie mit
`install.ps1` erneuern (`install.ps1 -Check` meldet „veraltet“).

## Quellen

| Quelle | Werte | Braucht |
|---|---|---|
| `psutil` | CPU-Last, RAM, Netzwerk | nichts |
| `nvml` | NVIDIA-Karte: Temperatur, Takte, Lüfter, Leistung, VRAM, Last, PCIe | NVIDIA-Treiber |
| `lhm` | LibreHardwareMonitor (pip-Paket `HardwareMonitor`): Kerntakte, CPU-Temperaturen und -Leistung, Lüfter und Spannungen des Mainboards, weitere GPU-Werte | **Admin** und PawnIO-Treiber |
| `presentmon` | FPS (angezeigt) und Frametime des Spiels | `PresentMon.exe`; **Admin** oder Gruppe „Leistungsprotokollbenutzer“ |

Ohne Adminrechte meldet `lhm` „kein Admin“ und liefert nur, was LHM trotzdem lesen kann (GPU-Werte, CPU-Last je
Kern). Kerntakte, CPU-Temperaturen, CPU-Leistung und alle Mainboard-Sensoren fehlen dann. Ein Fehler in einer
Quelle wird einmal geloggt (`sensors.log`) und unter `sources` gemeldet; die anderen Quellen laufen weiter.

**PresentMon** lädt `install-sensors.ps1` (Konsolenfassung 2.6.0, Prüfsumme und Signatur geprüft). Für den
Start von Hand: `PresentMon-<Version>-x64.exe` von <https://github.com/GameTechDev/PresentMon/releases> als
`tools/presentmon/PresentMon.exe` ablegen oder den Pfad in `config.json` unter `presentmon_exe` eintragen
(gilt nicht im Admin-Betrieb). Fehlt die Datei: Quelle „nicht installiert“.
Gestartet wird PresentMon erst, wenn der Hub ein Ziel setzt (`POST /target`).

## Schnittstelle

Nur `127.0.0.1`, Port aus `config.json` (`sensors_port`, Standard 8768). Jede Anfrage braucht den Kopf
`Authorization: Bearer <Token>`. Das Token steht in `secrets/sensors.key` und wird beim ersten Start erzeugt
(neu erzeugen: Datei löschen und Helfer neu starten). Ohne oder mit falschem Token: 401.

- `GET /values` → `{"time": …, "values": [{"id", "name", "value", "unit", "min", "max"}, …], "sources": {"psutil": "ok", "lhm": "kein Admin", …}}`.
  Abgetastet wird etwa jede Sekunde im Hintergrund, die Anfrage liefert den letzten Stand. IDs ohne aktuellen
  Wert fehlen in der Liste. `min`/`max` sind Skalengrenzen für die Anzeige (oder `null`), keine Messwerte.
- `POST /target` mit `{"pid": 1234}` oder `{"exe": "Spiel.exe"}` setzt das Spiel für PresentMon, `{}` löscht es.
  Bei `pid` endet PresentMon mit dem Spiel, bei `exe` wartet es auf den Prozess.

## IDs

| ID | Quelle | Einheit |
|---|---|---|
| `cpu.load` | psutil | % |
| `ram.used`, `ram.total` | psutil | MB |
| `net.down`, `net.up` | psutil | KB/s |
| `net.total_down`, `net.total_up` | psutil (seit Systemstart) | MB |
| `gpu.temp`, `gpu.load`, `gpu.load.memctl` | nvml, sonst lhm | °C, % |
| `gpu.clock.core`, `gpu.clock.mem` | nvml, sonst lhm | MHz |
| `gpu.fan1`, `gpu.fan2` / `gpu.fan1.pct`, `gpu.fan2.pct` | nvml, sonst lhm | RPM / % |
| `gpu.power` | nvml, sonst lhm | W |
| `gpu.vram.used`, `gpu.vram.total` | nvml, sonst lhm | MB |
| `gpu.pcie.rx`, `gpu.pcie.tx` | nvml, sonst lhm | KB/s |
| `gpu.temp.hotspot`, `gpu.temp.mem`, `gpu.volt.core`, `gpu.load.video` | lhm | °C, V, % |
| `cpu.clock.0` … `cpu.clock.<n-1>` | lhm (Admin), je CPU erzeugt (siehe unten) | MHz |
| `cpu.clock.p0` … `cpu.clock.p7`, `cpu.clock.e8` … `cpu.clock.e11` | lhm (Admin), Alias für den i7-12700K | MHz |
| `cpu.temp.package`, `cpu.temp.core_max` | lhm (Admin) | °C |
| `cpu.power.package` | lhm (Admin) | W |
| `fan.cpu`, `fan.sys1` … `fan.sys3` | lhm (Admin) | RPM |
| `fan.<Baustein>_<Nr>_<Kanal>` (z. B. `fan.it8688e_0_3`) | lhm (Admin), je Board erzeugt | RPM |
| `volt.12v`, `volt.5v`, `volt.3v3`, `volt.dram` | lhm (Admin) | V |
| `fps.displayed`, `fps.frametime` | presentmon | FPS, ms |

Netzwerk: Summe aller verbundenen Schnittstellen ohne Loopback. `gpu.temp.hotspot` gibt es nur, wenn die Karte
den Wert meldet (die RTX 5080 dieses PCs tut es nicht; dafür `gpu.temp.mem`).

## Andere PCs: erzeugte IDs

Die festen IDs oben passen zu diesem PC (Intel i7-12700K, MSI-Board mit NCT6687D, NVIDIA). Auf anderen PCs
leitet der Helfer bei jeder Abtastung zusätzliche IDs aus den Rohsensoren ab (`derive()` in `mapping.py`),
ohne dass `sensors.json` gepflegt werden muss. Quelle der LHM-Namen: der LibreHardwareMonitor-Quelltext
(`IntelCpu.cs`, `Amd17Cpu.cs`, `Amd10Cpu.cs`, `AmdGpu.cs`, `IntelDiscreteGpu.cs`, `IntelIntegratedGpu.cs`,
`SuperIOHardware.cs`).

- **Kerntakte `cpu.clock.<i>`:** LHM-Typ Clock unter `/intelcpu` oder `/amdcpu` mit genau den Namen `P-Core #n`,
  `E-Core #n` (Intel Hybrid) bzw. `Core #n` (Intel klassisch, AMD; „Core #n (Effective)“ und „Cores (Average)“
  zählen nicht). `i` folgt der LHM-Nummer (stabil, auch wenn ein Takt kurz fehlt): `P-Core #n` und `Core #n`
  -> `n-1`, `E-Core #n` -> hinter dem höchsten P-Kern weiter; höchstens 64 Kerne. Das Raster zeigt mit einem
  älteren Helfer ersatzweise die festen IDs `cpu.clock.p0`/`e8` …. Name:
  `P-Kern i`, `E-Kern i`, `Kern i`. Auf dem i7-12700K ist `cpu.clock.0` = `cpu.clock.p0` … `cpu.clock.11` = `cpu.clock.e11`.
  Die alten IDs `cpu.clock.p0` … bleiben als feste Zuordnung bestehen (Alias; `sensors.json` und alte Dashboards
  funktionieren weiter).
- **CPU-Temperatur/-Leistung:** `cpu.temp.package` = Intel „CPU Package“, sonst AMD „Core (Tctl/Tdie)“,
  „Core (Tdie)“, „Core (Tctl)“ (Tdie vor Tctl, weil Tctl bei älteren Ryzen einen Versatz hat), zuletzt „CPU Cores“
  (Amd10). `cpu.temp.core_max` = Intel „Core Max“ bzw. AMD „CCDs Max (Tdie)“ (gibt es nur bei Ryzen mit CCD-Sensor).
  `cpu.power.package` = Intel „CPU Package“ bzw. AMD „Package“.
- **Lüfter:** Die festen IDs (`fan.cpu` = „CPU Fan“, `fan.sys1`–`3` = „System Fan #1–#3“) haben Vorrang. Jeder weitere
  Mainboard-Lüfter (LHM-Typ Fan unter `/lpc`) mit Drehzahl > 0 bekommt `fan.<Baustein>_<Nr>_<Kanal>` aus dem
  LHM-Pfad (`/lpc/it8688e/0/fan/3` → `fan.it8688e_0_3`), den Namen liefert LHM („Chassis Fan #1“, „Pump Fan“ …).
  Steht ein Lüfter, verschwindet seine ID und kehrt unverändert zurück. Umbenennen in `sensors.json`:
  `{"fan.it8688e_0_3": {"label": "Pumpe"}}` (nur `label`, `unit`, `min`, `max`; mit `source`/`path` ersetzt der
  Eintrag die Erzeugung). Rohsensoren, die eine feste oder eigene ID belegt, werden nicht doppelt gelistet.
- **Spannungen:** nur eindeutige Namen. `volt.12v`: „+12V“; `volt.5v`: „+5V“; `volt.3v3`: „+3.3V“,
  „+3.3V (AVCC)“, „+3.3V (3VCC)“, „3VCC“, „VCC3V“; `volt.dram`: „DIMM“, „VDIMM“, „DRAM“. Mehrdeutiges
  („AVCC3“, „Voltage #n“, „DIMM A/B“) bleibt `–`; dann über `--list` in `sensors.json` zuordnen.
- **Grafikkarte:** NVML zuerst, dann LHM `/gpu-nvidia`, `/gpu-amd`, `/gpu-intel` (Arc) und `/gpu-intel-integrated`
  mit deren Namen („GPU Core“, „GPU Memory“, „GPU Fan“ bzw. „GPU Fan n“, „GPU Package“; Intel iGPU „GPU Power“).
  Nicht zugeordnet für AMD/Intel: VRAM, PCIe, Speichercontroller (Einheit der Speicherwerte unklar) - bleibt `–`.

Eigene Einträge in `sensors.json` gewinnen immer gegen erzeugte IDs.

## Zuordnung (`sensors.json`)

Die eingebauten Zuordnungen stehen in `bridge/sensors/mapping.py`. Eine eigene `sensors.json` neben
`config.json` (nicht im Git) überschreibt oder ergänzt sie; Vorlage: `sensors.example.json`.

1. `python -m bridge.sensors --list` **als Administrator** ausführen. Die Tabelle zeigt je Rohsensor Quelle,
   Typ, Name, Wert, Einheit, die zugeordnete ID und den Pfad; darunter den Zustand der Quellen und alle IDs
   ohne Wert.
2. Fehlende oder falsche IDs in `sensors.json` eintragen, entweder über den Pfad
   (`{"source": "lhm", "path": "/lpc/…/fan/2"}`) oder über Name und Typ
   (`{"source": "lhm", "sensor": "System Fan #4", "type": "Fan", "hardware": "/lpc"}`), bei Bedarf mit `factor`.
3. Helfer neu starten.

Noch zu prüfen für das MSI MPG Z690 Edge WiFi DDR4 (Super-I/O NCT6687D), siehe `sensors.example.json`:
- `fan.sys1`–`fan.sys3` sind auf die LHM-Namen „System Fan #1–#3“ gelegt. Ob das den Anschlüssen SYS_FAN1–3
  entspricht, zeigt nur ein Versuch (Lüfter kurz anhalten oder Drehzahl ändern).
- `volt.3v3` hat keinen Standard: LHM kennt bei diesem Baustein keinen Sensor „+3.3V“. Kandidat ist „AVCC3“;
  erst eintragen, wenn der Wert zum BIOS passt.
- Zeigen 12 V/5 V nur einen Bruchteil, fehlt der Spannungsteiler: `factor` ergänzen.

## Hub und Tablet-Seite

`bridge/stats.py` verbindet den Hub mit dem Helfer, `web/stats/` zeigt die Werte (`/stats/`, Dashboard mit
`?d=<name>`; ohne `?d=` das im Editor gewählte Standard-Dashboard, sonst `deck`; der MoBro-Nachbau ist `?d=mobro`).
`web/stats/render.js` (`StatsView`) ist der gemeinsame Zeichenbaustein von `stats.js` und dem Dashboard-Editor
(`web/editor/dash.js`, Reiter „Dashboards“). Die Vorschau im Editor bekommt ihre Live-Werte über den Editor-Kanal
(`dash_sensors`, alle 2 s, mit `min`/`max` der Sensoren), nicht über `/ws` (das braucht die Kopplung).

- **Abo über `/ws`:** Die Seite sendet `{"t":"stats_sub"}` (nach jedem Verbinden) und `{"t":"stats_unsub"}`;
  beim Trennen meldet der Hub sie selbst ab. Nur solange mindestens eine Seite abonniert hat, fragt der Hub
  jede Sekunde `GET /values` ab. Das Token liest er aus `secrets/sensors.key` (nie ins Log).
- **Nachricht an Abonnenten:** `{"t":"stats", "values": {id: Wert}, "sources": {…}, "meta": {id: {name, unit, min, max}}}`.
  `meta` kommt nur beim ersten Mal je Abonnent und wieder, wenn es sich ändert.
- **Rückfall:** Fehlt die Token-Datei, läuft der Helfer nicht oder lehnt er das Token ab, liefert der Hub selbst
  `cpu.load`, `ram.*` und `net.*` (psutil) sowie die NVML-Werte der Grafikkarte (ohne Admin), gleiche
  Einheiten wie der Helfer. `sources` zeigt dann
  `sensord: <Grund>`. Der Helfer wird alle 5 s erneut versucht; geloggt wird nur bei einem Zustandswechsel.
- **Spiel für PresentMon:** Beim Spielwechsel (`bridge.game`) sendet der Hub `POST /target {"exe": "<Name>"}`
  bzw. `{}` ohne Spiel. Der Name stammt aus `games.json` (`exe`) oder aus der Bibliothek (exe-Pfad bzw.
  laufendes Programm im Spielordner); bevorzugt ein gerade laufendes Programm. Ein Fehler stört die
  Spielerkennung nicht; ein neu gestarteter Helfer bekommt das Ziel erneut.
- `GET /api/dashboards` (Liste mit `name`, `title`, `origin`), `GET /api/dashboards/<name>` (geprüftes
  Dashboard, mitgeliefert oder eigen) und `GET /api/dashboards/default` (das gewählte Standard-Dashboard) liefert
  der Hub loopback bzw. nur gekoppelt wie die Profile.

## Dashboard

Datei `<name>.json` (Name: 1 bis 40 Zeichen aus Kleinbuchstaben, Ziffern, `_`, `-`; `default` und Windows-Gerätenamen
wie `con` sind gesperrt). Der Hub prüft sie beim Laden (`bridge/dashboard.py`); eine fehlerhafte Datei erscheint
nicht in der Liste und wird geloggt.

**Mitgeliefert und eigen:** Die mitgelieferten Dashboards (`dashboards/deck.json`, `dashboards/mobro.json`) gehören
zum Projekt, werden bei jedem Update ausgeliefert und sind im Editor schreibgeschützt. „Bearbeiten“ legt eine
eigene Kopie in `dashboards/eigene/` an (Name automatisch frei: `deck-eigen`, `deck-eigen-2`, …). Eigene
Dashboards stehen nicht im Git und nicht im Weitergabe-Paket; Updates überschreiben sie nie. Ein eigener Name darf
nicht wie ein mitgelieferter heißen. Gelöschte eigene Dashboards landen in `dashboards/eigene/.papierkorb/`
(wiederherstellbar: Datei zurückkopieren).

**Standard:** Die Kachel „PC-Werte“ (`/stats/` ohne `?d=`) zeigt das Dashboard `stats_dashboard` aus `config.json`
(vom Editor gesetzt, wirkt ohne Hub-Neustart). Fehlt die Einstellung oder das Dashboard (gelöscht), gilt `deck`;
„zurück zum Standard“ entfernt die Einstellung.

**Editor-Kanal `/edit`** (nach der Token-Anmeldung, Antworten bei Fehlern `{"t":"error","req":…,"msg":…}`):
`dash_list` → `{"t":"dash_list","dashboards":[{name,title,origin}],"default":name}`;
`dash_get {name}` → `{"t":"dash_get",name,origin,dashboard}`; `dash_save {name,dashboard}` (nur eigene, geprüft,
atomar) → `dash_saved`; `dash_create {from?,title?}` (leer 1152×800 oder Kopie) → `dash_created` mit `name`,
`dashboard` und der Liste; `dash_rename {name,to}` → `dash_renamed`; `dash_delete {name}` → `dash_deleted`;
`dash_default {name}` (`name` leer/`null` = zurück auf `deck`) → `dash_default`; `dash_schema` → `{"t":"dash_schema",
"schema":…}` mit Widget-Arten, Feldern, Typen, Grenzen, Auswahlwerten und Pflichtfeldern (dieselbe Quelle wie die
Prüfung, `dashboard.schema()`); `dash_sensors` → `{"t":"dash_sensors","sensors":[{id,name,unit,value}],"sources":…}`
mit den aktuellen Werten. Die Antworten auf Anlegen, Umbenennen, Löschen und Standard enthalten `dashboards` und
`default`.

```json
{"title": "…", "width": 1382, "height": 794, "background": "#323232", "widgets": [ {…}, … ]}
```

`width`/`height` sind die Zeichenfläche in beliebigen Einheiten (100 bis 10000). Die Seite skaliert sie auf die
verfügbare Fläche (Seitenverhältnis bleibt, `meet`). Alle Maße der Widgets liegen in diesen Einheiten.
Widgets werden in Listenreihenfolge gezeichnet (das letzte liegt vorn). Pflicht je Widget: `type`, `x`, `y`,
`w`, `h`; optional `group` (Gruppenname für den Editor, `[a-z0-9_-]{1,20}`, ohne Wirkung auf die Anzeige); bei `value`, `gauge`, `bar`, `line` außerdem `sensor` (ID aus der Tabelle oben), bei `text` `text`.

| `type` | Zeigt | Weitere Felder |
|---|---|---|
| `value` | Beschriftung und Wert mit Einheit (`–` bei fehlendem Wert) | `label`, `label_color`, `unit`, `scale`, `decimals`, `gap` (Abstand Beschriftung–Wert), `size`, `color`, `font`, `weight`, `small_unit` (Einheit klein, fest Gewicht 500 - `weight` gilt dann nur für die Zahl), `align` (ohne `label`: `start`/`center`/`end`) |
| `gauge` | Zeigerbogen (240°) | `min`, `max`, `color`, `track`, `thickness`, `zones`, `ring` (`false`: ohne Außenring, der Bogen färbt sich nach Zone) |
| `bar` | Balken von links | `min`, `max`, `color`, `track`, `radius` |
| `line` | Verlauf der letzten `seconds` (Standard 60) mit Höchst-/Tiefstwert links | `seconds`, `min`/`max` (sonst automatisch), `color`, `area` (Füllfarbe unter der Linie), `axis` (`false`: ohne Achsenwerte), `label_color`, `size`, `thickness`, `unit`, `decimals` |
| `text` | fester Text | `text`, `color`, `size`, `font`, `weight`, `align` |
| `clock` | Uhrzeit | `format` (Standard `HH:mm:ss`), `color`, `size`, `font`, `align` (Standard `center`) |
| `date` | Datum | `format` (Standard `DD-MM-YYYY`), sonst wie `clock` |
| `rect` | Rechteck (Karte) | `fill`, `stroke`, `stroke_width`, `radius` |
| `hline` | waagerechte Linie (mittig in `h`) | `color`, `thickness` |
| `cores` | Raster aller vorhandenen `cpu.clock.<n>`: Beschriftung (`P0`, `E8`, `K0`), Takt, Balken - so viele Zellen wie der Hub meldet. Ohne `sensor` | `columns` (Standard 6; bei vielen Kernen mehr, höchstens 16), `row_h` (52), `gap` (10), `size` (15), `label_size` (12), `scale`, `decimals`, `unit` (Standard leer), `min`/`max` der Balken (0 / 5500), `color` (Balken), `color_e` (Balken der E-Kerne), `track`, `label_color`, `text_color`, `weight` |
| `fans` | Liste aller vorhandenen `fan.*` mit Name (aus dem Helfer) und Drehzahl, Trennlinie zwischen den Zeilen. Ohne `sensor` | `row_h` (48; passen nicht alle in `h`, rücken die Zeilen zusammen), `size` (18), `label_size` (13), `unit` (`U/min`), `decimals`, `color`, `label_color`, `separator`, `weight` |

- **Anzeigewert:** `Wert × scale` (Standard 1), `decimals` Nachkommastellen (ohne Angabe 0 ab 100, sonst 1),
  Einheit `unit`, sonst die des Sensors. Die Werte des Hubs sind schon in MHz, MB, KB/s usw.
- **Grenzen** von `gauge`/`bar`: `min`/`max` des Widgets, sonst `min`/`max` des Sensors (`meta`), sonst 0 bis 100.
- **`zones`** (Zeiger): `[{"from": 0.75, "color": "#ff9a00"}]` - ab diesem Anteil der Skala färbt sich der dünne
  Außenring; ohne Angabe bleibt er in `color`.
- **Farben:** `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb(…)`/`rgba(…)`, `none`, `transparent`.
- **`font`:** `sans` (Standard), `mono`, `head` (Schriften aus `web/lib`). **`size`** ist die Schrifthöhe.
- **Zeit-`format`:** Platzhalter `YYYY`, `MM`, `DD`, `HH`, `mm`, `ss` (Monat `MM`, Minute `mm`).
- Fehlende oder länger als 4 s nicht aktualisierte Werte erscheinen als `–`. `cores` und `fans` zeigen nur, was
  der Hub gerade meldet; ohne Werte bleiben sie leer.

### Dashboard „deck“

`dashboards/deck.json` (Standard) ist das eigene Design im Stil des Tablet Deck: Karten für CPU, GPU, FPS,
Arbeitsspeicher/Netz und Mainboard, Fläche 1152×800 (Tablet ohne Leiste). Kerntakte (`cores`) und Lüfter (`fans`)
passen sich dem PC an; mehr als 32 Kerne zeigt das Raster nicht. Erzeugt mit
`python scripts/make_deck_dashboard.py` - Änderungen am Layout dort vornehmen und neu erzeugen.

### MoBro-Dashboard übernehmen

`python scripts/mobro_import.py [Dashboard.json] [--info …metric-information.json] [--out dashboards/mobro.json]`
wandelt ein Dashboard aus dem MoBro-Datenordner (`%APPDATA%\mobro-data\dashboards\<uuid>.json`) um. Die
MoBro-IDs sind undurchsichtig; die Beschriftung und den Typ jeder Metrik nennt die Datei
`dashboards-metadata/<uuid>.metric-information.json` (liegt neben dem Dashboard-Ordner, wird automatisch
gefunden). Die Zuordnung (Beschriftung, Typ) → Sensor-ID steht als Tabelle `METRICS` im Skript. Was dort nicht
steht, wird gemeldet und nicht übernommen, ebenso Bilder. Abgelesen aus dem MoBro-Screenshot und daher
geschätzt: Zonen und Farben der Zeiger.
