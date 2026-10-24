"""Build a single-file executable for Pike with PyInstaller.

Usage
-----
    pip install pyinstaller
    python build_exe.py

The result appears in ``dist/``: ``Pike.exe`` on Windows, ``Pike.app`` on
macOS and ``Pike`` on Linux. Windows/Linux builds are single-file; macOS is
built as an onedir ``.app`` bundle (as required for a proper application).

This module can also be imported (``from build_exe import build``) by
``build_installer.py`` so the installer build reuses the exact same recipe.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# --- Application metadata (also baked into the exe's version resource) ------- #
APP_NAME = "Pike"
APP_VERSION = "1.0.2"
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


def _module_available(name: str) -> bool:
    """Return True when *name* can be imported in the current interpreter."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _generate_icns() -> Path | None:
    """Best-effort conversion of ``static/pike.ico`` to a macOS ``.icns``.

    Pillow is only needed for this conversion, so a missing Pillow simply
    means the unsigned app ships without a custom icon.
    """
    source = ROOT / "static" / "pike.ico"
    if not source.is_file():
        return None
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return None
    target = ROOT / "pike.icns"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image.save(target, format="ICNS")
    except Exception:  # noqa: BLE001 - icon conversion is strictly optional
        return None
    return target if target.is_file() else None


def _icon_for_platform() -> Path | None:
    """Return the best icon file for the current platform, if any."""
    if sys.platform.startswith("win"):
        candidate = ROOT / "static" / "pike.ico"
        return candidate if candidate.is_file() else None
    if sys.platform == "darwin":
        bundled = ROOT / "static" / "pike.icns"
        if bundled.is_file():
            return bundled
        return _generate_icns()
    return None  # PyInstaller ignores --icon on Linux.


def _linux_qt_flags() -> list[str]:
    """Bundle the Qt WebEngine stack so Linux builds need no system WebKit."""
    flags: list[str] = []
    for package in ("qtpy", "PyQt6", "PyQt5", "PySide6"):
        if _module_available(package):
            flags += ["--collect-all", package]
    for module in ("PyQt6.QtWebEngineWidgets", "PyQt5.QtWebEngineWidgets"):
        if _module_available(module):
            flags += ["--hidden-import", module]
    return flags


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
    ]
    if onefile:
        command.append("--onefile")

    if sys.platform.startswith("win"):
        command += ["--windowed", "--hidden-import", "clr_loader"]
        # Bake company/version metadata into the executable.
        command += ["--version-file", str(write_version_file(version))]
    elif sys.platform == "darwin":
        # A .app bundle is required for a proper macOS application window.
        command.append("--windowed")
        for framework in ("objc", "Cocoa", "WebKit", "Quartz", "Foundation", "AppKit"):
            if _module_available(framework):
                command += ["--hidden-import", framework]
    else:
        command += _linux_qt_flags()

    for item in add_data:
        command += ["--add-data", item]

    icon_path = _icon_for_platform()
    if icon_path is not None:
        command += ["--icon", str(icon_path)]

    command.append(str(ROOT / "app.py"))
    return command


def _output_path() -> Path:
    """Return the expected PyInstaller output for the current platform."""
    if sys.platform == "darwin":
        bundle = ROOT / "dist" / f"{APP_NAME}.app"
        if bundle.is_dir():
            return bundle
    suffix = ".exe" if sys.platform.startswith("win") else ""
    return ROOT / "dist" / f"{APP_NAME}{suffix}"


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

    output = _output_path()
    if output.exists():
        if output.is_dir():
            print(f"\nBuilt {output}  (application bundle)")
        else:
            size_mb = output.stat().st_size / (1024 * 1024)
            print(f"\nBuilt {output}  ({size_mb:.1f} MB)")
        return output
    print(f"\nBuild finished but {output} was not found.")
    return None


def main() -> int:
    if shutil.which("pyinstaller") is None and not (ROOT / ".venv").exists():
        print("Tip: activate a virtual environment before building to keep the exe small.")
    # macOS .app bundles must be built in onedir mode: onefile + windowed is
    # deprecated by PyInstaller and conflicts with macOS code signing.
    onefile = sys.platform != "darwin"
    output = build(onefile=onefile)
    if output is None:
        return 1
    print(f"\nDone! Your executable is at: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())