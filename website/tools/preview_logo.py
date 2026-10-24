"""Render an SVG to PNG on several backgrounds so the logo can be eyeballed.

Usage:  python website/tools/preview_logo.py path/to/logo.svg out.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BG = [
    ("white", "#ffffff"),
    ("black", "#000000"),
    ("grey", "#8a8a8a"),
]


def main() -> None:
    svg_path = Path(sys.argv[1]).resolve()
    out_path = Path(sys.argv[2]).resolve()
    svg = svg_path.read_text("utf-8")

    cells = "".join(
        f'<div class="cell" style="background:{color}">{svg}</div>'
        for _, color in BG
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
      * {{ box-sizing: border-box; }}
      body {{ margin:0; padding:24px; background:#c9c9c9; font-family:sans-serif; }}
      .row {{ display:flex; gap:20px; align-items:center; justify-content:center; }}
      .cell {{ width:260px; height:260px; display:flex; align-items:center; justify-content:center; border-radius:8px; }}
      .cell svg {{ width:200px; height:200px; }}
      .small {{ display:flex; gap:16px; margin-top:24px; align-items:center; justify-content:center; }}
      .small .cell {{ width:64px; height:64px; }}
      .small .cell svg {{ width:48px; height:48px; }}
    </style></head><body>
      <div class="row">{cells}</div>
      <div class="small">{cells}</div>
    </body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 900, "height": 780}, device_scale_factor=2)
        page.set_content(html)
        page.screenshot(path=str(out_path))
        browser.close()
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()