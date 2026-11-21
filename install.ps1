# Tablet Deck - Einrichtung in einem Schritt (PC, optional Tablet). Mehrfach ausführbar.
# Anleitung: docs\install.md
#
#   .\install.ps1                 PC einrichten + Tablet, falls per USB verbunden
#   .\install.ps1 -SkipTablet     nur PC
#   .\install.ps1 -Modules        zusätzlich Magisk-Module aufs Tablet (Akku, Härtung), danach Neustart
#   .\install.ps1 -Companion      Begleit-Modus (Tablet ohne Root): Launcher als normale App, nicht als
#                                 Startbildschirm; setzt tablet_mode in config.json (ohne Schalter unverändert)
#   .\install.ps1 -SkipSpacedesk  ohne Zweitbildschirm (kein Treiber, kein MTP-Umschalten)
#   .\install.ps1 -SkipSensors    ohne Sensor-Helfer (PC-Werte dann nur Grundwerte, keine UAC-Abfrage)
#   .\install.ps1 -Check          nur prüfen und melden, was fehlt (ändert nichts)
#   .\install.ps1 -AllowLocalChanges  Sensor-Helfer auch mit nicht eingecheckten Änderungen einrichten
#   .\install.ps1 -Apk <Pfad>     diese Launcher-APK installieren (z. B. tablet-deck.apk aus den GitHub-Releases)
#   .\install.ps1 -ListDevices    angesteckte Android-Geräte mit Seriennummer und Modell anzeigen (ändert nichts)
#   .\install.ps1 -Serial <Nr>    nur dieses Gerät einrichten (weiteres Gerät, mehrere angesteckt). Sind mehrere
#                                 angesteckt und fehlt -Serial, fragt das Skript, welches. Mit -Companion gilt der
#                                 Begleit-Modus dann nur für dieses Gerät (tablet_modes in config.json)
#
# Was passiert (PC):
#   1. Python prüfen (>= 3.11; fehlt es: per winget bzw. python.org installieren - für alle Benutzer mit
#      UAC-Abfrage, mit -SkipSensors nur für diesen Benutzer), Abhängigkeiten installieren (pip --user)
#   2. adb (Android platform-tools) nach tools\platform-tools laden, falls nicht vorhanden
#   3. spacedesk-Treiber per winget + "USB Cable Android" einschalten (UAC-Abfrage)
#   4. Autostart (geplante Aufgabe "Tablet Deck Bridge") einrichten und Bridge starten
#   4b. Sensor-Helfer: PawnIO-Treiber (winget), Kopie nach %ProgramFiles%\TabletDeck\sensors, PresentMon,
#       geplante Aufgabe "Tablet Deck Sensors" mit höchsten Rechten (UAC, scripts\install-sensors.ps1)
# Tablet (falls verbunden, USB-Debugging erlaubt):
#   5. Launcher-App: -Apk <Pfad>, sonst bauen (nur wenn JDK/SDK in tools\ liegen), sonst die schon aus dem
#      Release geladene, wenn ihre Version passt, sonst aus dem GitHub-Release der Projektversion laden, sonst
#      (offline) eine vorhandene android\build\tablet-deck.apk mit Warnung; installieren,
#      als Startbildschirm setzen und mit dem PC koppeln (tablet\setup-launcher.ps1)
#   6. optional Magisk-Module
#   7. Smoke-Test gegen die laufende Bridge
param([switch]$SkipTablet, [switch]$SkipSpacedesk, [switch]$SkipAutostart, [switch]$SkipSensors, [switch]$Modules,
      [switch]$Companion, [switch]$Check, [switch]$AllowLocalChanges, [string]$Apk, [string]$Serial,
      [switch]$ListDevices)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
. (Join-Path $root "scripts\install-helpers.ps1")
# -Apk relativ zum Aufrufort auflösen (gleich danach wechselt das Skript in den Projektordner)
if ($Apk) {
    if (-not (Test-Path -LiteralPath $Apk -PathType Leaf)) { throw "APK nicht gefunden: $Apk" }
    $Apk = (Resolve-Path -LiteralPath $Apk).Path
}
# Downloads (adb, Python, APK): TLS 1.2 auch unter Windows PowerShell 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
# Ausgaben von Python (Smoke-Test) als UTF-8 lesen - sonst "w³rde" statt "würde" (Windows PowerShell 5.1)
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
Set-Location $root

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "   ok: $t" -ForegroundColor Green }
function Warn($t) { Write-Host "   !  $t" -ForegroundColor Yellow }

