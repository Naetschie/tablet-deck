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

# PATH aus der Registry neu lesen (nach einer Installation im selben Fenster, ohne neues Terminal). Einträge,
# die nur in diesem Prozess stehen, bleiben hinten erhalten.
function Update-SessionPath {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $new = @("$m;$u" -split ";" | Where-Object { $_ })
    $keep = @($env:Path -split ";" | Where-Object { $_ -and $new -notcontains $_ })
    $env:Path = ($new + $keep) -join ";"
}

function Find-PythonDirs($pattern) {   # neueste zuerst (Python313 vor Python39)
    @(Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
        Sort-Object { $n = 0; [void][int]::TryParse(($_.Directory.Name -replace '^Python3', '' -replace '\D.*$', ''), [ref]$n); $n } -Descending |
        ForEach-Object { $_.FullName })
}

# Pfad zu python.exe >= 3.11 oder $null. Der Store-Platzhalter "python" (WindowsApps) startet kein Python und
# fällt durch die Probe. Reihenfolge: für alle Benutzer installiert (%ProgramFiles%, nur das taugt für den
# Sensor-Helfer), dann PATH, dann das Benutzerprofil (falls PATH noch alt ist).
function Find-Python {
    $cands = @(Find-PythonDirs (Join-Path $env:ProgramFiles "Python3*\python.exe"))
    $cands += @("python", "py")
    $cands += @(Find-PythonDirs (Join-Path $env:LOCALAPPDATA "Programs\Python\Python3*\python.exe"))
    foreach ($cand in $cands) {
        if (-not (Get-Command $cand -ErrorAction SilentlyContinue)) { continue }
        $r = Invoke-Native $cand -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')"
        if ($r.Code -eq 0 -and $r.Out) {
            $p = ($r.Out -split "`r?`n")[-1].Trim()
            if ($p -and (Test-Path -LiteralPath $p)) { return $p }
        }
    }
    return $null
}

