#!/usr/bin/env bash
# Pike website - one-command launcher (macOS / Linux)
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing dependencies..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

echo
echo "Starting Pike website at http://127.0.0.1:5000/"
echo "Press Ctrl+C to stop."
echo
exec python app.py "$@"