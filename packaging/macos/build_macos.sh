#!/usr/bin/env bash
# Package dist/Pike.app into .dmg and .pkg installers.
#
# Usage: packaging/macos/build_macos.sh <version> <arch> [app]
set -euo pipefail

VERSION="${1:?usage: build_macos.sh <version> <arch> [app]}"
ARCH="${2:?usage: build_macos.sh <version> <arch> [app]}"
APP="${3:-dist/Pike.app}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${REPO_ROOT}"

if [ ! -d "${APP}" ]; then
  echo "error: ${APP} not found; run build_exe.py first" >&2
  exit 1
fi

# Ad-hoc signature so macOS treats the bundle as a consistent application.
codesign --force --deep --sign - "${APP}" || true

# --- Disk image (.dmg) ----------------------------------------------------- #
DMG="Pike-${VERSION}-macOS-${ARCH}.dmg"
STAGE="$(mktemp -d)"
cp -R "${APP}" "${STAGE}/Pike.app"
ln -s /Applications "${STAGE}/Applications"
cp packaging/macos/README.txt "${STAGE}/README.txt"
rm -f "${DMG}"
hdiutil create -volname "Pike" -srcfolder "${STAGE}" -ov -format UDZO "${DMG}"
rm -rf "${STAGE}"

# --- Installer package (.pkg) ---------------------------------------------- #
PKG="Pike-${VERSION}-macOS-${ARCH}.pkg"
rm -f "${PKG}"
pkgbuild --component "${APP}" \
  --install-location /Applications \
  --identifier com.pike.desktop \
  --version "${VERSION}" \
  "${PKG}"

echo "Built ${DMG} and ${PKG}"
