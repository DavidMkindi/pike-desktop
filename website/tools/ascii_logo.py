"""Render an SVG and print it as ASCII art so the shape can be inspected in text.

Usage:  python website/tools/ascii_logo.py path/to/logo.svg [width] [bg]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

RAMP = " .:-=+*#%@"


def render(svg: str, bg: str, size: int = 480) -> Image.Image:
    html = (
        "<!doctype html><html><head><style>"
        "html,body{margin:0;padding:0}"
        f".wrap{{width:{size}px;height:{size}px;background:{bg};"
        "display:flex;align-items:center;justify-content:center}"
        f".wrap svg{{width:{int(size*0.86)}px;height:{int(size*0.86)}px}}"
        "</style></head><body>"
        f'<div class="wrap">{svg}</div></body></html>'
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": size, "height": size})
        page.set_content(html)
        page.screenshot(path="_ascii_tmp.png")
        browser.close()
    return Image.open("_ascii_tmp.png").convert("L")


def to_ascii(img: Image.Image, cols: int) -> list[str]:
    aspect = 0.5  # terminal chars are ~2x tall
    rows = max(1, int(cols * aspect * img.height / img.width))
    small = img.resize((cols, rows), Image.LANCZOS)
    lines = []
    for y in range(rows):
        line = "".join(
            RAMP[(255 - small.getpixel((x, y))) * (len(RAMP) - 1) // 255]
            for x in range(cols)
        )
        lines.append(line)
    return lines


def main() -> None:
    svg = Path(sys.argv[1]).read_text("utf-8")
    cols = int(sys.argv[2]) if len(sys.argv) > 2 else 72
    bg = sys.argv[3] if len(sys.argv) > 3 else "#ffffff"
    img = render(svg, bg)
    print(f"--- {sys.argv[1]}  ({cols} cols, bg {bg}) ---")
    for line in to_ascii(img, cols):
        print(line)
    Path("_ascii_tmp.png").unlink(missing_ok=True)


if __name__ == "__main__":
    main()