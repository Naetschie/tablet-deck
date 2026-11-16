# Tablet-Setup: Lenovo Tab M10 HD (TB-X505F) → LineageOS-GSI

Protokoll aller Schritte am Tablet, damit sie sich wiederholen lassen.
Downloads liegen in `tools/firmware/` (nicht im Git).

## Ausgangszustand (2026-11-12)
| | |
|---|---|
| Modell | TB-X505F (EEA), SoC msm8937/SDM429, 2 GB RAM, Kernel 4.9.205 |
| Firmware | `TB-X505F_S001149_221115_ROW`, Android 10 (QKQ1.191224.003) |
| Partitionen | A-only, system-as-root, Treble ja, VNDK 29. `system` ≈ 3,9 GiB, `vendor` ≈ 1,5 GiB |
| Bootloader | gesperrt, OEM-Entsperrung in Entwickleroptionen **an** (`sys.oem_unlock_allowed=1`) |
| Akku | ca. 75 % Restkapazität (Schätzung aus Ladezähler) |

## Gewählt
- **System:** LineageOS 23.2 GSI (Android 16), MisterZtr, Variante **VANILLA-EXT4** (ohne Google).
  EROFS geht nicht (braucht Kernel ≥ 5.4, VNDK 29 dort entfernt).
  Quelle: https://github.com/MisterZtr/LineageOS_gsi/releases
- **vbmeta:** selbst erzeugt mit `scripts/make_vbmeta_disabled.py` (leer, flags=3 = Prüfung aus).
- **Kein TWRP nötig:** Flashen per `fastboot` aus dem Bootloader. Root später über LineageOS
  „Rooted debugging“ → Boot-Partition auslesen → mit Magisk patchen → flashen.
- **WLAN egal:** Das Tablet läuft über USB (`adb reverse`), deshalb ist das „permissive boot“-Image
  aus dem XDA-Thread (WLAN-Fix für X505F) nicht nötig.
- **Rettungsweg:** Stock-Firmware über Lenovo Rescue and Smart Assistant (LMSA) bzw. QPST-Paket
  `USR_S001149_2211151142_Q00015_ROW_QPST`. Fastboot bleibt nach dem Entsperren immer erreichbar.

## Vorab-Prüfungen (erledigt)
- ABI: `ro.product.cpu.abilist=arm64-v8a,armeabi-v7a,armeabi`, `app_process64` vorhanden → **arm64**
  (kein 32-Bit-Userspace, also die normale arm64-GSI). `ro.vndk.lite` leer → keine vndklite-Variante.
- `first_api_level=28` (Launch mit Android 9) → Legacy-SAR, LK-Bootloader (aboot).
- VNDK 29: Die EXT4-Variante behält VNDK 28/29 (nur bei EROFS entfernt, siehe Release-Notes). Dass
  LineageOS 23 auf Kernel 4.9 läuft, zeigt die XDA-Anleitung für das baugleiche X505X.

## Rückweg (vor dem Flashen bereitlegen)
- Stock-Firmware-Paket (QPST) entpacken und griffbereit halten: `vbmeta.img`, `boot.img`,
  `recovery.img`, `system.img` (ggf. Sparse-Teile), `vendor.img`, Firehose `prog_emmc_firehose_8937*.mbn`.
- Fastboot ist nach dem Entsperren immer erreichbar (Leiser + Power, auch im Bootloop).
  Rückfall: `fastboot flash vbmeta|boot|system …` aus dem Paket, dann `fastboot -w`.
- Letzter Ausweg: EDL (9008) mit QFIL + Firehose (`adb reboot edl` / `fastboot oem edl`).
  LMSA verweigert entsperrte Geräte teils – nicht allein darauf verlassen.
- Ersatz-GSI bereithalten (ältere LineageOS-GSI, Android 14/15), falls 23.2 nicht startet.

## Ablauf Phase 1 (löscht das Tablet)
```
adb reboot bootloader
fastboot oem unlock-go                     # alternativ: fastboot flashing unlock; am Tablet mit Lauter bestätigen
# Tablet setzt zurück und startet neu → wieder in den Bootloader (Leiser + Power)
fastboot getvar unlocked                   # muss "yes" sein
fastboot getvar partition-size:system      # >= Größe des GSI-Images
fastboot --disable-verity --disable-verification flash vbmeta <stock>/vbmeta.img
#   (Stock-vbmeta bevorzugt, behält Cmdline-Deskriptoren; Rückfall: tools/firmware/vbmeta_disabled.img)
fastboot flash system tools/firmware/gsi/<LineageOS…VANILLA-EXT4>.img
fastboot -w                                # userdata + cache formatieren
fastboot reboot
```
Bootloader danach **nie wieder sperren** (würde mit fremdem System nicht mehr starten).
Bootloop → `adb logcat` beobachten (adb läuft in GSIs früh), sonst Rückweg oben.

