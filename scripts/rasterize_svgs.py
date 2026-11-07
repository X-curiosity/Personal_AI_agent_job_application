"""Rasterize all SVG logos to PNG (128px) so they render consistently in <img>
tags (SVGs using external refs/fonts/currentColor can fail to render)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cairosvg

from ingest.store import Store

ROOT = Path(__file__).resolve().parents[1]
LOGO_DIR = ROOT / "vercel-site" / "data" / "logos"
SIZE = 128


def main() -> None:
    store = Store()
    svgs = list(LOGO_DIR.glob("*.svg"))
    converted = failed = 0
    for svg in svgs:
        png = svg.with_suffix(".png")
        try:
            cairosvg.svg2png(url=str(svg), write_to=str(png), output_width=SIZE, output_height=SIZE)
            svg.unlink()
            converted += 1
        except Exception as exc:
            failed += 1
            print(f"  ! {svg.name}: {type(exc).__name__} {str(exc)[:70]}")
    with store._connect() as con:
        con.execute("UPDATE startups SET logo_url = replace(logo_url, '.svg', '.png') WHERE logo_url LIKE '%.svg'")
    print(f"Converted {converted} SVGs to PNG, {failed} failed. {store.counts()}")


if __name__ == "__main__":
    main()
