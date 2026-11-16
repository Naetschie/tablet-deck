@echo off
cd /d "%~dp0"
title SC Tablet Bridge
python -m bridge %*
pause