Danach:
1. Einrichtung überspringen, Entwickleroptionen an, USB-Debugging + **Rooted debugging** an.
2. `adb root` → Sicherungen ziehen (`boot`, `recovery`, `persist`, `modemst1/2`, `fsg`).
3. Magisk-APK installieren. **Ramdisk-Status in der App prüfen:** Legacy-SAR hat oft keinen Ramdisk
   in `boot` → dann `recovery.img` patchen („Magisk in Recovery“, Start über Recovery-Tasten);
   sonst `boot.img` patchen und `fastboot flash boot magisk_patched.img`.
4. ACC (Magisk-Modul): Ladegrenze 45–55 %.
5. `fastboot oem off-mode-charge 0` testen (Start beim Anstecken).

## Downloads (in `tools/firmware/`)
| Datei | SHA-256 | Prüfung |
|---|---|---|
| `gsi/LineageOS-23.2-20260524-VANILLA-EXT4-GSI.7z` (→ `.img`, 2 733 260 800 B, ext4) | `4eba2022…c54c2da` | Quelle GitHub/SourceForge, keine Signatur |
| `stock/stock_S001149.zip` (inoffiziell: addrom.com → Google Drive, `TB-X505F_USR_S001149_2211151142_Q00015_ROW`) | `a87df901…8ac49023` | siehe unten |

**Echtheit des Stock-Pakets** mit `scripts/verify_stock.py`: `sha256(vbmeta.img)` ==
`ro.boot.vbmeta.digest` des noch gesperrten Tablets (`6f45e616…62b2ec07`), d. h. genau das vbmeta,
das der Bootloader mit Lenovos Schlüssel geprüft hat. Dessen Deskriptoren bestätigen
`boot`, `dtbo`, `recovery` (SHA-256) sowie `system`, `vendor` (dm-verity-Hashtree, SHA-1) → **alle OK**.
Die QPST-Programme im Paket wurden nicht ausgeführt; nur der Ordner `image/` ist entpackt.

**Nicht abgedeckt** (nicht per vbmeta geprüft): sbl1, tz, rpm, emmc_appsboot, NON-HLOS, Firehose u. a.
(signiert → prüft die Qualcomm-Secure-Boot-Kette in Hardware) sowie die **gerätespezifischen**
Partitionen `persist`, `modemst1/2`, `fsg` (Kalibrierung, MACs). Vor einem QFIL-Vollflash
`rawprogram*.xml` prüfen und diese ausnehmen bzw. die Sicherungen vom Gerät zurückspielen.

## Ergebnis Phase 1 (2026-11-12)
- Entsperren: `fastboot oem unlock-go` → Werksreset → Gerät startet in die Einrichtung (nicht in
  Fastboot), danach per Leiser + Power zurück in Fastboot.
- **Windows-Treiber:** Im Fastboot-Modus meldet sich das Tablet als `USB\VID_18D1&PID_D00D`. Der Google-
  USB-Treiber (r13) kennt diese ID nicht → im Geräte-Manager über „Datenträger…“ `android_winusb.inf`
  wählen und **„Android Bootloader Interface“** erzwingen.
- **fastboot 37.0.1 stürzt** beim System-Image mit `std::bad_alloc` ab (auch mit `-S`). **fastboot
  r33.0.3** (`tools/pt33/`) funktioniert und teilt das Image selbst in 6 Sparse-Teile.
- vbmeta: Stock-`vbmeta.img` mit `--disable-verity --disable-verification`.
- **Erster Start: Bootschleife am Lenovo-Logo.** Ursache war SELinux enforcing. Behoben mit
  `scripts/patch_boot_cmdline.py`: Stock-`boot.img` (Header v1, ohne Ramdisk, Legacy-SAR mit
  `skip_initramfs`) plus `androidboot.selinux=permissive` → `tools/firmware/custom/boot_permissive.img`.
  Zuerst per `fastboot boot` getestet, dann mit `fastboot flash boot` dauerhaft geflasht.
- Läuft: LineageOS 23.2 (Android 16, userdebug), SELinux Permissive, Start etwa 60 s,
  etwa 760 MB RAM frei.

## Phase 1b: Root und Akku (geplant)
1. Rooted debugging an → `adb root` → Sicherungen von `persist`, `modemst1/2`, `fsg`, `boot`,
   `recovery`, `vbmeta` nach `tools/firmware/backup/`.
