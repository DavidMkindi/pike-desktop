@echo off
REM Pike website - one-command launcher (Windows)
setlocal
cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)

call ".venv\Scripts\activate.bat"
echo Installing dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

echo.
echo Starting Pike website at http://127.0.0.1:5000/
echo Press Ctrl+C to stop.
echo.
python app.py %*

endlocal