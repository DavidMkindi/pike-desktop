"""Convert the bundled ``.ico`` icon into a PNG for Linux packaging.

Usage
-----
    python packaging/make_png.py static/pike.ico build/pike.png

Pillow is only needed for this conversion; when it is missing the script is a
no-op so that packaging can continue without a custom icon.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: make_png.py <input.ico> <output.png>", file=sys.stderr)
        return 2

    try:
        from PIL import Image  # type: ignore
    except ImportError:
        print("Pillow is not installed; skipping icon generation.", file=sys.stderr)
        return 0

    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    if not source.is_file():
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        try:
            sizes = sorted(image.ico.sizes())  # type: ignore[attr-defined]
            image.size = sizes[-1]
        except Exception:  # noqa: BLE001 - keep whatever frame we have
            pass
        icon = image.convert("RGBA").resize((256, 256), Image.LANCZOS)
        icon.save(target, format="PNG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