2. Magisk: **`boot_permissive.img`** patchen (magiskboot erhält die cmdline und ersetzt bei Legacy-SAR
   `skip_initramfs` → `want_initramfs`). **Erst `fastboot boot magisk_patched.img` testen**, dann flashen.
   Rückweg: `fastboot flash boot tools/firmware/custom/boot_permissive.img`.
   Klappt das nicht, ginge Magisk in recovery. Für ein Panel, das unbeaufsichtigt startet, taugt das
   aber nicht (Root nur beim Start über die Recovery-Tasten). Dann bräuchte die Ladegrenze einen
   anderen Weg (init-Skript).
3. ACC: Ladegrenze 45–55 %, danach am Gerät nachprüfen.
4. SELinux zurück auf **enforcing**. Die Bootschleife kam von enforcing insgesamt, nicht nur von WLAN.
   Deshalb:
   1. Im permissive-Betrieb **alle** Ablehnungen sammeln (`dmesg | grep avc`,
      `logcat -b all | grep avc:`), nach einem kompletten Start und nach WLAN-Nutzung.
   2. Daraus eine Magisk-`sepolicy.rule` bauen.
   3. Die cmdline per Skript auf `androidboot.selinux=enforcing` setzen und daraus die Magisk-Version
      neu patchen.
   4. **Erst per `fastboot boot` testen.** Rückweg ist das permissive Magisk-Image.
   Bis dahin auf dem Tablet nur eigene Seiten laden, nicht frei surfen (permissive hebelt die Sandbox
   der WebView aus).

Hinweis Magisk-App: Ohne Ramdisk im boot bietet die App die Option „Recovery Mode“ an. Für das
Patchen von boot muss sie **aus** sein.

## Ergebnis Phase 1b (2026-11-12)
- **Sicherungen** (Root-ADB, `adb exec-out cat /dev/block/bootdevice/by-name/<p>`) in
  `tools/firmware/backup/` mit `SHA256SUMS`: persist, modemst1/2, fsg, fsc, boot, recovery, vbmeta,
  dtbo, devinfo, misc. Plausibel: boot == boot_permissive, recovery == Stock.
- **Magisk 31.1** (APK-SHA256 = GitHub-Release-Digest `89cefac0…`). Gepatcht auf dem Gerät mit Magisks
  eigenem `boot_patch.sh` und `LEGACYSAR=true` (Ramdisk hinzu, `skip_initramfs` → `want_initramfs`,
  cmdline bleibt) → `tools/firmware/custom/boot_permissive_magisk.img`. Erst per `fastboot boot`
  getestet, dann geflasht.
  - Stolperstein: Ohne App-Einrichtung fehlt `/data/adb/magisk` („Magisk environment incomplete“,
    Module laufen nicht). Lösung: die Binärdateien und `util_functions.sh` aus der APK dorthin kopieren.
  - `su` aus der ADB-Shell wird abgelehnt (uid 2000). Stattdessen `adb root` nutzen (Rooted debugging).
  - Git-Bash wandelt `/data/...`-Pfade in Windows-Pfade um, deshalb adb-push über PowerShell.
- **Akku:** `battery_charging_enabled=0` → „Not charging“, Strom 0, das Tablet läuft vom USB-Strom
  (Akku wird weder geladen noch entladen). Eigenes Magisk-Modul `tablet/chargectl/` (statt ACC):
  Hysterese 45–55 %, ab 45 °C nie laden, Konfiguration `/data/adb/chargectl.conf` (nur MIN/MAX/TEMP_MAX/INTERVAL, geprüft), Wakelock beim Laden, LineageOS-Ladesteuerung aus lassen, Log
  `/data/adb/chargectl.log`. Installation: `tablet/install-module.ps1 tablet/chargectl/module -Reboot`.
  Akku-Zustand: `charge_full` 4982 mAh, 10 Zyklen (die frühere Schätzung von etwa 75 % war falsch).
- Bildschirm/Gerät bleibt an jeder Stromquelle wach (`svc power stayon true` = `stay_on_while_plugged_in 15`, AC+USB+kabellos+Dock, setzt auch die Bridge) - verhindert Laden im Suspend über MAX hinaus.
- **Uhrzeit:** Die Bridge setzt beim Verbinden und danach stündlich Zeit und Zeitzone
  (`cmd alarm set-time/set-timezone`, geht ohne Root, `tablet_timezone` in config.json).
  Zeitsprünge lassen die ADB-Freigabe „ablaufen“ → `settings put global adb_allowed_connection_time 0`.
- **Start beim Einstecken:** `fastboot oem off-mode-charge 0`. Getestet: Ausschalten am USB
  (`reboot -p`) → nach etwa 45 s startet das Tablet von selbst wieder.
