"""Enrich existing startups with logos and street-level HQ addresses, then re-export.

- Logos: self-hosted under vercel-site/data/logos/ (site icon -> google favicon).
- Geocoding: Nominatim best-effort; only street-level offices are kept.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.enrich import fetch_logo, geocode_hq
from ingest.store import Store

ROOT = Path(__file__).resolve().parents[1]
LOGO_DIR = ROOT / "vercel-site" / "data" / "logos"


def main() -> None:
    store = Store()
    startups = store.all_startups()
    print(f"Enriching {len(startups)} companies…")
    for i, s in enumerate(startups, 1):
        slug = s["startup_id"]
        logo = s.get("logo_url") or ""
        if not logo:
            logo = fetch_logo(s["website"], slug, LOGO_DIR)
        geo = geocode_hq(s["name"], s["office_city"], s["country"])
        address = ""
        lat, lng = s["latitude"], s["longitude"]
        if geo:
            address = geo["address"]
            lat, lng = geo["latitude"], geo["longitude"]
        store.upsert_startup({**s, "logo_url": logo, "address": address, "latitude": lat, "longitude": lng})
        mark = "logo" if logo else "·"
        print(f"  {i:2d}. {s['name']:16s} {mark}  addr={address[:45] or 'city-level'}")
        time.sleep(1.1)  # be polite to Nominatim
    print(f"\nDone. {store.counts()}")


if __name__ == "__main__":
    main()
