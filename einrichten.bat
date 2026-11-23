@echo off
rem Tablet Deck: gefuehrte Einrichtung (Doppelklick). Umgeht die Ausfuehrungsrichtlinie nur fuer diesen Aufruf.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Interactive %*
echo.
pause
