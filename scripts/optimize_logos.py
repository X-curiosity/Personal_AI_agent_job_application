"""Optimize company logos: convert to compact 128px PNGs (except SVGs, which are
kept — they're the smallest vector format), replacing only when smaller."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from ingest.store import Store

ROOT = Path(__file__).resolve().parents[1]
LOGO_DIR = ROOT / "vercel-site" / "data" / "logos"
MAX_SIZE = 128


def _optimize(path: Path) -> Path | None:
    try:
        im = Image.open(path)
        im = im.convert("RGBA")
        im.thumbnail((MAX_SIZE, MAX_SIZE), Image.LANCZOS)
        out = path.with_suffix(".png")
        im.save(out, "PNG", optimize=True)
        return out
    except Exception:
        return None


def main() -> None:
    store = Store()
    converted = 0
    for f in sorted(LOGO_DIR.iterdir()):
        if f.suffix == ".svg":
            continue  # vector SVG is already the smallest representation
        if f.suffix == ".png":
            if f.stat().st_size < 20_000:
                continue  # already small enough
            out = _optimize(f)
            if out is None or out.stat().st_size >= f.stat().st_size:
                continue
            f.unlink()
            converted += 1
        else:
            # ICO / JPEG / WEBP -> always convert to PNG
            out = _optimize(f)
            if out is None:
                continue
            f.unlink()
            converted += 1
    # update logo_url references to .png where the extension changed
    with store._connect() as con:
        for row in con.execute("SELECT startup_id, logo_url FROM startups WHERE logo_url != ''").fetchall():
            url = row["logo_url"]
            if not url.endswith(".png") and not url.endswith(".svg"):
                new = Path(url).stem + ".png"
                con.execute("UPDATE startups SET logo_url = ? WHERE startup_id = ?", (f"data/logos/{new}", row["startup_id"]))
    print(f"Optimized {converted} logos. {store.counts()}")


if __name__ == "__main__":
    main()
