"""Re-fetch low-resolution logos (< 64px, i.e. favicons) from better sources,
replacing them only when the new logo is larger (a real logo)."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from ingest.enrich import fetch_logo, fetch_logo_playwright
from ingest.store import Store

ROOT = Path(__file__).resolve().parents[1]
LOGO_DIR = ROOT / "vercel-site" / "data" / "logos"


def _size(path: Path) -> int:
    try:
        with Image.open(path) as im:
            return min(im.size)
    except Exception:
        return 0


def main() -> None:
    store = Store()
    tmp = Path("/tmp/logo_refetch")
    tmp.mkdir(parents=True, exist_ok=True)
    improved = 0
    for s in store.all_startups():
        if not s.get("logo_url"):
            continue
        old_rel = s["logo_url"]
        old_path = LOGO_DIR / Path(old_rel).name
        if not old_path.exists():
            continue
        old_size = _size(old_path)
        if old_size >= 64:
            continue  # already a real logo
        # re-fetch into temp dir
        new_rel = fetch_logo(s.get("website") or "", s["startup_id"], tmp, name=s.get("name") or "")
        if not new_rel and s.get("website"):
            new_rel = fetch_logo_playwright(s["website"], s["startup_id"], tmp)
        if not new_rel:
            print(f"  - {s['name']}: no better source found, keeping {old_size}px")
            continue
        new_path = tmp / Path(new_rel).name
        new_size = _size(new_path)
        if new_size > old_size:
            dest = LOGO_DIR / new_path.name
            shutil.copy(new_path, dest)
            with store._connect() as con:
                con.execute("UPDATE startups SET logo_url = ? WHERE startup_id = ?", (f"data/logos/{dest.name}", s["startup_id"]))
            print(f"  + {s['name']}: {old_size}px -> {new_size}px")
            improved += 1
        else:
            print(f"  = {s['name']}: no improvement ({new_size}px vs {old_size}px), keeping")
        for f in tmp.iterdir():
            f.unlink()
    print(f"\nImproved {improved} logos. {store.counts()}")


if __name__ == "__main__":
    main()
