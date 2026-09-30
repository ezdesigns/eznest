@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start EZ Nest.ps1"
if errorlevel 1 pause
