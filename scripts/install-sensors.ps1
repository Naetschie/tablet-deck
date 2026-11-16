# Sensor-Helfer (PC-Werte) mit Adminrechten einrichten - wird von install.ps1 per UAC gestartet.
#   .\scripts\install-sensors.ps1 -Python C:\Python313\python.exe -Repo P:\...\touchtabletexpansion_PC
#   .\scripts\install-sensors.ps1 -Remove     Aufgabe und Programmordner entfernen
#
# Warum so (docs/install.md, "Sensor-Helfer"): Kerntakte, CPU-Temperaturen, Mainboard-Sensoren
# (LibreHardwareMonitor) und FPS (PresentMon) brauchen Adminrechte. Was mit Adminrechten läuft, darf
# nichts ausführen, was ein normaler Prozess des Nutzers ändern kann - sonst wird jede Schadsoftware in
# der Sitzung zum Admin. Deshalb:
#   - Code-Kopie nach %ProgramFiles%\TabletDeck\sensors (nur Admin beschreibbar): app\ (feste Dateiliste aus
#     bridge\sensors), lib\ (pip --isolated --require-hashes: feste Versionen mit SHA-256 aus
#     bridge\sensors\requirements.txt, nur von pypi.org, ohne pip-Cache und -Konfiguration des Nutzers),
#     PresentMon.exe (feste Version, SHA-256 und Intel-Signatur). Downloads und Entpacken in einem
#     Arbeitsordner unter %ProgramFiles% statt im %TEMP% des Nutzers.
#   - Python muss samt Inhalt, Besitzer und übergeordneten Ordnern nur für Admins änderbar sein (wird
#     geprüft) und startet mit -I; run.py setzt vor allen Importen eine feste Umgebung (die Aufgabe erbt
#     sonst Variablen aus HKCU\Environment, z. B. COR_PROFILER für .NET oder PATH)
#   - der Projektordner liefert nur Daten (config.json, sensors.json, secrets\sensors.key)
#   - geplante Aufgabe "Tablet Deck Sensors": beim Anmelden, höchste Rechte, in deiner Sitzung
param([string]$Python, [string]$Repo, [string]$User, [switch]$Remove)
$ErrorActionPreference = "Stop"
# Module nur aus den Systemordnern laden: das automatische Nachladen (ScheduledTasks, Get-FileHash …) fände
# sonst zuerst Module im Dokumente-Ordner des Nutzers - als Admin ausgeführt
$env:PSModulePath = "$env:windir\system32\WindowsPowerShell\v1.0\Modules;$env:ProgramFiles\WindowsPowerShell\Modules"

$TaskName = "Tablet Deck Sensors"
$Dest = Join-Path $env:ProgramFiles "TabletDeck\sensors"
$PresentMonVersion = "2.6.0"
$PresentMonUrl = "https://github.com/GameTechDev/PresentMon/releases/download/v$PresentMonVersion/PresentMon-$PresentMonVersion-x64.exe"
$PresentMonSha256 = "b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af"
# feste Liste statt *.py: eine zusätzlich abgelegte Datei käme sonst ungesehen in den Admin-Betrieb
$SensorFiles = "__init__.py", "__main__.py", "collector.py", "lhm_src.py", "mapping.py", "nvml_src.py",
               "presentmon_src.py", "psutil_src.py", "server.py"

function Ok($t)   { Write-Host "   ok: $t" -ForegroundColor Green }
function Warn($t) { Write-Host "   !  $t" -ForegroundColor Yellow }

$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Bitte mit Administratorrechten starten (install.ps1 macht das per UAC-Abfrage)"
}

function Stop-Helper {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    # installierte Kopie und von Hand gestartete Helfer (python -m bridge.sensors) - sonst ist der Port belegt
    $procs = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -match 'TabletDeck\\sensors\\run\.py' -or $_.CommandLine -match '-m bridge\.sensors' })
    $procs += @(Get-CimInstance Win32_Process -Filter "Name='PresentMon.exe'" | Where-Object { $_.ExecutablePath -like "$Dest*" })
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Ok "beendet: $($p.Name) (PID $($p.ProcessId))"
    }
    # warten, bis die Dateien in lib\ (DLLs) frei sind
    foreach ($p in $procs) { Wait-Process -Id $p.ProcessId -Timeout 10 -ErrorAction SilentlyContinue }
}

if ($Remove) {
    Stop-Helper
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Ok "Aufgabe '$TaskName' entfernt"
    }
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest; Ok "$Dest entfernt" }
    $parent = Split-Path $Dest
    if ((Test-Path $parent) -and -not (Get-ChildItem $parent)) { Remove-Item $parent }
    return
}

