@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if exist "%~dp0eznest.exe" (
  start "" "%~dp0eznest.exe" --web
  exit /b 0
)

set "PY=%~dp0.local\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Setting up eznest. This only happens the first time.
  where py >nul 2>&1
  if errorlevel 1 goto needpython
  py -3.12 -c "import sys,struct; raise SystemExit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 else 1)"
  if errorlevel 1 goto needpython
  py -3.12 -m venv "%~dp0.local\venv"
  if errorlevel 1 goto needpython
  "%PY%" -m pip install -r "%~dp0requirements.txt"
  if errorlevel 1 (
    echo Setup stopped. Leave this window open and ask for help.
    pause
    exit /b 1
  )
)

start "eznest" /min "%PY%" "%~dp0launcher.py" --web
exit /b 0

:needpython
echo eznest needs the packaged folder, or 64-bit Python 3.12.
echo Double-click this file in the folder that contains eznest.exe.
pause
exit /b 1
