"""Build a Windows installer (setup .exe) for Pike.

This wraps the PyInstaller one-file executable produced by :mod:`build_exe`
into a proper Inno Setup installer with Start Menu / desktop shortcuts and an
uninstaller.

Usage
-----
    # 1. Make sure the app exe exists (or let this script build it):
    python build_exe.py

    # 2. Create the installer:
    python build_installer.py

    # Build the exe and the installer in one go:
    python build_installer.py --build-exe

Output
------
    installer/Output/Pike-<version>-Setup.exe

Requirements
------------
* Windows
* `Inno Setup 6 <https://jrsoftware.org/isdl.php>`_ (provides ``ISCC.exe``).
  Install with ``winget install JRSoftware.InnoSetup`` or Chocolatey, or let
  the GitHub Actions workflow do it for you.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INSTALLER_DIR = ROOT / "installer"
ISS_FILE = INSTALLER_DIR / "pike.iss"
DIST_EXE = ROOT / "dist" / "Pike.exe"

# Keep in sync with build_exe.py / config.py.
APP_VERSION = "1.0.2"
APP_PUBLISHER = "Pike"
APP_URL = "https://github.com/DavidMkindi/pike-desktop"


def find_iscc() -> Path | None:
    """Locate the Inno Setup command-line compiler (``ISCC.exe``)."""
    # 1. Already on PATH.
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return Path(found)

    # 2. Standard install locations.
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    # 3. Chocolatey shim.
    choco = Path(r"C:\ProgramData\chocolatey\bin\ISCC.exe")
    if choco.is_file():
        return choco
    return None


def _iscc_defines(version: str) -> list[str]:
    return [
        f"/DAppVersion={version}",
        f"/DAppPublisher={APP_PUBLISHER}",
        f"/DAppUrl={APP_URL}",
        f"/DSourceExe={DIST_EXE}",
    ]


def build_installer(version: str = APP_VERSION, build_exe: bool = False) -> Path | None:
    """Compile the Inno Setup script and return the resulting setup exe."""
    if not sys.platform.startswith("win"):
        print("The Windows installer can only be built on Windows.")
        return None

    if build_exe or not DIST_EXE.is_file():
        print("Building the application executable first...\n")
        import build_exe as builder

        if builder.build(version) is None:
            print("Failed to build Pike.exe; aborting installer build.")
            return None

    iscc = find_iscc()
    if iscc is None:
        print(
            "Inno Setup was not found (ISCC.exe).\n"
            "Install it, then re-run this script:\n\n"
            "    winget install -e --id JRSoftware.InnoSetup\n"
            "    # or:  choco install innosetup -y\n"
        )
        return None

    command = [str(iscc), *_iscc_defines(version), str(ISS_FILE)]
    print("Building installer...\n", " ".join(command), "\n")
    result = subprocess.run(command, cwd=INSTALLER_DIR)
    if result.returncode != 0:
        print("Inno Setup reported an error.")
        return None

    output = INSTALLER_DIR / "Output" / f"Pike-{version}-Setup.exe"
    if output.is_file():
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"\nBuilt installer: {output}  ({size_mb:.1f} MB)")
        return output
    print(f"Installer finished but {output} was not found.")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Pike Windows installer")
    parser.add_argument("--version", default=APP_VERSION, help="Version string (default: %(default)s)")
    parser.add_argument(
        "--build-exe",
        action="store_true",
        help="Run build_exe.py first to (re)build Pike.exe",
    )
    args = parser.parse_args()

    output = build_installer(args.version, build_exe=args.build_exe)
    if output is None:
        return 1
    print(f"\nDone! Windows setup file: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())