# Ausgabe mitschreiben: das UAC-Fenster schließt sich am Ende, install.ps1 zeigt das Log danach an
New-Item -ItemType Directory -Force (Join-Path $Dest "logs") | Out-Null
Start-Transcript -Path (Join-Path $Dest "logs\install.log") -Force | Out-Null
$stopped = $false
trap {
    Write-Host "FEHLER: $_" -ForegroundColor Red
    # Helfer nicht tot zurücklassen: lief er vorher, mit dem alten Stand wieder starten
    if ($stopped -and (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
        Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "   Aufgabe mit dem bisherigen Stand wieder gestartet"
    }
    Stop-Transcript | Out-Null
    exit 1
}

if (-not $Python -or -not (Test-Path $Python)) { throw "-Python fehlt (Pfad zu python.exe)" }
if (-not $Repo -or -not (Test-Path (Join-Path $Repo "bridge\sensors\__main__.py"))) { throw "-Repo ist kein Projektordner" }
$Python = (Resolve-Path $Python).Path
$Repo = (Resolve-Path $Repo).Path.TrimEnd("\")
$pythonw = Join-Path (Split-Path $Python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "pythonw.exe fehlt neben $Python" }

# ---------------------------------------------------------------- Rechte prüfen
$AdminSids = @("S-1-5-18", "S-1-5-32-544", "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464")
function Get-Sid($id) {
    try { return $id.Translate([Security.Principal.SecurityIdentifier]).Value } catch { return "$id" }
}
# Wer außer SYSTEM, Administratoren, TrustedInstaller (und ERSTELLER-BESITZER) darf $path ändern?
#   $mask: zu prüfende Rechte; -Self: nur Einträge, die für das Objekt selbst gelten (nicht "nur vererben")
function Get-WriteHolders($path, [long]$mask) {
    $acl = Get-Acl -LiteralPath $path
    $owner = Get-Sid ([Security.Principal.NTAccount]$acl.Owner)
    if ($AdminSids -notcontains $owner) { "$path -> Besitzer $($acl.Owner)" }   # Besitzer darf die Rechte ändern
    foreach ($r in $acl.Access) {
        if ($r.AccessControlType -ne "Allow") { continue }
        if ($r.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
        $sid = Get-Sid $r.IdentityReference
        # ERSTELLER-BESITZER (S-1-3-0) und EIGENTÜMERRECHTE (S-1-3-4, legt Python 3.13 bei os.mkdir an) gelten
        # nur für den Besitzer - und der wird oben geprüft (muss SYSTEM/Administratoren/TrustedInstaller sein)
        if ($AdminSids -contains $sid -or $sid -eq "S-1-3-0" -or $sid -eq "S-1-3-4") { continue }
        if (([long]$r.FileSystemRights -band $mask) -ne 0) { "$path -> $($r.IdentityReference): $($r.FileSystemRights)" }
    }
}
# Inhalt: WriteData/AddFile, AppendData/AddSubdir, WriteEA, DeleteChild, WriteAttributes, Delete, WRITE_DAC,
# WRITE_OWNER, GENERIC_ALL, GENERIC_WRITE
$WriteMask = 0x2 -bor 0x4 -bor 0x10 -bor 0x40 -bor 0x100 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x10000000 -bor 0x40000000
# übergeordnete Ordner: Umbenennen/Ersetzen des Unterordners (DeleteChild) oder Rechte ändern; Anlegen neuer
# Ordner (z. B. Authentifizierte Benutzer auf C:\) ist harmlos
$ParentMask = 0x40 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x10000000
function Test-AdminOnlyTree($dir) {
    $bad = @()
    $bad += @(Get-WriteHolders $dir $WriteMask)
    foreach ($i in Get-ChildItem -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue) {
        if ($i.Attributes -band [IO.FileAttributes]::ReparsePoint) { $bad += "$($i.FullName) ist eine Verknüpfung (Junction/Symlink)" }
        $bad += @(Get-WriteHolders $i.FullName $WriteMask)
        if ($bad.Count -gt 20) { break }
    }
    $p = Split-Path $dir
    while ($p) {
        $bad += @(Get-WriteHolders $p $ParentMask)
        $pi = Get-Item -LiteralPath $p -Force
        if ($pi.Attributes -band [IO.FileAttributes]::ReparsePoint) { $bad += "$p ist eine Verknüpfung (Junction/Symlink)" }
        $p = Split-Path $p
    }
    if ((Get-Item -LiteralPath $dir -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        $bad += "$dir ist eine Verknüpfung (Junction/Symlink)"
    }
    return $bad
}

$pyDir = Split-Path $Python
Write-Host "   Python-Ordner prüfen (Rechte aller Dateien, Besitzer, übergeordnete Ordner) ..."
if (Test-Path (Join-Path $pyDir "pyvenv.cfg")) { throw "$Python ist eine virtuelle Umgebung - bitte das Basis-Python angeben" }
$bad = @(Test-AdminOnlyTree $pyDir)
if ($bad) {
    $bad | Select-Object -First 10 | ForEach-Object { Warn $_ }
    throw "Python in $pyDir ist nicht nur für Administratoren änderbar - so würde jeder Prozess des Nutzers zum Admin. Python für alle Benutzer installieren (winget install -e --id Python.Python.3.13 --scope machine) und install.ps1 mit diesem Python erneut starten."
}
Ok "Python nur für Admins änderbar: $pyDir"

# ---------------------------------------------------------------- Kopie
Stop-Helper
$bad = @(Test-AdminOnlyTree $Dest)
# hier bewusst ohne Neustart im Fehlerfall: der Inhalt von $Dest ist dann nicht vertrauenswürdig
if ($bad) { $bad | Select-Object -First 10 | ForEach-Object { Warn $_ }; throw "$Dest ist für normale Benutzer änderbar - abgebrochen" }
$stopped = $true

# Arbeitsordner für pip und Downloads (der %TEMP% des Nutzers ist von ihm beschreibbar: Austausch zwischen
# Prüfung und Kopie möglich)
$work = Join-Path $Dest "tmp"
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory $work | Out-Null
$env:TEMP = $work; $env:TMP = $work

$app = Join-Path $Dest "app"
if (Test-Path $app) { Remove-Item -Recurse -Force $app }
New-Item -ItemType Directory -Force (Join-Path $app "bridge\sensors") | Out-Null
Set-Content -Path (Join-Path $app "bridge\__init__.py") -Value "" -Encoding ASCII
foreach ($f in $SensorFiles) { Copy-Item (Join-Path $Repo "bridge\sensors\$f") (Join-Path $app "bridge\sensors\$f") }
Copy-Item (Join-Path $Repo "scripts\sensors-run.py") (Join-Path $Dest "run.py") -Force
Ok "Code nach $Dest kopiert"

# Pakete: nur wenn sich requirements.txt geändert hat (Kopie daneben merkt sich den Stand)
$req = Join-Path $work "requirements.txt"
Copy-Item (Join-Path $Repo "bridge\sensors\requirements.txt") $req   # geprüfte Kopie, nicht das Original lesen
$reqDone = Join-Path $Dest "requirements.installed.txt"
$lib = Join-Path $Dest "lib"
$same = (Test-Path $lib) -and (Test-Path $reqDone) -and
        ((Get-FileHash $req).Hash -eq (Get-FileHash $reqDone).Hash)
if (-not $same) {
    $new = Join-Path $Dest "lib.new"
    if (Test-Path $new) { Remove-Item -Recurse -Force $new }
    Write-Host "   Pakete installieren (pip, feste Versionen mit Prüfsummen) ..."
    # --isolated: keine PIP_*-Variablen, keine pip.ini des Nutzers; Index fest; jede Datei mit Hash
    Get-ChildItem env: | Where-Object Name -like "PIP_*" | ForEach-Object { Remove-Item "env:$($_.Name)" }
    $ErrorActionPreference = "Continue"
    $out = & $Python -I -m pip install --isolated --disable-pip-version-check --no-cache-dir `
        --index-url https://pypi.org/simple --only-binary=:all: --no-deps --require-hashes `
        --target $new -r $req 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($code -ne 0) { $out | Select-Object -Last 15 | ForEach-Object { "   $_" }; throw "pip fehlgeschlagen" }
    if (Test-Path $lib) { Remove-Item -Recurse -Force $lib }
    Rename-Item $new "lib"
    Copy-Item $req $reqDone -Force
    Ok "Pakete installiert"
} else { Ok "Pakete aktuell" }

# ---------------------------------------------------------------- PresentMon
$pm = Join-Path $Dest "PresentMon.exe"
if ((Test-Path $pm) -and (Get-FileHash $pm -Algorithm SHA256).Hash -eq $PresentMonSha256) {
    Ok "PresentMon $PresentMonVersion vorhanden"
} else {
    Write-Host "   PresentMon $PresentMonVersion laden ..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $file = Join-Path $work "PresentMon.exe"
    Invoke-WebRequest $PresentMonUrl -OutFile $file -UseBasicParsing
    $hash = (Get-FileHash $file -Algorithm SHA256).Hash
    if ($hash -ne $PresentMonSha256) { throw "PresentMon: Prüfsumme falsch ($hash) - abgebrochen" }
    $sig = Get-AuthenticodeSignature $file
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "O=Intel Corporation") {
        throw "PresentMon ist nicht gültig von Intel signiert ($($sig.Status)) - abgebrochen"
    }
    Move-Item $file $pm -Force
    Ok "PresentMon $PresentMonVersion (SHA-256 und Intel-Signatur geprüft)"
}
Remove-Item -Recurse -Force $work

# ---------------------------------------------------------------- Aufgabe
# Nutzer aus install.ps1 (nicht erhöht): bei UAC mit einem anderen Admin-Konto wäre $env:USERNAME sonst falsch
$taskUser = if ($User) { $User } else { "$env:USERDOMAIN\$env:USERNAME" }
# Repo darf nicht auf "\" enden (P:\ -> "P:\" würde das schließende Anführungszeichen maskieren)
$dataArg = if ($Repo.EndsWith(":")) { "$Repo\." } else { $Repo }
$taskArgs = "-I `"$(Join-Path $Dest 'run.py')`" --data `"$dataArg`""
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $taskArgs -WorkingDirectory $Dest
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Tablet Deck: PC-Werte (LibreHardwareMonitor, PresentMon) mit Adminrechten aus $Dest" `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
$stopped = $false
Ok "Aufgabe '$TaskName' eingerichtet und gestartet (Log: $Dest\logs\sensors.log)"
Stop-Transcript | Out-Null
