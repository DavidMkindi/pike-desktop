#!/usr/bin/env bash
# Build a Debian/Ubuntu installer for Pike.
#
# Usage: packaging/linux/build_deb.sh <version> [binary] [arch]
set -euo pipefail

VERSION="${1:?usage: build_deb.sh <version> [binary] [arch]}"
BINARY="${2:-dist/Pike}"
ARCH="${3:-amd64}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${REPO_ROOT}"

if [ ! -f "${BINARY}" ]; then
  echo "error: ${BINARY} not found; run build_exe.py first" >&2
  exit 1
fi

OUTPUT="Pike-${VERSION}-Linux-${ARCH}.deb"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

install -d "${WORK}/opt/pike" "${WORK}/usr/bin" \
           "${WORK}/usr/share/applications" \
           "${WORK}/usr/share/icons/hicolor/256x256/apps" \
           "${WORK}/usr/share/doc/pike" \
           "${WORK}/DEBIAN"

install -m 0755 "${BINARY}" "${WORK}/opt/pike/Pike"

cat > "${WORK}/usr/bin/pike" <<'EOF'
#!/bin/sh
exec /opt/pike/Pike "$@"
EOF
chmod 0755 "${WORK}/usr/bin/pike"

cat > "${WORK}/usr/share/applications/pike.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Pike
Comment=Focused desktop AI assistant
Exec=/opt/pike/Pike
Icon=pike
Terminal=false
Categories=Utility;Office;
EOF

python3 packaging/make_png.py static/pike.ico \
  "${WORK}/usr/share/icons/hicolor/256x256/apps/pike.png" || true
cp packaging/linux/README.txt "${WORK}/usr/share/doc/pike/README.txt" 2>/dev/null || true

INSTALLED_SIZE="$(du -sk "${WORK}/opt" "${WORK}/usr" | awk '{s+=$1} END {print s}')"

cat > "${WORK}/DEBIAN/control" <<EOF
Package: pike
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Installed-Size: ${INSTALLED_SIZE}
Maintainer: Pike <noreply@github.com>
Homepage: https://github.com/DavidMkindi/pike-desktop
Description: Pike - a focused desktop AI assistant
 Pike is a small desktop chat client for OpenAI-compatible providers.
EOF

dpkg-deb --build --root-owner-group "${WORK}" "${OUTPUT}"
echo "Built ${OUTPUT}"
