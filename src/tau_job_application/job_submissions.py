"""Employer/operator job submissions: a validated inbox merged into the snapshot.

The first step of the employer self-serve path without a hosted portal: a
reviewed JSON inbox of job submissions (title, company, URL, location,
description) that the public export merges in. Every record is validated and
deduplicated by URL; nothing here crawls or fabricates a listing.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

SUBMISSIONS_PATH = Path(__file__).resolve().parents[2] / "vercel-site" / "data" / "submitted_jobs.json"


def validate_submission(data: dict) -> dict:
    title = str(data.get("title") or "").strip()
    company = str(data.get("company") or "").strip()
    url = str(data.get("url") or "").strip()
    location = str(data.get("location") or "").strip()
    description = str(data.get("description") or "").strip()
    if not title or not company or not url.startswith("https://") or not location:
        raise ValueError("A submission needs title, company, an HTTPS url, and a location")
    return {
        "title": title[:300], "company": company[:160], "url": url, "location": location[:300],
        "description": description[:4000],
        "source": "Employer submission",
        "source_id": "sub_" + hashlib.sha256(url.encode()).hexdigest()[:20],
        "source_timestamp": str(data.get("submittedAt") or datetime.now(UTC).isoformat()),
        "source_timestamp_kind": "created",
    }


def load_submissions(path: Path = SUBMISSIONS_PATH) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("jobs", []) if isinstance(payload, dict) else []
    return [validate_submission(row) for row in rows if isinstance(row, dict)]


def add_submission(path: Path, data: dict) -> dict:
    record = validate_submission({**data, "submittedAt": datetime.now(UTC).isoformat()})
    payload: dict = {"jobs": []}
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded
    existing = payload.get("jobs", [])
    if any(str(job.get("url")) == record["url"] for job in existing):
        raise ValueError("A submission with this URL already exists")
    payload["jobs"] = [*existing, record]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record
