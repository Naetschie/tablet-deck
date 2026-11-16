# Startet die Bridge beim Windows-Login automatisch - als geplante Aufgabe in deiner Sitzung
# (ein Windows-Dienst ginge nicht: Dienste laufen in Session 0 und können keine Tasten/Maus an den
# Desktop senden, kein Taskleisten-Symbol).
#   - Die Aufgabe startet den Wächter (bridge/supervise.py). Er startet die Bridge nach einem Absturz
#     neu (5 s, bei Absturzschleifen wachsend bis 5 min); "Beenden" im Taskleisten-Menü (Exit 0) beendet
#     auch den Wächter. (Die Neustart-Option der Aufgabenplanung greift nur bei Startfehlern.)
#   - nie zwei Instanzen, kein Zeitlimit, normale Priorität (sonst Eingabe-Verzögerung unter Spiel-Last)
# Keine Admin-Rechte nötig. -Remove entfernt die Aufgabe (und alte Autostart-Verknüpfungen).
# Log: bridge.log im Projektordner. Panel-Editor: Taskleisten-Symbol -> "Panel-Editor öffnen".
param([switch]$Remove, [string]$Python)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$name = "Tablet Deck Bridge"
$oldLnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Tablet Deck Bridge.lnk"
if (Test-Path $oldLnk) { Remove-Item $oldLnk }

if ($Remove) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        "Autostart entfernt."
    } else { "Kein Autostart eingerichtet." }
    return
}

# pythonw des Python, mit dem die Abhängigkeiten installiert sind (nicht irgendeins aus dem PATH)
$ErrorActionPreference = "Continue"   # PS 5.1: stderr (ImportError) sonst sofort als Abbruch
$exe = if ($Python) { $Python } else { "python" }
$out = & $exe -c "import sys, websockets, pycaw; print(sys.executable)" 2>$null
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0 -or -not $out) { throw "python mit websockets/pycaw nicht gefunden - erst: pip install -r requirements.txt" }
$python = "$out".Trim()
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "pythonw.exe fehlt neben $python" }

$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m bridge.supervise" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = "PT10S"   # kurz warten, bis Desktop/Audio bereit sind
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 4
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "USB-Tablet als PC-Erweiterung (Bridge, Taskleisten-Symbol)" -Force | Out-Null
"Autostart eingerichtet: geplante Aufgabe '$name' (beim Anmelden, Wächter startet nach Absturz neu)."
"Jetzt starten: Start-ScheduledTask -TaskName '$name'"