# Externe Programme: stderr nicht als Abbruch werten (PS 5.1), Exit-Code selbst prüfen
function Run {
    $ErrorActionPreference = "Continue"
    $exe = $args[0]
    # immer ein Array: "$exe, $rest = $args" macht aus EINEM Argument einen String, den @rest
    # zeichenweise splattet (adb d e v i c e s)
    $rest = @($args | Select-Object -Skip 1)
    $out = & $exe @rest 2>&1
    [pscustomobject]@{ Code = $LASTEXITCODE; Out = ($out | Out-String).Trim() }
}

$sensorsDest = Join-Path $env:ProgramFiles "TabletDeck\sensors"

# Sensor-Helfer abfragen (Token aus secrets\sensors.key, nie ausgeben). Ergebnis: Quellen-Status oder $null
function Get-SensorSources {
    $key = Join-Path $root "secrets\sensors.key"
    if (-not (Test-Path $key)) { return $null }
    $tok = "$(Get-Content $key -Raw)".Trim()
    if (-not $tok) { return $null }
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:8768/values" -Headers @{ Authorization = "Bearer $tok" } -TimeoutSec 3
        return $r.sources
    } catch { return $null }
}

# Installierte Kopie gleich dem Repo? (sonst install.ps1 erneut ausführen)
function Test-SensorCopy {
    # dieselbe feste Liste wie in scripts\install-sensors.ps1 ($SensorFiles)
    $files = "__init__.py", "__main__.py", "collector.py", "lhm_src.py", "mapping.py", "nvml_src.py",
             "presentmon_src.py", "psutil_src.py", "server.py"
    $pairs = @($files | ForEach-Object {
        ,@((Join-Path $root "bridge\sensors\$_"), (Join-Path $sensorsDest "app\bridge\sensors\$_")) })
    $pairs += ,@((Join-Path $root "scripts\sensors-run.py"), (Join-Path $sensorsDest "run.py"))
    $pairs += ,@((Join-Path $root "bridge\sensors\requirements.txt"), (Join-Path $sensorsDest "requirements.installed.txt"))
    foreach ($p in $pairs) {
        if (-not (Test-Path $p[1])) { return $false }
        if ((Get-FileHash $p[0]).Hash -ne (Get-FileHash $p[1]).Hash) { return $false }
    }
    return $true
}

