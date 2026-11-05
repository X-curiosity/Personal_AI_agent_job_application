"""Fetch logos for every startup that lacks one (concurrent), then re-export."""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.enrich import fetch_logo
from ingest.store import Store

ROOT = Path(__file__).resolve().parents[1]
LOGO_DIR = ROOT / "vercel-site" / "data" / "logos"


def _one(s: dict) -> tuple[str, str]:
    if s.get("logo_url"):
        return s["startup_id"], s["logo_url"]
    logo = fetch_logo(s.get("website") or "", s["startup_id"], LOGO_DIR, name=s.get("name") or "")
    return s["startup_id"], logo


def main() -> None:
    store = Store()
    startups = store.all_startups()
    todo = [s for s in startups if not s.get("logo_url")]
    print(f"Fetching logos for {len(todo)} of {len(startups)} companies…")
    got = 0
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(_one, s) for s in todo]
        for fut in as_completed(futures):
            sid, logo = fut.result()
            if logo:
                got += 1
                with store._connect() as con:
                    con.execute("UPDATE startups SET logo_url = ? WHERE startup_id = ?", (logo, sid))
    print(f"Fetched {got} logos. {store.counts()}")


if __name__ == "__main__":
    main()
