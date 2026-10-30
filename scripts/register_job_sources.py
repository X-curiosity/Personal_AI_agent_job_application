#!/usr/bin/env python3
"""Auto-detect and register employer job sources from the public company catalogue.

Bounded and best-effort: scans a limited batch of company websites for a
Greenhouse/Lever/Ashby/Workable/Recruitee board, then registers each detected
source in the local ``job_sources`` table. Detected sources are then refreshed
by the normal ingestion flow; no jobs are invented here.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tau_job_application.job_sources import JobSource, JobSourceStore, detect_company_ats  # noqa: E402
from tau_job_application.role_folders import _project_root  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="maximum companies to scan")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--database", type=Path, default=_project_root() / ".job_assistant" / "assistant.sqlite")
    parser.add_argument("--only-startups", action="store_true", help="only scan companies typed as startups")
    args = parser.parse_args()

    catalogue = json.loads((_project_root() / "vercel-site" / "data" / "companies.json").read_text(encoding="utf-8"))
    companies = [c for c in catalogue.get("companies", []) if isinstance(c, dict)
                 and str(c.get("website") or "").startswith("https://")]
    if args.only_startups:
        companies = [c for c in companies if c.get("type") == "startup"]
    companies = companies[: args.limit]

    store = JobSourceStore(args.database)
    registered = 0

    def scan(company: dict) -> list[dict]:
        try:
            return detect_company_ats(company["website"])
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        future_map = {pool.submit(scan, company): company for company in companies}
        for future in as_completed(future_map):
            company = future_map[future]
            for found in future.result():
                store.register(JobSource(
                    company=company["name"], source=found["source"], board_identifier=found["board_identifier"],
                    board_url=found["board_url"], company_type=company.get("type") or "unknown",
                    region_hint=company.get("country") or "", website=company["website"], detected_from="catalogue",
                ))
                registered += 1

    print(f"Scanned {len(companies)} companies, registered {registered} sources (total {store.count()})")


if __name__ == "__main__":
    main()