if ($Check) {
    $missing = 0
    function Need($ok, $good, $bad) { if ($ok) { Ok $good } else { Warn $bad; $script:missing++ } }
    Step "Prüfung (ändert nichts)"
    $py = Find-Python
    if ($py -and (Run $py -c "import websockets, pycaw").Code -ne 0) { $py = $null }
    Need $py "Python mit Abhängigkeiten: $py" "Python >= 3.11 mit requirements.txt fehlt - install.ps1 ausführen"
    Need (Test-Path (Join-Path $root "tools\platform-tools\adb.exe")) "adb vorhanden" "adb fehlt - install.ps1 ausführen"
    Need (Get-ScheduledTask -TaskName "Tablet Deck Bridge" -ErrorAction SilentlyContinue) "Autostart 'Tablet Deck Bridge'" "Autostart fehlt - install.ps1 ausführen"
    Need (@(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object CommandLine -match '-m bridge( |$)').Count -gt 0) "Bridge läuft" "Bridge läuft nicht - Start-ScheduledTask -TaskName 'Tablet Deck Bridge'"
    if (-not $SkipSpacedesk) {
        Need (Get-Service spacedeskService -ErrorAction SilentlyContinue) "spacedesk-Treiber" "spacedesk-Treiber fehlt - install.ps1 ausführen oder -SkipSpacedesk"
    }
    if (-not $SkipSensors) {
        Need (Get-CimInstance Win32_SystemDriver -Filter "Name='PawnIO'" -ErrorAction SilentlyContinue) "PawnIO-Treiber" "PawnIO fehlt (Kerntakte/Temperaturen/Mainboard) - install.ps1 ausführen oder: winget install -e --id namazso.PawnIO"
        $task = Get-ScheduledTask -TaskName "Tablet Deck Sensors" -ErrorAction SilentlyContinue
        $taskOk = $task -and $task.Principal.RunLevel -eq "Highest" -and $task.Actions.Count -eq 1 -and
            $task.Actions[0].Execute -like "*\pythonw.exe" -and
            $task.Actions[0].Arguments -like "-I `"$sensorsDest\run.py`" --data *"
        Need $taskOk "Aufgabe 'Tablet Deck Sensors' (höchste Rechte, startet $sensorsDest\run.py)" "Sensor-Helfer nicht (richtig) eingerichtet - install.ps1 ausführen (UAC-Abfrage)"
        Need (Test-SensorCopy) "Kopie in $sensorsDest aktuell" "Kopie in $sensorsDest fehlt oder ist veraltet - install.ps1 erneut ausführen"
        $src = Get-SensorSources
        Need $src "Sensor-Helfer antwortet" "Sensor-Helfer antwortet nicht - Log: $sensorsDest\logs\sensors.log"
        if ($src) {
            Need ($src.lhm -eq "ok") "LibreHardwareMonitor: ok" "LibreHardwareMonitor: $($src.lhm)"
            Need ($src.presentmon -ne "nicht installiert") "PresentMon: $($src.presentmon)" "PresentMon: $($src.presentmon)"
        }
        if (-not (Test-Path (Join-Path $root "sensors.json"))) {
            Warn "keine sensors.json - Standardzuordnung (MSI/NCT6687D). Andere Boards: python -m bridge.sensors --list (docs\sensors.md)"
        }
    }
    if (-not $SkipTablet) {
        $adbExe = Join-Path $root "tools\platform-tools\adb.exe"
        if (Test-Path $adbExe) {
            $dev = @((Run $adbExe devices).Out -split "`r?`n" | Where-Object { $_ -match '^\S+\tdevice$' })
            if ($dev.Count -eq 1) {
                $one = @("-s", ($dev[0] -split "`t")[0])   # daneben evtl. ein Gerät "unauthorized"/"offline"
                Need ((Run $adbExe @one shell pm list packages app.tabletdeck.launcher).Out -match "app.tabletdeck.launcher") "Launcher auf dem Tablet" "Launcher fehlt auf dem Tablet - install.ps1 ausführen"
                Need ((Run $adbExe @one shell appops get app.tabletdeck.launcher WRITE_SETTINGS).Out -match "allow") "Launcher darf die Ausrichtung halten" "WRITE_SETTINGS fehlt - tablet\setup-launcher.ps1 ausführen"
            } else { Warn "kein (oder mehr als ein) Tablet per USB - Tablet-Prüfung übersprungen" }
        }
    }
    Write-Host ""
    if ($missing) { Write-Host "$missing Punkt(e) offen." -ForegroundColor Yellow; exit 1 }
    Write-Host "Alles eingerichtet." -ForegroundColor Green
    exit 0
}

$adb = Join-Path $root "tools\platform-tools\adb.exe"
# Angesteckte Android-Geräte: Seriennummer, Zustand, Modell, ob der Launcher schon installiert ist
function Get-AdbDevices {
    @((Run $adb devices).Out -split "`r?`n" | Where-Object { $_ -match '^\S+\t(device|unauthorized|offline)$' } |
        ForEach-Object {
            $s, $st = $_ -split "`t"
            $model, $has = "", ""
            if ($st -eq "device") {
                $model = "$((Run $adb -s $s shell getprop ro.product.model).Out)".Trim()
                $has = if ((Run $adb -s $s shell pm path app.tabletdeck.launcher).Out -match "package:") { "ja" } else { "nein" }
            }
            [pscustomobject]@{ Seriennummer = $s; Zustand = $st; Modell = $model; Launcher = $has }
        })
}
function Show-AdbDevices($list) {
    $i = 0
    $list | ForEach-Object {
        $i++
        Write-Host ("   {0}) {1,-20} {2,-12} {3,-22} Launcher: {4}" -f $i, $_.Seriennummer, $_.Zustand, $_.Modell, $_.Launcher)
    }
}
if ($ListDevices) {
    # nur anzeigen: vor Python/Abhängigkeiten, ändert nichts
    if (-not (Test-Path $adb)) { Warn "adb fehlt noch - erst .\install.ps1 ausführen (lädt die platform-tools)"; exit 1 }
    Step "Angesteckte Geräte"
    $list = Get-AdbDevices
    if (-not $list) { Warn "kein Android-Gerät per USB gefunden (USB-Debugging an? Dialog am Gerät bestätigt?)" }
    else { Show-AdbDevices $list; Write-Host "`n   Einrichten: .\install.ps1 -Serial <Seriennummer> [-Companion]" }
    exit 0
}