- **SELinux enforcing (vertagt):** 241 Regeln aus den Ablehnungen im permissive-Betrieb
  (`scripts/avc2rule.py` → Magisk-Modul `tablet/selinux-fix`, Installation über
  `tablet/install-module.ps1`, schreibt auch die Preinit-Datei `sepolicy.rule`). Das
  enforcing-Image `boot_enforcing_magisk.img` startet (nur `fastboot boot`), aber `adb root` lässt
  danach die USB-Verbindung verschwinden. Ablehnungen von adbd und su fehlen noch. Vorerst bleibt
  das Tablet **permissive**; Ausgleich: Die WebView des Launchers lädt nur localhost bzw. den
  gekoppelten Hub, fremde Seiten nur in einer abgeschotteten Ansicht ohne JS-Schnittstelle.


## Härtung (2026-11-12)
Lauschende Sockets nach dem Start (`netstat -ltnup`):
- `127.0.0.1:1528/tcp` → `ptt_socket_app` (Dienst `ptt_wlan`, root, **u:r:init**), ein Qualcomm-WLAN-Test
  aus Lenovos Fabriktest. `init.qcom.rc` startet ihn `on property:sys.boot_completed=1`.
- `0.0.0.0:8080/udp` → `cnss-daemon` (wcnss_service), wird für WLAN gebraucht.

Magisk-Modul `tablet/hardening`: stoppt nach `boot_completed` die Dienste `ptt_wlan` und `ftmd_bt`
(beide oneshot, bleiben aus), Chain `deck_in`: auf `wlan+` nur ESTABLISHED/RELATED, alles Neue
DROP (iptables + ip6tables). Danach lauscht nur noch `cnss-daemon`, abgeschirmt durch die Firewall.

Aus den SELinux-Regeln **gestrichen** (`tablet/selinux-fix/exclude.txt`): init → vendor_file
execute / tcp_socket / port / node (Netzwerkdienst ohne Domänenwechsel) und alle Zugriffe auf
`diag_device` (Qualcomm-Diagnose, Modem/NV). Es bleiben 227 Regeln, keine davon für App-Domains.
Hinweis: Die Preinit-Datei `sepolicy.rule` baut nur `install-module.ps1` neu. Wird ein Modul über
die Magisk-App entfernt, das Skript erneut laufen lassen.

## spacedesk (Zweitbildschirm per USB, 2026-11-12)
- PC: `winget install Datronicsoft.SpacedeskDriver.Server` (2.2.35, UAC). In der „spacedesk DRIVER
  Console“ unter Communication Interfaces **„USB Cable Android“** einschalten (Registry danach
  `HKLM\SOFTWARE\datronicsoft\spacedesk\Service\AndroidUsbControlEnabled = 1`). Per UI-Automation
  allein reicht nicht, die Konsole reagiert nur auf einen echten Klick.
- Tablet: `ph.spacedesk.beta` 2.1.40 als XAPK (Basis + 3 Splits, APKPure), jedes Teil mit `apksigner`
  geprüft: Zertifikat `CN=Mark Neil Templonuevo, OU=datronicsoft Inc`, SHA-256 `69572e37…aa8c48`
  = Fingerabdruck auf APKMirror. Installation `adb install-multiple`.
- Ablauf: Steht das Tablet auf MTP+ADB, schaltet der spacedesk-Treiber es in den USB-Zubehör-Modus
  (`accessory,adb`, ADB bleibt nutzbar). Einmalig fragt Android nach der USB-Berechtigung. Danach
  öffnet die Launcher-Kachel „Bildschirm“ den Windows-Desktop ohne weitere Abfrage.
- Im reinen ADB-Modus (nach einem Tablet-Neustart) macht der Treiber nichts. Die Bridge stellt beim
  Verbinden deshalb `svc usb setFunctions mtp` ein (config `spacedesk_usb`, Standard an).
  Nebenwirkung: Das Tablet taucht im Windows-Explorer als MTP-Gerät auf („Lenovo TB-X505F“). Das ist
  gewollt; wer spacedesk nicht nutzt, setzt `"spacedesk_usb": false` in `config.json`.
- Beim Wechsel MTP → Zubehör meldet sich das Tablet kurz neu am USB an. Die Bridge richtet ein Tablet
  erst nach mehr als 15 s Abwesenheit wieder komplett ein, sonst würde der HOME-Start spacedesk verdrängen.

## Log
- 2026-11-12: Ausgangszustand erfasst, OEM-Entsperrung aktiviert, GSI geladen, vbmeta erzeugt.
- 2026-11-12: Stock-Paket S001149 geladen und gegen das Gerät verifiziert (alle Images OK).
