@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
  set "PY_CMD=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python was not found. Install Python 3.11+ first, then run this file again.
    pause
    exit /b 1
  )
  set "PY_CMD=python"
)

echo Rebuilding local Python runtime...
%PY_CMD% -m venv runtime
if errorlevel 1 goto failed

"%~dp0runtime\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed

"%~dp0runtime\Scripts\python.exe" -m pip install -r "%~dp0backend\requirements.txt"
if errorlevel 1 goto failed

echo Runtime repaired successfully.
pause
exit /b 0

:failed
echo Runtime repair failed.
pause
exit /b 1
