@echo off
REM ==========================================================================
REM  Pike - Windows launcher
REM  Creates a virtual environment (first run), installs dependencies and
REM  starts the desktop app.
REM ==========================================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [Pike] Python was not found on your PATH.
  echo Install Python 3.9+ from https://www.python.org/downloads/ and try again.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo [Pike] Creating virtual environment...
  python -m venv .venv
)

call ".venv\Scripts\activate.bat"

echo [Pike] Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt

echo.
echo [Pike] Starting the app...
python app.py %*

endlocal
pause