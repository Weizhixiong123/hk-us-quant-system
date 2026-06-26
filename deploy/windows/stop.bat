@echo off
setlocal

set "APP_PORT=8000"
set "FOUND="

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%APP_PORT%" ^| findstr "LISTENING"') do (
  set "FOUND=1"
  echo Stopping process %%p on port %APP_PORT%...
  taskkill /PID %%p /F
)

if not defined FOUND (
  echo No service is listening on port %APP_PORT%.
)

pause
