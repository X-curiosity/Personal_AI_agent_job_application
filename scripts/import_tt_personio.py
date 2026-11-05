"""Import companies whose jobs use Teamtailor or Personio boards (from the
startupmap reference snapshot), fetch their roles, and store them."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.ats import fetch_personio, fetch_teamtailor
from ingest.pipeline import _jobs_id, _slug, _to_job_row
from ingest.store import Store

BAK = Path("/Users/magbi/Desktop/startupmap-rebuild-backup-20261104-194859")

_FETCH = {"teamtailor": fetch_teamtailor, "personio": fetch_personio}


def _board(vendor: str, url: str) -> str:
    host = urlparse(url).netloc
    if vendor == "personio" and ".jobs.personio" in host:
        return host.split(".")[0]
    if vendor == "teamtailor" and ".teamtailor.com" in host:
        return host.split(".")[0]
    return ""


def _extract() -> dict[tuple[str, str], dict]:
    startups = {s["startup_id"]: s for s in json.load(open(BAK / "sm-startups.json"))}
    boards: dict[tuple[str, str], dict] = {}
    for j in json.load(open(BAK / "sm-jobs.json")):
        method = j.get("scrape_method")
        if method not in ("ats:teamtailor", "ats:personio"):
            continue
        vendor = method.split(":", 1)[1]
        board = _board(vendor, j.get("apply_url") or "")
        s = startups.get(j.get("startup_id") or "", {})
        if board and s.get("name"):
            boards[(vendor, board)] = s
    return boards


def _fetch_one(store: Store, vendor: str, board: str, s: dict) -> tuple[int, int]:
    try:
        openings = _FETCH[vendor](board)
    except Exception:
        return 0, 0
    if not openings:
        return 0, 0
    name = s["name"]
    startup_id = _slug(name)
    def _s(v):
        return v or ""
    startup = {
        "startup_id": startup_id, "name": name, "website": f"https://{board}.teamtailor.com" if vendor == "teamtailor" else f"https://{board}.jobs.personio.com",
        "logo_url": "", "latitude": s.get("latitude"), "longitude": s.get("longitude"),
        "office_city": _s(s.get("office_city")), "address": "", "country": _s(s.get("country")),
        "domain_primary": _s(s.get("domain_primary")), "stage": _s(s.get("stage")),
        "hiring_status": _s(s.get("hiring_status")), "team_size_min": None, "team_size_max": None,
        "year_founded": s.get("year_founded"), "accelerators": "[]",
        "last_funding_amount": "", "claimed": 0, "why_interesting": "",
    }
    store.upsert_startup(startup)
    n = 0
    for op in openings:
        store.upsert_job(_to_job_row(startup, op, _jobs_id(startup_id, op.title)))
        n += 1
    return 1, n


def main() -> None:
    boards = _extract()
    print(f"{len(boards)} teamtailor/personio boards to import")
    store = Store()
    companies = jobs = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_fetch_one, store, v, b, s) for (v, b), s in boards.items()]
        for fut in as_completed(futures):
            c, j = fut.result()
            companies += c
            jobs += j
    print(f"Fetched {jobs} roles across {companies} companies. {store.counts()}")


if __name__ == "__main__":
    main()
