"""Review employer role submissions and approve them into the local store.

Reads `job_submissions` (status 'pending') from Supabase, lets you approve or
reject each, and adds approved roles to the local SQLite store + export.

Requires env vars: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from ingest.ats import Opening
from ingest.pipeline import _jobs_id, _slug, _to_job_row
from ingest.store import Store

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")


def _headers() -> dict:
    return {"apikey": SECRET_KEY, "Authorization": f"Bearer {SECRET_KEY}"}


def list_pending() -> list[dict]:
    r = httpx.get(
        f"{SUPABASE_URL}/rest/v1/job_submissions",
        params={"status": "eq.pending", "order": "created_at.asc"},
        headers=_headers(), timeout=20,
    )
    r.raise_for_status()
    return r.json()


def set_status(sub_id: str, status: str) -> None:
    httpx.patch(
        f"{SUPABASE_URL}/rest/v1/job_submissions",
        params={"id": f"eq.{sub_id}"},
        json={"status": status},
        headers=_headers(), timeout=20,
    ).raise_for_status()


def approve(sub: dict, store: Store) -> None:
    startup_id = _slug(sub["company"])
    startup = {
        "startup_id": startup_id, "name": sub["company"], "website": sub.get("website") or "",
        "logo_url": "", "latitude": None, "longitude": None, "office_city": "",
        "address": "", "country": "",
        "domain_primary": "", "stage": "", "hiring_status": "",
        "team_size_min": None, "team_size_max": None, "year_founded": None,
        "accelerators": "[]", "last_funding_amount": "", "claimed": 0, "why_interesting": "",
    }
    store.upsert_startup(startup)
    op = Opening(
        title=sub["title"], url=sub["apply_url"], location=sub.get("location") or "",
        description=sub.get("description") or "", scrape_method="submission",
        employment=sub.get("employment_type") or "",
    )
    store.upsert_job(_to_job_row(startup, op, _jobs_id(startup_id, op.title)))
    set_status(sub["id"], "approved")


def main() -> None:
    if not SUPABASE_URL or not SECRET_KEY:
        print("Missing env vars. Set SUPABASE_URL and SUPABASE_SECRET_KEY, then retry.")
        return
    store = Store()
    pending = list_pending()
    if not pending:
        print("No pending submissions.")
        return
    for sub in pending:
        print(f"\n=== {sub['company']} — {sub['title']}")
        print(f"  location: {sub.get('location') or '-'} | {sub.get('employment_type') or '-'}")
        print(f"  apply:    {sub['apply_url']}")
        note = sub.get('review_note') or ''
        if note:
            print(f"  AI check: {note}")
        print(f"  desc:     {(sub.get('description') or '')[:200]}")
        choice = input("Approve? [y/N/skip] ").strip().lower()
        if choice == "y":
            approve(sub, store)
            print("  -> approved")
        elif choice == "n":
            set_status(sub["id"], "rejected")
            print("  -> rejected")
        else:
            print("  -> skipped")
    print("\nReview done. Run: .venv/bin/python scripts/export.py")


if __name__ == "__main__":
    main()