# ---------------------------------------------------------------- 1. Python
Step "Python"
$python = Find-Python
if (-not $python) {
    # Der Sensor-Helfer läuft mit Adminrechten und braucht ein Python, das nur Admins ändern können
    Install-Python -Machine:(-not $SkipSensors)
    $python = Find-Python
    if (-not $python) {
        throw "Python 3.11 oder neuer nicht gefunden. Von Hand: winget install -e --id Python.Python.3.13 - danach neues Terminal öffnen und install.ps1 erneut starten."
    }
    Ok "Python installiert"
}
Ok $python
$r = Run $python -m pip install --user --disable-pip-version-check -q -r (Join-Path $root "requirements.txt")
if ($r.Code -ne 0) { throw "pip install fehlgeschlagen:`n$($r.Out)" }
Ok "Abhängigkeiten installiert (requirements.txt)"

# ---------------------------------------------------------------- 2. adb
Step "adb (Android platform-tools)"
$adb = Join-Path $root "tools\platform-tools\adb.exe"
if (-not (Test-Path $adb)) {
    $zip = Join-Path $env:TEMP "platform-tools-windows.zip"
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest "https://dl.google.com/android/repository/platform-tools-latest-windows.zip" -OutFile $zip -UseBasicParsing
    New-Item -ItemType Directory -Force (Join-Path $root "tools") | Out-Null
    Expand-Archive $zip -DestinationPath (Join-Path $root "tools") -Force
    Remove-Item $zip
    $sig = Get-AuthenticodeSignature $adb   # Zip selbst ist nicht signiert - adb.exe darin prüfen
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Google") {
        Remove-Item -Recurse -Force (Join-Path $root "tools\platform-tools")
        throw "adb.exe ist nicht gültig von Google signiert ($($sig.Status)) - abgebrochen"
    }
}
Ok $adb

# ---------------------------------------------------------------- 3. spacedesk
if (-not $SkipSpacedesk) {
    Step "spacedesk-Treiber (Zweitbildschirm per USB)"
    $svc = Get-Service spacedeskService -ErrorAction SilentlyContinue
    if (-not $svc) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            Warn "winget fehlt - spacedesk-Treiber von spacedesk.net installieren (oder App Installer aus dem Microsoft Store aktualisieren), dann install.ps1 erneut; ohne Zweitbildschirm: -SkipSpacedesk"
        } else {
            Write-Host "   Installation per winget (Windows fragt nach Administratorrechten) ..."
            $r = Run winget install -e --id Datronicsoft.SpacedeskDriver.Server --silent --accept-package-agreements --accept-source-agreements
            $svc = Get-Service spacedeskService -ErrorAction SilentlyContinue
            if (-not $svc) {
                # z. B. Code 3010 / "Neustart erforderlich": Dienst gibt es erst nach dem Neustart
                Warn "spacedesk-Treiber noch nicht aktiv (winget-Code $($r.Code)) - PC neu starten und install.ps1 erneut ausführen"
            }
        }
    }
}
if (-not $SkipSpacedesk -and $svc) {
    Ok "Treiber installiert"
    $key = "HKLM:\SOFTWARE\datronicsoft\spacedesk\Service"
    $on = (Get-ItemProperty $key -Name AndroidUsbControlEnabled -ErrorAction SilentlyContinue).AndroidUsbControlEnabled
    if ($on -ne 1) {
        Write-Host "   'USB Cable Android' einschalten (Administratorrechte) ..."
        # New-Item -Force würde einen VORHANDENEN Schlüssel leeren (alle spacedesk-Einstellungen weg)
        $cmd = "if (-not (Test-Path '$key')) { New-Item -Force '$key' | Out-Null }; Set-ItemProperty -Path '$key' -Name AndroidUsbControlEnabled -Value 1 -Type DWord; Restart-Service spacedeskService -Force"
        try {
            Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", $cmd
        } catch { Warn "Administratorrechte abgelehnt" }
        $on = (Get-ItemProperty $key -Name AndroidUsbControlEnabled -ErrorAction SilentlyContinue).AndroidUsbControlEnabled
        if ($on -ne 1) { Warn "nicht gesetzt - in der 'spacedesk DRIVER Console' unter COMMUNICATION INTERFACES 'USB Cable Android' anhaken" }
    }
    if ($on -eq 1) { Ok "USB Cable Android an (bleibt der Bildschirm am Tablet schwarz: in der 'spacedesk DRIVER Console' den Haken 'USB Cable Android' einmal von Hand setzen)" }
}