# Liegt dieses Python im Benutzerprofil (für den Sensor-Helfer mit Adminrechten ungeeignet)?
function Test-UserPython($python) {
    return $python -and $env:LOCALAPPDATA -and
        $python.StartsWith($env:LOCALAPPDATA.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}

# Python installieren: $Machine = für alle Benutzer (UAC-Abfrage; nötig für den Sensor-Helfer), sonst nur für
# den aktuellen Benutzer. winget, ohne winget der signierte Installer von python.org.
function Install-Python([switch]$Machine) {
    $scope = if ($Machine) { "machine" } else { "user" }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "   Python per winget ($(if ($Machine) { 'für alle Benutzer, Windows fragt nach Administratorrechten' } else { 'nur für diesen Benutzer' })) ..."
        $r = Invoke-Native winget install -e --id Python.Python.3.13 --scope $scope --silent `
            --accept-package-agreements --accept-source-agreements
        if ($r.Code -eq 0) { Update-SessionPath; return }
        Write-Host ("   winget fehlgeschlagen (Code $($r.Code)) - zweiter Versuch mit dem Installer von python.org" +
            "$(if ($Machine) { ' (erneute Abfrage der Administratorrechte)' }) ...")
    }
    $v = $PythonFallback
    $dir = Join-Path $env:TEMP ("tabletdeck-python-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory $dir | Out-Null
    $exe = Join-Path $dir "python-$v-amd64.exe"
    $ProgressPreference = "SilentlyContinue"   # PS 5.1: Fortschrittsbalken bremst Downloads stark
    try {
        Invoke-WebRequest "https://www.python.org/ftp/python/$v/python-$v-amd64.exe" -OutFile $exe -UseBasicParsing
        # Bis der Installer läuft, darf niemand die Datei austauschen (%TEMP% gehört dem Benutzer, gestartet wird
        # mit Adminrechten): nur Lesen erlauben, erst dann die Signatur prüfen. Das deckt nur diese erste Stufe;
        # was der Installer (WiX Burn) danach entpackt, prüft er selbst per Hash. Start mit RunAs unter der Sperre
        # ist auf echter UAC nicht getestet (Lesen ist freigegeben, mehr braucht der Start nicht).
        $lock = [IO.File]::Open($exe, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try {
            $sig = Get-AuthenticodeSignature -LiteralPath $exe
            if ($sig.Status -ne "Valid" -or
                $sig.SignerCertificate.Subject -notmatch '(^|, )CN=Python Software Foundation(,|$)') {
                throw "Python-Installer ist nicht gültig von der Python Software Foundation signiert ($($sig.Status)) - abgebrochen"
            }
            $a = @("/quiet", "InstallAllUsers=$(if ($Machine) { 1 } else { 0 })", "PrependPath=1",
                   "Include_launcher=1", "Include_test=0")
            # Process statt Start-Process: nur so kommt eine Win32Exception mit Fehlercode (Start-Process meldet
            # alles als InvalidOperationException)
            $si = New-Object Diagnostics.ProcessStartInfo $exe, ($a -join " ")
            $si.UseShellExecute = $true
            if ($Machine) { $si.Verb = "runas" }
            try {
                $p = [Diagnostics.Process]::Start($si)
                $p.WaitForExit()
            } catch [ComponentModel.Win32Exception] {
                $code = $_.Exception.NativeErrorCode
                if ($Machine -and $code -eq 1223) {   # ERROR_CANCELLED: UAC-Abfrage abgelehnt
                    throw "Administratorrechte abgelehnt - Python wurde nicht installiert. Ohne Adminrechte: install.ps1 -SkipSensors (Python nur für diesen Benutzer, ohne Sensor-Helfer)"
                }
                if ($code -eq 32) {   # Freigabeverletzung: Start trotz Lesesperre abgelehnt (nicht erwartet)
                    throw "Python-Installer ließ sich nicht starten (Datei gesperrt). Von Hand: winget install -e --id Python.Python.3.13 --scope machine, dann install.ps1 erneut"
                }
                throw
            }
        } finally { $lock.Dispose() }
        if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {   # 3010 = ok, Neustart empfohlen
            throw "Python-Installation fehlgeschlagen (Code $($p.ExitCode))"
        }
    } finally {
        Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
    }
    Update-SessionPath
}

# versionName der Launcher-App aus dem Manifest (z. B. "4.1") oder $null
function Get-LauncherVersion($root) {
    $m = Join-Path $root "android\AndroidManifest.xml"
    if (-not (Test-Path -LiteralPath $m)) { return $null }
    $hit = Select-String -LiteralPath $m -Pattern 'android:versionName="([^"]+)"' | Select-Object -First 1
    if ($hit) { return $hit.Matches[0].Groups[1].Value }
    return $null
}

# SHA-256 der Signaturzertifikate aus dem APK-Signaturblock (Schema v2/v3 - danach prüft Android ab 7 bzw. 9;
# das alte v1 unter META-INF zählt bei minSdk 30 nicht). Leere Liste = kein v2/v3-Block.
function Get-ApkCertHashes($path) {
    $b = [IO.File]::ReadAllBytes($path)
    $eocd = -1
    for ($i = $b.Length - 22; $i -ge [Math]::Max(0, $b.Length - 65557); $i--) {
        if ([BitConverter]::ToUInt32($b, $i) -eq 0x06054b50) { $eocd = $i; break }
    }
    if ($eocd -lt 0) { return @() }
    $cd = [BitConverter]::ToUInt32($b, $eocd + 16)
    if ($cd -lt 24 -or [Text.Encoding]::ASCII.GetString($b, $cd - 16, 16) -ne "APK Sig Block 42") { return @() }
    $size = [BitConverter]::ToUInt64($b, $cd - 24)
    $start = $cd - $size - 8
    if ($start -lt 0) { return @() }
    $sha = [Security.Cryptography.SHA256]::Create()
    $hashes = @()
    $pos = $start + 8
    while ($pos + 12 -le $cd - 24) {
        $len = [BitConverter]::ToUInt64($b, $pos); $id = [BitConverter]::ToUInt32($b, $pos + 8)
        $val = $pos + 12; $next = $pos + 8 + $len
        if ($id -eq 0x7109871a -or $id -eq 4032000192) {          # v2 bzw. v3 (0xf05368c0 als Dezimalzahl: PS 5.1 liest das Hex-Literal als negatives Int32)
            $p = $val + 4                                           # Länge der Signer-Folge überspringen
            $end = $val + [BitConverter]::ToUInt32($b, $val) + 4
            while ($p + 4 -le $end) {
                $signerLen = [BitConverter]::ToUInt32($b, $p); $s = $p + 4
                $sd = $s + 4                                        # signed data
                $digLen = [BitConverter]::ToUInt32($b, $sd); $certs = $sd + 4 + $digLen
                $certsEnd = $certs + 4 + [BitConverter]::ToUInt32($b, $certs)
                $c = $certs + 4
                if ($c + 4 -le $certsEnd) {                         # erstes Zertifikat = Signierer
                    $cl = [BitConverter]::ToUInt32($b, $c)
                    $hashes += ([BitConverter]::ToString($sha.ComputeHash($b, $c + 4, $cl)) -replace '-', '').ToLower()
                }
                $p = $s + $signerLen
            }
        }
        $pos = $next
    }
    return $hashes
}

# Trägt die APK das Release-Zertifikat (android\release-cert.sha256)? Jede v2/v3-Signatur muss es nennen. Das
# prüft nicht die Signatur selbst (das Zertifikat ist öffentlich) - es fängt Releases mit falschem Schlüssel ab,
# vor Fälschungen schützt die Prüfsumme aus der GitHub-API; Android prüft die Signatur beim Installieren.
function Test-ApkSigner($root, $path) {
    $pinFile = Join-Path $root "android\release-cert.sha256"
    if (-not (Test-Path -LiteralPath $pinFile)) { return $false }
    $pin = ((Get-Content -LiteralPath $pinFile -Raw) -split '\s')[0].Trim().ToLower()
    try { $h = @(Get-ApkCertHashes $path) } catch { return $false }
    return $h.Count -gt 0 -and @($h | Where-Object { $_ -ne $pin }).Count -eq 0
}

# tablet-deck.apk des Releases v<versionName> nach $dest laden. Pflicht: SHA-256 aus der GitHub-API stimmt und
# die APK ist mit dem Release-Schlüssel signiert (Zertifikat im Repo festgehalten). Schreibt daneben
# tablet-deck.apk.version. Gibt $true/$false zurück, wirft nicht.
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
        if ("$($asset.digest)" -notmatch '^sha256:([0-9a-f]{64})$') {
            Write-Host "   Release v$ver nennt keine Prüfsumme - nicht geladen"; return $false
        }
        $want = $Matches[1]
        Write-Host "   lade tablet-deck.apk aus Release v$ver ..."
        New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
        Invoke-WebRequest $asset.browser_download_url -OutFile $tmp -UseBasicParsing -TimeoutSec 120
        if ((Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash -ne $want) {
            Write-Host "   Prüfsumme stimmt nicht - verworfen"; return $false
        }
        if (-not (Test-ApkSigner $root $tmp)) {
            Write-Host "   APK trägt nicht das Release-Zertifikat (android\release-cert.sha256) - verworfen"
            return $false
        }
        Move-Item -Force -LiteralPath $tmp -Destination $dest
        Set-Content -LiteralPath "$dest.version" -Value $ver -Encoding ASCII
        return $true
    } catch {
        Write-Host "   Download fehlgeschlagen: $($_.Exception.Message)"
        return $false
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}
