"""Screenshot the brand logo inside the running desktop app."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PORT = "5099"
RAMP = " .:-=+*#%@"


def to_ascii(img: Image.Image, cols: int) -> None:
    rows = max(1, int(cols * 0.5 * img.height / img.width))
    small = img.resize((cols, rows), Image.LANCZOS).convert("L")
    for y in range(rows):
        print("".join(
            RAMP[(255 - small.getpixel((x, y))) * (len(RAMP) - 1) // 255]
            for x in range(cols)
        ))


def main() -> None:
    proc = subprocess.Popen(
        [sys.executable, "app.py", "--server", "--port", PORT],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(4)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            for theme in ("dark", "light"):
                page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=4)
                page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle", timeout=20000)
                page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
                page.wait_for_timeout(150)
                page.locator(".brand").screenshot(path="_brand_tmp.png")
                page.close()
                print(f"=== app sidebar brand ({theme}) ===")
                to_ascii(Image.open("_brand_tmp.png"), 100)
                print()
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    Path("_brand_tmp.png").unlink(missing_ok=True)


if __name__ == "__main__":
    main()