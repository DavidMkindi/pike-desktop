"""Render the logo at the small sizes the app/extension use and inspect each.

Renders black-on-white at 1x, then prints ASCII of the actual pixels (no
upscaling tricks) so legibility at real size can be judged.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

SVG_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("website/static/img/pike.svg")
SVG = SVG_PATH.read_text("utf-8")
RAMP = " .:-=+*#%@"
SIZES = [14, 16, 18, 20, 24, 28, 32]


def to_ascii(img: Image.Image, cols: int) -> None:
    rows = max(1, int(cols * 0.5 * img.height / img.width))
    small = img.resize((cols, rows), Image.LANCZOS)
    for y in range(rows):
        print("".join(
            RAMP[(255 - small.getpixel((x, y))) * (len(RAMP) - 1) // 255]
            for x in range(cols)
        ))


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for size in SIZES:
            sized = SVG.replace("<svg ", f'<svg width="{size}" height="{size}" fill="none" stroke="#000" ', 1)
            # The partial uses currentColor; force it black for a white background.
            sized = sized.replace("currentColor", "#000000")
            html = (
                "<!doctype html><html><head><style>"
                "html,body{margin:0;background:#fff}"
                ".box{width:40px;height:40px;display:grid;place-items:center}"
                "</style></head><body><div class='box'>" + sized + "</div></body></html>"
            )
            page = browser.new_page(viewport={"width": 40, "height": 40}, device_scale_factor=2)
            page.set_content(html)
            page.locator(".box").screenshot(path="_sz_tmp.png")
            page.close()
            img = Image.open("_sz_tmp.png").convert("L")
            print(f"===== {size}px =====")
            to_ascii(img, 56)
            print()
        browser.close()
    Path("_sz_tmp.png").unlink(missing_ok=True)


if __name__ == "__main__":
    main()