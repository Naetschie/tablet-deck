# Hilfsfunktionen für install.ps1 (per Dot-Sourcing geladen): Python finden/installieren, Launcher-APK aus den
# GitHub-Releases holen. Einzeln testbar: . .\scripts\install-helpers.ps1; Find-Python
$ReleaseRepo = "Naetschie/tablet-deck"
$ReleasesUrl = "https://github.com/$ReleaseRepo/releases"
$PythonFallback = "3.13.14"   # nur ohne winget: Installer direkt von python.org (signiert, wird geprüft)

# Externe Programme: stderr nicht als Abbruch werten (PS 5.1), Exit-Code selbst prüfen
function Invoke-Native {
    $ErrorActionPreference = "Continue"
    $exe = $args[0]
    $rest = @($args | Select-Object -Skip 1)
    $out = & $exe @rest 2>&1
    [pscustomobject]@{ Code = $LASTEXITCODE; Out = ($out | Out-String).Trim() }
}

# PATH aus der Registry neu lesen (nach einer Installation im selben Fenster, ohne neues Terminal)
function Update-SessionPath {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (@($m, $u) | Where-Object { $_ }) -join ";"
}

# Pfad zu python.exe >= 3.11 oder $null. Der Store-Platzhalter "python" (WindowsApps) startet kein Python und
# fällt durch die Probe; zusätzlich die üblichen Installationsorte (falls PATH noch alt ist).
function Find-Python {
    $cands = @("python", "py")
    $cands += @(Get-ChildItem -ErrorAction SilentlyContinue -Path `
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python3*\python.exe"),
        (Join-Path $env:ProgramFiles "Python3*\python.exe") | Sort-Object FullName -Descending |
        ForEach-Object { $_.FullName })
    foreach ($cand in $cands) {
        if (-not (Get-Command $cand -ErrorAction SilentlyContinue)) { continue }
        $r = Invoke-Native $cand -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')"
        if ($r.Code -eq 0 -and $r.Out) {
            $p = ($r.Out -split "`r?`n")[-1].Trim()
            if ($p -and (Test-Path $p)) { return $p }
        }
    }
    return $null
}

# Python für den aktuellen Benutzer installieren (ohne Adminrechte): winget, sonst python.org-Installer.
function Install-Python {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "   Python per winget (nur für diesen Benutzer) ..."
        $r = Invoke-Native winget install -e --id Python.Python.3.13 --scope user --silent `
            --accept-package-agreements --accept-source-agreements
        if ($r.Code -eq 0) { Update-SessionPath; return }
        Write-Host "   winget fehlgeschlagen ($($r.Code)) - Installer von python.org ..."
    }
    $v = $PythonFallback
    $exe = Join-Path $env:TEMP "python-$v-amd64.exe"
    $ProgressPreference = "SilentlyContinue"   # PS 5.1: Fortschrittsbalken bremst Downloads stark
    Invoke-WebRequest "https://www.python.org/ftp/python/$v/python-$v-amd64.exe" -OutFile $exe -UseBasicParsing
    $sig = Get-AuthenticodeSignature $exe
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Python Software Foundation") {
        Remove-Item $exe -Force
        throw "Python-Installer ist nicht gültig von der Python Software Foundation signiert ($($sig.Status)) - abgebrochen"
    }
    $p = Start-Process $exe -Wait -PassThru -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1",
        "Include_launcher=1", "Include_test=0"
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) { throw "Python-Installation fehlgeschlagen (Code $($p.ExitCode))" }
    Update-SessionPath
}

# versionName der Launcher-App aus dem Manifest (z. B. "4.1") oder $null
function Get-LauncherVersion($root) {
    $m = Join-Path $root "android\AndroidManifest.xml"
    if (-not (Test-Path $m)) { return $null }
    $hit = Select-String -Path $m -Pattern 'android:versionName="([^"]+)"' | Select-Object -First 1
    if ($hit) { return $hit.Matches[0].Groups[1].Value }
    return $null
}

# tablet-deck.apk des Releases v<versionName> nach $dest laden. Prüft die SHA-256-Prüfsumme aus der
# GitHub-API und dass es ein APK (Zip mit AndroidManifest.xml) ist. Gibt $true/$false zurück, wirft nicht.
function Get-ReleaseApk($root, $dest) {
    $ver = Get-LauncherVersion $root
    if (-not $ver) { Write-Host "   Version der App nicht lesbar (android\AndroidManifest.xml)"; return $false }
    $tmp = "$dest.download"
    $ProgressPreference = "SilentlyContinue"
    try {
        $rel = Invoke-RestMethod "https://api.github.com/repos/$ReleaseRepo/releases/tags/v$ver" `
            -Headers @{ "User-Agent" = "tablet-deck-install" } -TimeoutSec 20
        $asset = @($rel.assets | Where-Object name -eq "tablet-deck.apk") | Select-Object -First 1
        if (-not $asset) { Write-Host "   Release v$ver hat keine tablet-deck.apk"; return $false }
        Write-Host "   lade tablet-deck.apk aus Release v$ver ..."
        New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
        Invoke-WebRequest $asset.browser_download_url -OutFile $tmp -UseBasicParsing -TimeoutSec 120
        if ($asset.digest -match '^sha256:([0-9a-f]{64})$') {
            if ((Get-FileHash $tmp -Algorithm SHA256).Hash -ne $Matches[1]) {
                Write-Host "   Prüfsumme stimmt nicht - verworfen"; return $false
            }
        }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($tmp)
        try { $ok = @($zip.Entries | Where-Object FullName -eq "AndroidManifest.xml").Count -eq 1 }
        finally { $zip.Dispose() }
        if (-not $ok) { Write-Host "   Datei ist kein APK - verworfen"; return $false }
        Move-Item -Force $tmp $dest
        return $true
    } catch {
        Write-Host "   Download fehlgeschlagen: $($_.Exception.Message)"
        return $false
    } finally {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
}
