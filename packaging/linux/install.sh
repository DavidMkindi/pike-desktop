#!/usr/bin/env bash
# Install the bundled Pike binary for the current user.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"

mkdir -p "${BIN_DIR}" "${APP_DIR}"
install -m 0755 "${HERE}/Pike" "${BIN_DIR}/pike"

cat > "${APP_DIR}/pike.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Pike
Comment=Focused desktop AI assistant
Exec=pike
Terminal=false
Categories=Utility;Office;
EOF

echo "Installed Pike to ${BIN_DIR}/pike"
echo "Make sure ${BIN_DIR} is on your PATH, then launch 'Pike' from your menu."
