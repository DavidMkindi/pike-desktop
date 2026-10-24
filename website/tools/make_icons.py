"""Generate raster icon assets (PNG + multi-size ICO) from an SVG logo.

Uses headless Chrome via Playwright to rasterise, then Pillow to write the
PNG and ICO files. Run from the repository root:

    python website/tools/make_icons.py

Outputs (classic black & white tile):
    static/pike.ico                      (Windows app / PyInstaller)
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
TILE_SVG = ROOT / "website" / "tools" / "logo-icon.svg"

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def render_png(svg: str, size: int, background: str = "transparent") -> Image.Image:
    html = (
        "<!doctype html><html><head><style>"
        f"html,body{{margin:0;width:{size}px;height:{size}px;background:{background}}}"
        f"svg{{display:block;width:{size}px;height:{size}px}}"
        "</style></head><body>" + svg + "</body></html>"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
        page.set_content(html)
        png = page.screenshot(omit_background=True)
        browser.close()
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main() -> None:
    if not TILE_SVG.is_file():
        raise SystemExit(f"missing logo: {TILE_SVG}")
    svg = TILE_SVG.read_text("utf-8")

    # Render the largest size once, then downscale for the rest.
    master = render_png(svg, 256)

    outputs: list[Path] = []

    ico_path = ROOT / "static" / "pike.ico"
    frames = [master.resize((s, s), Image.LANCZOS) for s in ICO_SIZES]
    frames[-1].save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    outputs.append(ico_path)

    for path in outputs:
        rel = path.relative_to(ROOT)
        print(f"wrote {rel}  ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()