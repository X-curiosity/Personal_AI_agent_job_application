"""Ingestion pipeline: detect ATS -> fetch openings -> classify -> store."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from .ats import Opening, detect_company_ats, fetch_board, HTTPX_VENDORS
from .store import Store

# Role taxonomy mirrors startupmap.one's `type` field.
_ROLE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Engineering", ("engineer", "developer", "software", "devops", "backend", "frontend", "fullstack", "full-stack", "ml ", "machine learning", "data scientist", "data engineer", "security", "sre", "qa ", "architect", "embedded", "hardware", "robotics", "c++", "python", "rust", "golang", "platform engineer")),
    ("Product", ("product manager", "product owner", "product lead", "head of product", "pm ")),
    ("Design", ("designer", "design lead", "ux", "ui ", "product design", "brand designer")),
    ("Sales", ("sales", "account executive", "business development", "sdr", "bdr", "gtm", "go-to-market", "growth", "revenue", "partnerships", "account manager")),
    ("Customer Success", ("customer success", "customer experience", "account manager", "onboarding", "support engineer", "support specialist", "solutions engineer", "solutions architect", "implementation")),
    ("Operations", ("operation", "ops ", "office manager", "executive assistant", "chief of staff", "supply chain", "logistics", "procurement", "facilities", "compliance manager", "project manager", "program manager")),
    ("Finance", ("finance", "financial", "accountant", "controller", "fp&a", "treasury", "investor relations", "fund accountant")),
    ("Legal", ("legal", "counsel", "paralegal", "compliance officer", "compliance analyst")),
    ("People", ("people ", "people operations", "people ops", "hr ", "human resources", "recruiter", "talent ", "recruiting", "people partner", "people team")),
    ("Marketing", ("marketing", "seo", "content", "social media", "brand", "communications", "growth marketer", "pr ", "copywriter")),
)


def classify_role(title: str) -> list[str]:
    """Return startupmap-style role categories for a job title."""
    text = (" " + (title or "").lower() + " ")
    out = []
    for category, words in _ROLE_GROUPS:
        if any(w in text for w in words):
            out.append(category)
    if "intern" in text or "internship" in text:
        out.append("Internship")
    if not out:
        out.append("Other")
    return out


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return value or "unknown"


def _jobs_id(startup_id: str, title: str) -> str:
    return f"{startup_id}-{_slug(title)}"


def _first_seen() -> str:
    return datetime.now(timezone.utc).isoformat()


def ingest_startup(store: Store, startup: dict) -> list[dict]:
    """Detect and fetch jobs for one startup; returns stored job dicts."""
    website = startup.get("website", "")
    if not website.startswith("https://"):
        return []
    try:
        boards = detect_company_ats(website)
    except Exception:
        boards = []
    stored = []
    seen_ids: set[str] = set()
    if not boards:
        return []
    for board in boards:
        vendor = board["vendor"]
        identifier = board["identifier"]
        try:
            if vendor in HTTPX_VENDORS:
                continue  # html-scrape vendors handled by the scraper stage
            openings = fetch_board(vendor, identifier)
        except Exception:
            continue
        for op in openings:
            job_id = _jobs_id(startup["startup_id"], op.title)
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            row = _to_job_row(startup, op, job_id)
            store.upsert_job(row)
            stored.append(row)
    # any jobs were seen -> hiring signal
    if seen_ids:
        store.upsert_startup({**startup, "hiring_status": startup.get("hiring_status") or "open_to_talent"})
    return stored


def _to_job_row(startup: dict, op: Opening, job_id: str) -> dict:
    types = classify_role(op.title)
    return {
        "jobs_id": job_id,
        "startup_id": startup["startup_id"],
        "job_title": op.title,
        "job_country": startup.get("country", ""),
        "location_display": op.location or startup.get("office_city", ""),
        "type": json.dumps(types),
        "apply_url": op.url,
        "scrape_method": op.scrape_method,
        "is_remote": int(bool(op.workplace and op.workplace.lower() == "remote")),
        "workplace_type": op.workplace,
        "exp_min": None,
        "exp_max": None,
        "posted_at": op.posted_at,
        "first_seen_at": _first_seen(),
        "visible": 1,
        "description": op.description,
    }


def ingest_many(startups: list[dict], store: Store, *, on_progress=None) -> dict:
    total = {"startups": 0, "jobs": 0, "methods": {}}
    for i, startup in enumerate(startups, 1):
        rows = ingest_startup(store, startup)
        if rows:
            total["startups"] += 1
            total["jobs"] += len(rows)
            for r in rows:
                total["methods"][r["scrape_method"]] = total["methods"].get(r["scrape_method"], 0) + 1
        if on_progress:
            on_progress(i, len(startups), startup.get("name", ""), len(rows))
    return total
