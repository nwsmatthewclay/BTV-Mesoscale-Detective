@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo Portable Python runtime not found.
  echo Please extract the entire BTV-NSHARP folder before launching.
  pause
  exit /b 1
)
"runtime\python.exe" "launcher.py"
if errorlevel 1 (
  echo.
  echo BTV NSHARP exited with an error. Check the Logs folder if available.
  pause
)
