#!/usr/bin/env bash
# Build a portable AppImage for Pike.
#
# Usage: packaging/linux/build_appimage.sh <version> [binary] [arch]
set -euo pipefail

VERSION="${1:?usage: build_appimage.sh <version> [binary] [arch]}"
BINARY="${2:-dist/Pike}"
ARCH="${3:-x86_64}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${REPO_ROOT}"

if [ ! -f "${BINARY}" ]; then
  echo "error: ${BINARY} not found; run build_exe.py first" >&2
  exit 1
fi

OUTPUT="Pike-${VERSION}-Linux-${ARCH}.AppImage"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

APPDIR="${WORK}/Pike.AppDir"
install -d "${APPDIR}/usr/bin" \
           "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

install -m 0755 "${BINARY}" "${APPDIR}/usr/bin/Pike"
python3 packaging/make_png.py static/pike.ico "${APPDIR}/pike.png" || true
if [ -f "${APPDIR}/pike.png" ]; then
  cp "${APPDIR}/pike.png" \
     "${APPDIR}/usr/share/icons/hicolor/256x256/apps/pike.png"
fi

cat > "${APPDIR}/pike.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Pike
Comment=Focused desktop AI assistant
Exec=Pike
Icon=pike
Terminal=false
Categories=Utility;Office;
X-AppImage-Version=${VERSION}
EOF

cat > "${APPDIR}/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "${HERE}/usr/bin/Pike" "$@"
EOF
chmod 0755 "${APPDIR}/AppRun"

TOOL="${WORK}/appimagetool.AppImage"
curl -fsSL -o "${TOOL}" \
  "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage"
chmod +x "${TOOL}"

ARCH="${ARCH}" "${TOOL}" --appimage-extract-and-run "${APPDIR}" "${OUTPUT}"
echo "Built ${OUTPUT}"
