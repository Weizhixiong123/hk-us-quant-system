@echo off
setlocal

cd /d "%~dp0"

set "APP_HOST=127.0.0.1"
set "APP_PORT=8000"
set "PYTHONPATH=%~dp0backend"
set "FRONTEND_DIST_DIR=%~dp0frontend\dist"
set "LIVE_SETTINGS_PATH=%~dp0data\live-settings.json"

if not exist "%~dp0data" mkdir "%~dp0data"
if not exist "%~dp0logs" mkdir "%~dp0logs"

set "PYTHON_EXE=%~dp0runtime\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python runtime was not found.
    echo Run repair-runtime.bat or rebuild the package with runtime included.
    pause
    exit /b 1
  )
  set "PYTHON_EXE=python"
)

echo Starting HK/US Quant System on http://%APP_HOST%:%APP_PORT%
start "" "http://%APP_HOST%:%APP_PORT%"

"%PYTHON_EXE%" -m uvicorn app.main:app --app-dir "%~dp0backend" --host "%APP_HOST%" --port "%APP_PORT%"

echo.
echo Service stopped.
pause
