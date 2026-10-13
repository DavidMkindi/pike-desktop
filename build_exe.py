"""Build a single-file executable for Pike with PyInstaller.

Usage
-----
    pip install pyinstaller
    python build_exe.py

The result appears in ``dist/Pike`` (``Pike.exe`` on Windows).

This module can also be imported (``from build_exe import build``) by
``build_installer.py`` so the installer build reuses the exact same recipe.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# --- Application metadata (also baked into the exe's version resource) ------- #
APP_NAME = "Pike"
APP_VERSION = "1.0.0"
APP_PUBLISHER = "Pike"
APP_DESCRIPTION = "Pike - a focused desktop AI assistant"
APP_COPYRIGHT = "Copyright (C) 2025 Pike"


def version_file_text(version: str = APP_VERSION) -> str:
    """Return a PyInstaller ``--version-file`` payload for Windows."""
    parts = []
    for chunk in (version.split(".") + ["0", "0", "0", "0"])[:4]:
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    v = tuple(parts)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v},
    prodvers={v},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', '{APP_PUBLISHER}'),
         StringStruct('FileDescription', '{APP_DESCRIPTION}'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', '{APP_NAME}'),
         StringStruct('LegalCopyright', '{APP_COPYRIGHT}'),
         StringStruct('OriginalFilename', '{APP_NAME}.exe'),
         StringStruct('ProductName', '{APP_NAME}'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def write_version_file(version: str = APP_VERSION) -> Path:
    """Write ``version_info.txt`` next to the build scripts."""
    target = ROOT / "version_info.txt"
    target.write_text(version_file_text(version), encoding="utf-8")
    return target


def _require_build_deps() -> bool:
    missing = False
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Install it with:\n\n    pip install pyinstaller\n")
        missing = True
    try:
        import webview  # noqa: F401
    except ImportError:
        print(
            "pywebview is required to build the desktop app:\n\n"
            "    pip install pywebview\n"
        )
        missing = True
    return not missing


def _build_command(version: str, onefile: bool = True) -> list[str]:
    separator = ";" if sys.platform.startswith("win") else ":"
    add_data = [
        f"templates{separator}templates",
        f"static{separator}static",
    ]

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        APP_NAME,
        "--collect-all",
        "webview",
        "--collect-all",
        "flask",
        "--hidden-import",
        "clr_loader",
    ]
    if onefile:
        command.append("--onefile")
    if sys.platform.startswith("win"):
        command.append("--windowed")
        # Bake company/version metadata into the executable.
        command += ["--version-file", str(write_version_file(version))]

    for item in add_data:
        command += ["--add-data", item]

    icon_path = ROOT / "static" / "pike.ico"
    if icon_path.is_file():
        command += ["--icon", str(icon_path)]

    if not onefile:
        # Only bundle runtime assets for onedir; skip the entry script check.
        pass

    command.append(str(ROOT / "app.py"))
    return command


def build(version: str = APP_VERSION, onefile: bool = True, quiet: bool = False) -> Path | None:
    """Build the executable and return its path (or ``None`` on failure)."""
    if not _require_build_deps():
        return None

    command = _build_command(version, onefile=onefile)
    if not quiet:
        print("Building executable...\n", " ".join(command), "\n")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return None

    output = ROOT / "dist" / (f"{APP_NAME}.exe" if sys.platform.startswith("win") else APP_NAME)
    if output.is_file():
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"\nBuilt {output}  ({size_mb:.1f} MB)")
        return output
    print(f"\nBuild finished but {output} was not found.")
    return None


def main() -> int:
    if shutil.which("pyinstaller") is None and not (ROOT / ".venv").exists():
        print("Tip: activate a virtual environment before building to keep the exe small.")
    output = build()
    if output is None:
        return 1
    print(f"\nDone! Your executable is at: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())