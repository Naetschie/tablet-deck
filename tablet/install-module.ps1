# Installiert ein Magisk-Modul (Ordner mit module.prop) nach /data/adb/modules/<id>.
# Voraussetzung: Tablet per USB, Magisk aktiv, "Rooted debugging" an. Wirksam nach Neustart (-Reboot).
# Beispiel: tablet\install-module.ps1 tablet\chargectl\module -Reboot
param([Parameter(Mandatory)][string]$ModuleDir, [switch]$Reboot)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$adb = Join-Path $root "tools\platform-tools\adb.exe"
$src = (Resolve-Path $ModuleDir).Path

function Adb {
    $ErrorActionPreference = "Continue"   # PS 5.1: stderr-Zeilen ("daemon starting") nicht als Abbruch werten
    $out = & $adb @args 2>&1
    if ($LASTEXITCODE -ne 0) { throw "adb $($args -join ' ') fehlgeschlagen: $out" }
    $out
}

$id = (Get-Content (Join-Path $src "module.prop") | Where-Object { $_ -match '^id=' }) -replace '^id=', ''
if ($id -notmatch '^[a-zA-Z][a-zA-Z0-9._-]+$') { throw "ungültige Modul-id '$id'" }
# Dateien müssen LF-Zeilenenden haben (CR würde Shell bzw. magiskpolicy auf dem Tablet stören)
Get-ChildItem $src -File | ForEach-Object {
    if ([IO.File]::ReadAllBytes($_.FullName) -contains 13) { throw "$($_.Name) enthält CR-Zeilenenden" }
}
$tmp = "/data/local/tmp/mod_$id"
Adb root | Out-Null
Adb wait-for-device | Out-Null
if ((Adb shell id -u).Trim() -ne "0") { throw "adb läuft nicht als root - 'Rooted debugging' am Tablet einschalten" }
Adb shell "rm -rf $tmp && mkdir -p $tmp" | Out-Null
Get-ChildItem $src -File | ForEach-Object { Adb push $_.FullName "$tmp/$($_.Name)" | Out-Null }
Adb shell "M=/data/adb/modules/$id; rm -rf `$M && mkdir -p `$M && cp $tmp/* `$M/ && chmod 644 `$M/* && { chmod 755 `$M/*.sh 2>/dev/null || true; } && chown -R 0:0 `$M && rm -rf $tmp && ls -la `$M"
# Wie Magisks copy_preinit_files: Regeln aller aktiven Module in die Preinit-Datei, die magiskinit früh lädt
Adb shell 'P=/debug_ramdisk/.magisk/preinit; [ -d $P ] || { echo "kein Preinit-Verzeichnis"; exit 1; }; for r in /data/adb/modules*/*/sepolicy.rule; do [ -f "$r" ] || continue; D=${r%/*}; [ -f $D/disable ] || [ -f $D/remove ] || [ -f $D/update ] || { cat $r; echo; }; done > $P/sepolicy.rule; echo "preinit sepolicy.rule: $(wc -l < $P/sepolicy.rule) Zeilen"'
if ($Reboot) { Adb reboot | Out-Null; "Modul '$id' installiert, Tablet startet neu." }
else { "Modul '$id' installiert. Aktiv nach dem nächsten Neustart (oder mit -Reboot)." }
