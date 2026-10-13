#!/usr/bin/env bash
# ==========================================================================
#  Pike - macOS / Linux launcher
#  Creates a virtual environment (first run), installs dependencies and
#  starts the desktop app.
# ==========================================================================
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[Pike] python3 was not found. Please install Python 3.9+ and try again."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "[Pike] Creating virtual environment..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[Pike] Installing dependencies..."
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

echo
echo "[Pike] Starting the app..."
python app.py "$@"