"""Re-import the auto-detected ATS board registry from the pre-rebuild backup and
fetch live roles from each, restoring broad company coverage."""
from __future__ import annotations

import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.ats import FETCHERS, fetch_board
from ingest.pipeline import _jobs_id, _slug, _to_job_row
from ingest.store import Store

BACKUP = Path("/Users/magbi/Desktop/startupmap-rebuild-backup-20261104-194859/.job_assistant/assistant.sqlite")

_COUNTRY_HINTS = {"europe", "asia", "africa", "oceania", "americas", "north america", "south america", "global", "worldwide"}

# Country -> approximate centre, for placing a company on the map when only its
# country is known (jobs carry their own city-level location).
_COUNTRY_COORDS = {
    "United States": (39.8, -98.6), "United Kingdom": (54.0, -2.0), "Germany": (51.1, 10.4),
    "France": (46.6, 2.2), "Netherlands": (52.2, 5.3), "Sweden": (60.1, 14.6),
    "Belgium": (50.5, 4.5), "Switzerland": (46.8, 8.2), "Spain": (40.2, -3.6),
    "Italy": (42.8, 12.5), "Denmark": (56.3, 9.5), "Norway": (60.5, 8.5),
    "Finland": (64.0, 26.0), "Ireland": (53.2, -8.1), "Austria": (47.6, 14.1),
    "Portugal": (39.5, -8.0), "Poland": (52.1, 19.4), "Estonia": (58.6, 25.0),
    "Latvia": (56.9, 24.6), "Lithuania": (55.2, 24.0), "Czech Republic": (49.8, 15.5),
    "Australia": (-25.3, 133.8), "Canada": (56.1, -106.3), "Singapore": (1.35, 103.8),
    "India": (20.6, 79.0), "Israel": (31.0, 34.8), "Japan": (36.2, 138.3),
    "Luxembourg": (49.8, 6.1), "Iceland": (64.9, -18.0), "Romania": (45.9, 25.0),
    "Greece": (39.1, 22.0), "Hungary": (47.2, 19.5), "Bulgaria": (42.7, 25.5),
    "Croatia": (45.1, 15.2), "Slovenia": (46.1, 15.0), "Slovakia": (48.7, 19.7),
    "Ukraine": (49.0, 31.4), "Turkey": (39.0, 35.2), "United Arab Emirates": (23.4, 53.8),
}


def _country(region_hint: str) -> str:
    hint = (region_hint or "").strip()
    if not hint or hint.casefold() in _COUNTRY_HINTS:
        return ""
    return hint


def _fetch_one(store: Store, row: dict) -> tuple[int, int]:
    vendor = row["source"].casefold()
    if vendor not in FETCHERS:
        return 0, 0
    name = row["company"].strip()
    if not name:
        return 0, 0
    startup_id = _slug(name)
    country = _country(row.get("region_hint") or "")
    lat, lng = _COUNTRY_COORDS.get(country, (None, None))
    startup = {
        "startup_id": startup_id, "name": name, "website": row.get("website") or "",
        "logo_url": "", "latitude": lat, "longitude": lng, "office_city": "",
        "address": "", "country": country,
        "domain_primary": "", "stage": "", "hiring_status": "",
        "team_size_min": None, "team_size_max": None, "year_founded": None,
        "accelerators": "[]", "last_funding_amount": "", "claimed": 0, "why_interesting": "",
    }
    try:
        openings = fetch_board(vendor, row["board_identifier"])
    except Exception:
        return 0, 0
    if not openings:
        return 0, 0
    store.upsert_startup(startup)
    n = 0
    for op in openings:
        job_id = _jobs_id(startup_id, op.title)
        store.upsert_job(_to_job_row(startup, op, job_id))
        n += 1
    return 1, n


def main() -> None:
    old = sqlite3.connect(BACKUP)
    old.row_factory = sqlite3.Row
    rows = [dict(r) for r in old.execute("SELECT * FROM job_sources WHERE enabled = 1").fetchall()]
    print(f"Importing {len(rows)} registered boards…")
    store = Store()
    companies = jobs = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_fetch_one, store, r) for r in rows]
        for fut in as_completed(futures):
            c, j = fut.result()
            companies += c
            jobs += j
    print(f"Fetched {jobs} roles across {companies} companies. {store.counts()}")


if __name__ == "__main__":
    main()
