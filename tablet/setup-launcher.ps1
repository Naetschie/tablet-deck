# Installiert die Launcher-App und richtet das Tablet als Bedienpanel ein (per USB, umkehrbar).
#   - APK installieren (android/build/tablet-deck.apk; vorher: python android/build.py)
#   - als Startbildschirm setzen, Overlay-Berechtigung für den Rücksprung-Griff
#   - Sperrbildschirm aus, Bildschirm an jeder Stromquelle an
# Mit -Companion (Begleit-Modus, Tablet ohne Root): nur APK, Berechtigungen und Kopplung - kein Startbildschirm,
# kein Sperrbildschirm-Eingriff, Browser bleibt, keine feste Ausrichtung per settings (nur WRITE_SETTINGS-Recht).
param([switch]$Companion)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$adb = Join-Path $root "tools\platform-tools\adb.exe"
$apk = Join-Path $root "android\build\tablet-deck.apk"
$pkg = "app.tabletdeck.launcher"

function Adb {
    $ErrorActionPreference = "Continue"
    $out = & $adb @args 2>&1
    if ($LASTEXITCODE -ne 0) { throw "adb $($args -join ' ') fehlgeschlagen: $out" }
    $out
}

if (-not (Test-Path $apk)) { throw "APK fehlt - erst 'python android/build.py' ausführen" }
Adb wait-for-device | Out-Null
Adb install -r $apk | Select-Object -Last 1
if (-not $Companion) { Adb shell cmd package set-home-activity "$pkg/.HomeAlias" | Out-Null }
Adb shell appops set $pkg SYSTEM_ALERT_WINDOW allow
# WLAN-Betrieb: Launcher stellt den Android-Proxy um (USB: Bridge-Proxy, WLAN: direkt)
Adb shell pm grant $pkg android.permission.WRITE_SECURE_SETTINGS
# Feste Ausrichtung: der Launcher stellt sie selbst wieder her (spacedesk schaltet die Drehung ein)
Adb shell appops set $pkg WRITE_SETTINGS allow
Adb shell svc power stayon true
if (-not $Companion) {
    Adb shell locksettings set-disabled true | Out-Null
    # Querformat fest (Android 16 ignoriert App-Vorgaben zur Ausrichtung auf großen Bildschirmen teilweise)
    Adb shell settings put system accelerometer_rotation 0
    Adb shell settings put system user_rotation 1
    # Kein Browser auf dem Tablet, solange SELinux permissive läuft (keine fremden Inhalte, docs/tablet-setup.md)
    & $adb shell pm disable-user --user 0 org.lineageos.jelly 2>&1 | Out-Null   # fehlt die App: egal
}
# Kopplung: Geheimnis des Hubs (secret.key, wird von der Bridge beim ersten Start erzeugt) an den Launcher
$secretFile = Join-Path $root "secret.key"
if (-not (Test-Path $secretFile)) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $s = [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_').TrimEnd('=')
    [IO.File]::WriteAllText($secretFile, "$s`n")
}
$secret = (Get-Content $secretFile -Raw).Trim()
if ($secret -notmatch '^[A-Za-z0-9_-]{32,128}$') { throw "secret.key hat ein ungültiges Format" }
# Kopplung über den PairingReceiver (nur die ADB-Shell darf ihn aufrufen: android.permission.DUMP)
$r = Adb shell am broadcast --include-stopped-packages -n "$pkg/.PairingReceiver" --es deck_secret $secret
if (($r -join " ") -notmatch "result=1") { throw "Kopplung fehlgeschlagen: $r" }
if ($Companion) {
    Adb shell am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "$pkg/.HomeActivity" | Out-Null
    "Launcher eingerichtet (Begleit-Modus, normale App)"
} else {
    Adb shell am start -a android.intent.action.MAIN -c android.intent.category.HOME -n "$pkg/.HomeActivity" | Out-Null
    "Launcher eingerichtet: $(Adb shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME | Select-Object -Last 1)"
}
