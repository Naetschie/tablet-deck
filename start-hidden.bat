@echo off
rem Bridge ohne Konsolenfenster starten (Taskleisten-Symbol, Log in bridge.log)
cd /d "%~dp0"
start "" pythonw -m bridge %*
