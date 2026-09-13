@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_remote.ps1" -OpenBrowser
if errorlevel 1 pause
