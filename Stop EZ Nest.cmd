@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Stop EZ Nest.ps1"
if errorlevel 1 pause
