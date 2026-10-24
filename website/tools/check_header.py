"""Screenshot the live website header and print the brand mark as ASCII.

Usage:  python website/tools/check_header.py [url]
"""
from __future__ import annotations

import sys

from PIL import Image
from playwright.sync_api import sync_playwright

RAMP = " .:-=+*#%@"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000/"


def to_ascii(img: Image.Image, cols: int) -> None:
    rows = max(1, int(cols * 0.5 * img.height / img.width))
    small = img.resize((cols, rows), Image.LANCZOS).convert("L")
    for y in range(rows):
        print("".join(
            RAMP[(255 - small.getpixel((x, y))) * (len(RAMP) - 1) // 255]
            for x in range(cols)
        ))


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for theme in ("dark", "light"):
            page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=3)
            page.goto(URL, wait_until="networkidle")
            page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
            page.wait_for_timeout(120)
            page.locator(".brand").screenshot(path="_header_tmp.png")
            page.close()
            print(f"=== header brand ({theme} theme) ===")
            to_ascii(Image.open("_header_tmp.png"), 96)
            print()
        browser.close()
    import pathlib
    pathlib.Path("_header_tmp.png").unlink(missing_ok=True)


if __name__ == "__main__":
    main()