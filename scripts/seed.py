"""Seed a small, independently-curated list of well-known companies and ingest
their live roles. Each entry names a public ATS board (verifiable on the
company's own career page)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.ats import fetch_board, HTTPX_VENDORS
from ingest.pipeline import classify_role, _jobs_id, _slug, _first_seen, _to_job_row
from ingest.store import Store

# (name, website, country, domain, stage, city, lat, lng, [(vendor, board), ...])
SEED: list[dict] = [
    {"name": "Datadog", "website": "https://www.datadoghq.com", "country": "United States", "domain": "Developer tools", "stage": "public", "office_city": "New York", "latitude": 40.7128, "longitude": -74.0060, "boards": [("greenhouse", "datadog")]},
    {"name": "DoorDash", "website": "https://www.doordash.com", "country": "United States", "domain": "Marketplace", "stage": "public", "office_city": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "boards": [("greenhouse", "doordash")]},
    {"name": "Robinhood", "website": "https://robinhood.com", "country": "United States", "domain": "Fintech", "stage": "public", "office_city": "Menlo Park", "latitude": 37.4529, "longitude": -122.1817, "boards": [("greenhouse", "robinhood")]},
    {"name": "Stripe", "website": "https://stripe.com", "country": "United States", "domain": "Fintech", "stage": "private", "office_city": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "boards": [("greenhouse", "stripe")]},
    {"name": "Figma", "website": "https://www.figma.com", "country": "United States", "domain": "Design tools", "stage": "private", "office_city": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "boards": [("greenhouse", "figma")]},
    {"name": "Twilio", "website": "https://www.twilio.com", "country": "United States", "domain": "Developer tools", "stage": "public", "office_city": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "boards": [("greenhouse", "twilio")]},
    {"name": "Linear", "website": "https://linear.app", "country": "United States", "domain": "Developer tools", "stage": "private", "office_city": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "boards": [("ashby", "linear")]},
    {"name": "Ramp", "website": "https://ramp.com", "country": "United States", "domain": "Fintech", "stage": "private", "office_city": "New York", "latitude": 40.7128, "longitude": -74.0060, "boards": [("ashby", "ramp")]},
    {"name": "Mercury", "website": "https://mercury.com", "country": "United States", "domain": "Fintech", "stage": "private", "office_city": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "boards": [("ashby", "mercury")]},
    {"name": "Anysphere", "website": "https://anysphere.com", "country": "United States", "domain": "AI", "stage": "private", "office_city": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "boards": [("ashby", "anysphere")]},
    {"name": "Perplexity", "website": "https://www.perplexity.ai", "country": "United States", "domain": "AI", "stage": "private", "office_city": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "boards": [("ashby", "perplexity")]},
    {"name": "Netlify", "website": "https://www.netlify.com", "country": "United States", "domain": "Developer tools", "stage": "private", "office_city": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "boards": [("greenhouse", "netlify")]},
    {"name": "Canva", "website": "https://www.canva.com", "country": "Australia", "domain": "Design tools", "stage": "private", "office_city": "Sydney", "latitude": -33.8688, "longitude": 151.2093, "boards": [("lever", "canva")]},
    {"name": "Pigment", "website": "https://www.pigment.com", "country": "France", "domain": "Fintech", "stage": "private", "office_city": "Paris", "latitude": 48.8566, "longitude": 2.3522, "boards": [("lever", "pigment")]},
    {"name": "Fuse Energy", "website": "https://www.fuseenergy.com", "country": "United Kingdom", "domain": "Energy", "stage": "private", "office_city": "London", "latitude": 51.5074, "longitude": -0.1278, "boards": [("workable", "fuseenergy")]},
]


def main() -> None:
    store = Store()
    total_jobs = 0
    for row in SEED:
        startup_id = _slug(row["name"])
        startup = {
            "startup_id": startup_id,
            "name": row["name"],
            "website": row["website"],
            "logo_url": "",
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "office_city": row.get("office_city", ""),
            "country": row["country"],
            "domain_primary": row["domain"],
            "stage": row["stage"],
            "hiring_status": "open_to_talent",
            "team_size_min": None,
            "team_size_max": None,
            "year_founded": None,
            "accelerators": "[]",
            "last_funding_amount": "",
            "claimed": 0,
            "why_interesting": "",
        }
        store.upsert_startup(startup)
        n = 0
        for vendor, board in row["boards"]:
            try:
                openings = fetch_board(vendor, board)
            except Exception as exc:
                print(f"  ! {row['name']} ({vendor}:{board}): {type(exc).__name__}")
                continue
            for op in openings:
                job_id = _jobs_id(startup_id, op.title)
                store.upsert_job(_to_job_row(startup, op, job_id))
                n += 1
        total_jobs += n
        print(f"  {row['name']:16s} -> {n:4d} jobs")
    print(f"\nSeeded {len(SEED)} companies, {total_jobs} jobs. {store.counts()}")


if __name__ == "__main__":
    main()
