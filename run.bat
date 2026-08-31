@echo off
cd /d "%~dp0"
title Traffic Safety Quiz Server

echo Checking server status...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5000/health' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" > nul 2>&1
if not errorlevel 1 goto already_running

set "APP_PYTHON=.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" goto try_fallback
"%APP_PYTHON%" -c "import sys" > nul 2>&1
if not errorlevel 1 goto launch

:try_fallback
set "APP_PYTHON=C:\Users\USER1\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%APP_PYTHON%" goto no_python
set "PYTHONPATH=%CD%\.venv\Lib\site-packages"
"%APP_PYTHON%" -c "import flask" > nul 2>&1
if errorlevel 1 goto no_python

:launch
echo.
echo Starting server. Keep this window open.
echo Student page will open in 2 seconds.
echo Master admin PIN: 1234
echo.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:5000/'"
"%APP_PYTHON%" app.py
echo.
echo Server stopped. Review the error message above.
pause
exit /b 1

:already_running
echo Server is already running. Opening the student page.
start "" "http://127.0.0.1:5000/"
exit /b 0

:no_python
echo.
echo Python is not available.
echo Install Python 3 and run install.bat first.
pause
exit /b 1