# config.json und launcher.json sind PC-gebunden (nicht im Git): beim ersten Mal aus config.example.json bzw.
# launcher.example.json anlegen, atomar; vorhandene Dateien bleiben unberührt. Mit -SkipSpacedesk ohne spacedesk-Kachel.
$frArgs = @("-m", "bridge.firstrun"); if ($SkipSpacedesk) { $frArgs += "--no-spacedesk" }
$fr = Run $python @frArgs
if ($fr.Code -ne 0) { throw "config.json/launcher.json nicht anlegbar: $($fr.Out)" }
if ($fr.Out) { $fr.Out -split "`r?`n" | ForEach-Object { Ok $_ } }

# config.json: mit -SkipSpacedesk beide spacedesk-Schalter aus; ohne Schalter nur das MTP-Umschalten
# wieder an (spacedesk_silence bleibt, wie es ist). Geschrieben wird nur bei Änderung, atomar.
$cfgPath = Join-Path $root "config.json"
$r = Run $python (Join-Path $root "scripts\set_config.py") $cfgPath ($(if ($SkipSpacedesk) { "skip" } else { "use" }))
if ($r.Code -ne 0) { throw "config.json nicht änderbar: $($r.Out)" }
# -Companion: ohne Tablet (-SkipTablet) gilt der Begleit-Modus für alle (tablet_mode). Mit Tablet entscheidet der
# Tablet-Schritt unten, sobald das Zielgerät feststeht (sonst träfe es bei einer Auswahl auch die anderen).
$firstDevice = -not (Test-Path (Join-Path $root "devices.json"))
if ($Companion -and $SkipTablet) {
    $r = Run $python (Join-Path $root "scripts\set_config.py") $cfgPath "companion"
    if ($r.Code -ne 0) { throw "config.json nicht änderbar: $($r.Out)" }
}

# ---------------------------------------------------------------- 4. Autostart + Bridge
Step "Bridge"
$bridgeRunning = { @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object CommandLine -match '-m bridge( |$)').Count -gt 0 }
if (-not $SkipAutostart) {
    & (Join-Path $root "scripts\install-autostart.ps1") -Python $python | ForEach-Object { "   $_" }
    if (-not (& $bridgeRunning)) { Start-ScheduledTask -TaskName "Tablet Deck Bridge" }
} elseif (-not (& $bridgeRunning)) {
    Start-Process (Join-Path (Split-Path $python) "pythonw.exe") -ArgumentList "-m", "bridge.supervise" -WorkingDirectory $root
}
$secret = Join-Path $root "secret.key"
for ($i = 0; $i -lt 30 -and -not (Test-Path $secret); $i++) { Start-Sleep 1 }
if (-not (Test-Path $secret)) { throw "Bridge startet nicht (kein secret.key) - siehe bridge.log / supervise.log" }
Ok "läuft (Taskleisten-Symbol), Log: bridge.log"

# ---------------------------------------------------------------- 4b. Sensor-Helfer
if (-not $SkipSensors) {
    Step "Sensor-Helfer (PC-Werte mit Adminrechten)"
    # Token für Hub <-> Helfer: hier ohne Adminrechte anlegen - der Admin-Helfer liest es nur
    $r = Run $python -c "from pathlib import Path; from bridge.sensors.server import load_or_create_token; load_or_create_token(Path('secrets') / 'sensors.key')"
    if ($r.Code -ne 0) { throw "Token für den Sensor-Helfer nicht anlegbar: $($r.Out)" }
    # PawnIO: signierter Treiber für LibreHardwareMonitor (Kerntakte, CPU-Temperaturen, Mainboard-Sensoren)
    if (-not (Get-CimInstance Win32_SystemDriver -Filter "Name='PawnIO'" -ErrorAction SilentlyContinue)) {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Write-Host "   PawnIO-Treiber per winget (Windows fragt nach Administratorrechten) ..."
            $r = Run winget install -e --id namazso.PawnIO --silent --accept-package-agreements --accept-source-agreements
            if ($r.Code -ne 0) { Warn "PawnIO nicht installiert - ohne ihn fehlen Kerntakte, CPU-Temperaturen und Mainboard-Werte" }
            else { Ok "PawnIO installiert" }
        } else { Warn "winget fehlt - PawnIO von https://pawnio.eu installieren" }
    } else { Ok "PawnIO-Treiber vorhanden" }
    if ((Get-ScheduledTask -TaskName "Tablet Deck Sensors" -ErrorAction SilentlyContinue) -and (Test-SensorCopy)) {
        Ok "Aufgabe 'Tablet Deck Sensors' eingerichtet, Kopie aktuell"
        if (-not (Get-SensorSources)) { Start-ScheduledTask -TaskName "Tablet Deck Sensors" -ErrorAction SilentlyContinue }
    } elseif (Test-UserPython $python) {
        # install-sensors.ps1 würde nach der UAC-Abfrage abbrechen: ein Python im Benutzerprofil kann jeder
        # Prozess des Nutzers ändern - mit Adminrechten gestartet wäre das eine Rechteausweitung
        Warn "Sensor-Helfer übersprungen: $python ist nur für diesen Benutzer installiert. Python für alle Benutzer: winget install -e --id Python.Python.3.13 --scope machine - dann install.ps1 erneut (oder -SkipSensors)"
    } else {
        # Was jetzt kopiert wird, läuft danach mit Adminrechten. Lokale (nicht eingecheckte) Änderungen an diesen
        # Dateien nur mit -AllowLocalChanges - so wird eine unbemerkte Änderung nicht per UAC zu Admin-Code.
        $srcPaths = "scripts/install-sensors.ps1", "scripts/sensors-run.py", "bridge/sensors"
        if ((Get-Command git -ErrorAction SilentlyContinue) -and (Run git -C $root rev-parse --git-dir).Code -eq 0) {
            $st = Run git -C $root status --porcelain -- @srcPaths
            if ($st.Code -ne 0) { throw "git status fehlgeschlagen: $($st.Out)" }
            $dirty = $st.Out
            $rev = (Run git -C $root log -1 --format="%h %s" -- @srcPaths).Out
            if ($rev) { Write-Host "   Quelle: $rev" }
            if ($dirty -and -not $AllowLocalChanges) {
                $dirty -split "`r?`n" | ForEach-Object { Warn "geändert: $_" }
                throw "Nicht eingecheckte Änderungen am Sensor-Helfer - prüfen, einchecken oder install.ps1 -AllowLocalChanges"
            }
        } else { Warn "kein git bzw. kein git-Repo - Stand der Quelle nicht prüfbar" }
        Write-Host "   Kopie nach $sensorsDest und geplante Aufgabe (Administratorrechte) ..."
        # immer Windows PowerShell: install-sensors.ps1 beschränkt PSModulePath auf deren Systemmodule
        $ps = Join-Path $env:windir "System32\WindowsPowerShell\v1.0\powershell.exe"
        $isc = Join-Path $root "scripts\install-sensors.ps1"
        try {
            Start-Process $ps -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", "`"$isc`"", "-Python", "`"$python`"", "-Repo", "`"$($root.TrimEnd('\'))\.`"",
                "-User", "`"$env:USERDOMAIN\$env:USERNAME`""
        } catch { Warn "Administratorrechte abgelehnt - PC-Werte zeigen nur die Grundwerte" }
        $log = Join-Path $sensorsDest "logs\install.log"
        if (Test-Path $log) {
            Get-Content $log | Where-Object { $_ -match '^\s+(ok|!)|FEHLER' } | ForEach-Object { Write-Host $_ }
        }
    }
    $src = $null
    for ($i = 0; $i -lt 15 -and -not $src; $i++) { Start-Sleep 1; $src = Get-SensorSources }
    if ($src) {
        Ok ("Helfer antwortet: " + (($src.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ", "))
    } elseif (Get-ScheduledTask -TaskName "Tablet Deck Sensors" -ErrorAction SilentlyContinue) {
        Warn "Helfer antwortet nicht - Log: $sensorsDest\logs\sensors.log"
    }
}

# ---------------------------------------------------------------- 5./6. Tablet
if (-not $SkipTablet) {
    Step "Tablet"
    # Zielgerät: -Serial, bei mehreren angesteckten Auswahl per Nummer, sonst das eine
    $all = @(Get-AdbDevices)
    $target = $null
    if ($Serial) {
        $target = $all | Where-Object { $_.Seriennummer -eq $Serial } | Select-Object -First 1
        if (-not $target) { Warn "Gerät $Serial nicht angesteckt. Angesteckt:"; Show-AdbDevices $all }
    } elseif ($all.Count -gt 1) {
        Write-Host "   Mehrere Android-Geräte angesteckt:"
        Show-AdbDevices $all
        $pick = ""
        try { $pick = Read-Host "   Welches einrichten? Nummer (Enter = keins)" } catch { }
        $n = 0
        if ([int]::TryParse("$pick".Trim(), [ref]$n) -and $n -ge 1 -and $n -le $all.Count) { $target = $all[$n - 1] }
        else { Warn "kein Gerät gewählt - später: .\install.ps1 -Serial <Seriennummer>" }
    } else { $target = $all | Select-Object -First 1 }
    $companionDone = $false
    if ($target -and $target.Seriennummer -match ':|_adb-tls|^adb-') {
        # adb über WLAN (IP:Port): keine feste Kennung fürs Gerät - der Hub koppelt nur per USB
        Warn "$($target.Seriennummer) ist per WLAN-adb verbunden - Gerät per USB anstecken und erneut ausführen"
        $target = $null
    }
    # Erstes Gerät überhaupt: nur eins angesteckt, kein -Serial, Hub kennt noch keins (devices.json fehlt)
    $soleFirst = $all.Count -eq 1 -and -not $Serial -and $firstDevice
    $dev = if ($target) { "$($target.Seriennummer)`t$($target.Zustand)" } else { $null }
    $adbSel = if ($target) { @("-s", $target.Seriennummer) } else { @() }
    if (($Serial -and -not $target) -or ($all -and -not $target)) {
        # schon gemeldet (nicht angesteckt bzw. keins gewählt)
    } elseif ($dev -match "offline") {
        Warn "Tablet 'offline' - Kabel neu stecken, dann install.ps1 erneut ausführen"
    } elseif (-not $dev) {
        Warn "kein Tablet per USB gefunden - Tablet vorbereiten (docs\tablet-setup.md), anstecken, install.ps1 erneut ausführen"
    } elseif ($dev -match "unauthorized") {
        Warn "USB-Debugging am Tablet erlauben (Dialog am Tablet bestätigen), dann install.ps1 erneut ausführen"
    } else {
        $apkDir = Join-Path $root "android\build"
        $apkPath = Join-Path $apkDir "tablet-deck.apk"   # setup-launcher.ps1 installiert genau diese Datei
        $canBuild = (Test-Path (Join-Path $root "tools\jdk")) -and (Test-Path (Join-Path $root "tools\android-sdk"))
        $ver = Get-LauncherVersion $root
        $verFile = "$apkPath.version"   # Version einer aus dem Release geladenen APK
        $haveVer = if (Test-Path -LiteralPath $verFile) { "$(Get-Content -LiteralPath $verFile -Raw)".Trim() } else { "" }
        if ($Apk) {
            if ($Apk -ne $apkPath) {
                New-Item -ItemType Directory -Force $apkDir | Out-Null
                Copy-Item -Force -LiteralPath $Apk -Destination $apkPath
                Remove-Item -LiteralPath $verFile -Force -ErrorAction SilentlyContinue
            }
            Ok "Launcher-APK: $Apk"
        } elseif ($canBuild) {
            $r = Run $python (Join-Path $root "android\build.py")
            if ($r.Code -ne 0) { throw "APK-Build fehlgeschlagen:`n$($r.Out)" }
            Ok "Launcher gebaut"
            Remove-Item -LiteralPath $verFile -Force -ErrorAction SilentlyContinue
        } elseif ((Test-Path -LiteralPath $apkPath) -and $ver -and $haveVer -eq $ver) {
            Ok "Launcher-APK $ver aus den Releases: android\build\tablet-deck.apk"
        } elseif (Get-ReleaseApk $root $apkPath) {
            Ok "Launcher-APK $ver aus den GitHub-Releases geladen (Prüfsumme ok, Zertifikat passt)"
        } elseif (Test-Path -LiteralPath $apkPath) {
            # z. B. aus dem Weitergabe-Zip oder offline: nehmen, aber sagen, dass die Version ungeprüft ist
            Warn "nehme vorhandene android\build\tablet-deck.apk (Version nicht geprüft, Projekt ist $ver)"
        }
        if (-not (Test-Path $apkPath)) {
            Warn "keine Launcher-APK: tablet-deck.apk aus den Releases laden ($ReleasesUrl) und nach android\build\ legen oder angeben: install.ps1 -Apk <Pfad zur tablet-deck.apk>"
        } else {
            # Hashtable: ein Array würde "-Companion" als Wert statt als Schalter übergeben (PS 5.1)
            $setupArgs = @{ Serial = $target.Seriennummer }; if ($Companion) { $setupArgs.Companion = $true }
            & (Join-Path $root "tablet\setup-launcher.ps1") @setupArgs | ForEach-Object { "   $_" }
            Ok "Launcher eingerichtet und gekoppelt ($($target.Seriennummer) $($target.Modell))"
            # Begleit-Modus immer für dieses Gerät (tablet_modes); beim allerersten Gerät zusätzlich für alle
            # (tablet_mode, wie bisher). Andere Geräte bleiben unverändert.
            if ($Companion) {
                $companionDone = $true
                $r = Run $python (Join-Path $root "scripts\set_config.py") $cfgPath "device" $target.Seriennummer "companion"
                if ($r.Code -ne 0) { throw "config.json nicht änderbar: $($r.Out)" }
                if ($soleFirst) {
                    $r = Run $python (Join-Path $root "scripts\set_config.py") $cfgPath "companion"
                    if ($r.Code -ne 0) { throw "config.json nicht änderbar: $($r.Out)" }
                    Ok "Begleit-Modus (erstes Gerät: auch Standard für weitere)"
                } else {
                    Ok "Begleit-Modus nur für $($target.Seriennummer) (tablet_modes in config.json)"
                    Warn "Bridge neu starten (geplante Aufgabe 'Tablet Deck Bridge' beenden und starten), Gerät angesteckt lassen"
                }
            }
        }
        if (-not $SkipSpacedesk) {
            $has = (Run $adb @adbSel shell pm list packages ph.spacedesk.beta).Out
            if ($has -notmatch "ph.spacedesk.beta") { Warn "spacedesk-App fehlt auf dem Tablet - siehe docs\install.md (Abschnitt spacedesk)" }
            else { Ok "spacedesk-App vorhanden" }
        }
        if ($Modules -and $Companion) {
            Warn "-Modules im Begleit-Modus übersprungen: Die Magisk-Module (hardening, chargectl) brauchen Root."
        } elseif ($Modules) {
            foreach ($m in "chargectl", "hardening") {
                & (Join-Path $root "tablet\install-module.ps1") (Join-Path $root "tablet\$m\module") -Serial $target.Seriennummer | ForEach-Object { "   $_" }
            }
            Write-Host "   Tablet startet neu (Module werden aktiv) ..."
            Run $adb @adbSel reboot | Out-Null
        }
    }
}

if ($Companion -and -not $SkipTablet -and -not $companionDone) {
    Warn "-Companion nicht eingetragen (kein Gerät eingerichtet) - nach Behebung install.ps1 -Companion erneut ausführen"
}

# ---------------------------------------------------------------- 7. Test
Step "Smoke-Test"
Start-Sleep 2
$r = Run $python (Join-Path $root "tests\smoke_bridge.py")
$r.Out -split "`r?`n" | ForEach-Object { "   $_" }
if ($r.Code -ne 0) { Warn "Smoke-Test meldet Fehler (siehe oben)" } else { Ok "alles grün" }
Write-Host "`nFertig. Panel-Editor: Taskleisten-Symbol -> 'Panel-Editor öffnen'." -ForegroundColor Cyan
