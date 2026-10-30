"""Export a bounded, source-linked European vacancy snapshot for the static site.

Only reviewed public employer-board APIs are read. No LinkedIn or personal data.
Coordinates describe listing cities/country centres, never company headquarters.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from tau_job_application.city_coordinates import geocode_location
from tau_job_application.job_skills import extract_skills
from tau_job_application.role_discovery import DEFAULT_VETTED_COMPANY_BOARDS
from tau_job_application.sources import fetch_public_board_openings

ROOT = Path(__file__).resolve().parents[1]
EUROPE = {"united kingdom", "uk", "england", "germany", "france", "netherlands", "switzerland", "sweden", "denmark", "norway", "finland", "ireland", "spain", "portugal", "italy", "austria", "belgium", "luxembourg", "poland", "czech republic", "czechia", "slovakia", "hungary", "romania", "bulgaria", "greece", "estonia", "latvia", "lithuania", "croatia", "slovenia", "iceland"}
def role_area(title: str) -> str:
    text = title.casefold()
    if "data center" in text or "data centre" in text:
        return "Engineering" if "engineer" in text else "Operations"
    groups = (
        ("Data & AI", ("machine learning", "scientist", "data ", "ai ", "llm")),
        ("Product", ("product manager", "product owner")),
        ("Engineering", ("engineer", "developer", "architect", "security")),
        ("Design", ("designer", "design ", "ux ")),
        ("Finance", ("finance", "financial", "accountant")),
        ("Sales", ("sales", "account executive", "business development")),
        ("People & HR", ("recruit", "people ", "talent ")),
        ("Legal", ("legal", "counsel", "compliance")),
    )
    return next((name for name, words in groups if any(word in text for word in words)), "Operations")


def company_logos() -> dict[str, str]:
    path = ROOT / "vercel-site/data/companies.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("companies", [])
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(row.get("name", "")).casefold(): str(row.get("logo") or "") for row in rows if row.get("name")}


class _Company:
    def __init__(self, name: str, company_type: str) -> None:
        self.name, self.company_type = name, company_type


class _Board:
    def __init__(self, source: str, identifier: str, url: str, name: str, company_type: str) -> None:
        self.source, self.board_identifier, self.board_url = source, identifier, url
        self.company = _Company(name, company_type)


def _iter_boards():
    """Registered sources plus the vetted baseline, deduplicated. An empty
    registry still yields the reviewed default boards."""
    from tau_job_application.job_sources import JobSourceStore
    rows = JobSourceStore().list(enabled_only=True)
    boards = [_Board(r["source"], r["board_identifier"], r["board_url"], r["company"], r["company_type"]) for r in rows]
    seen = {(board.source, board.board_identifier) for board in boards}
    for default in DEFAULT_VETTED_COMPANY_BOARDS:
        if (default.source, default.board_identifier) not in seen:
            boards.append(default)
    return boards


def export(limit: int = 120) -> dict:
    jobs = []
    errors = []
    logos = company_logos()
    boards = _iter_boards()
    for board in boards:
        try:
            openings = fetch_public_board_openings(board.source, board.board_identifier, company=board.company.name)
        except Exception as exc:  # retain source failure without exporting stale claims as live
            errors.append(f"{board.company.name}: {exc}")
            continue
        for opening in openings:
            locations = []
            for raw in re.split(r"\s*[•;|]\s*", opening.get("location") or ""):
                point = geocode_location(raw)
                if not point:
                    continue
                country = raw.strip().split(",")[-1].strip().casefold()
                if country not in EUROPE:
                    continue
                locations.append({"label": raw.strip(), "city": point.label, "country": raw.strip().split(",")[-1].strip(), "latitude": point.latitude, "longitude": point.longitude, "precision": point.precision})
            if not locations or not opening.get("url"):
                continue
            description = re.sub(r"\s+", " ", opening.get("description") or "").strip()
            description = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[email in original advert]", description)[:4000]
            skills = extract_skills(f"{opening['title']} {description}")
            identity = f"{board.company.name}|{opening['source_id']}"
            logo = logos.get(board.company.name.casefold(), "")
            if logo:
                source = ROOT / "vercel-site" / logo
                suffix = source.suffix.lower()
                target_relative = f"data/job-logos/{hashlib.sha256(board.company.name.encode()).hexdigest()[:12]}{suffix}"
                if source.is_file() and suffix in {".png", ".jpg", ".webp", ".gif", ".ico"}:
                    target = ROOT / "vercel-site" / target_relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    logo = target_relative
                else:
                    logo = ""
            jobs.append({
                "id": "job_" + hashlib.sha256(identity.encode()).hexdigest()[:20],
                "logo": logo,
                "title": opening["title"], "company": board.company.name, "companyType": board.company.company_type,
                "url": opening["url"], "source": opening["source"], "boardUrl": board.board_url,
                "area": role_area(opening["title"]), "skills": skills, "description": description,
                "locations": locations, "workplace": opening.get("workplace_type"), "employment": opening.get("employment_type"),
                "sourceTimestamp": opening.get("source_timestamp"), "sourceTimestampKind": opening.get("source_timestamp_kind"),
            })
    jobs.sort(key=lambda job: (job["sourceTimestamp"] or "", job["company"], job["title"]), reverse=True)
    # Keep the bounded preview diverse instead of letting the newest board fill it.
    per_company = max(1, limit // max(1, len(boards)))
    counts: dict[str, int] = {}
    selected = []
    for job in jobs:
        if counts.get(job["company"], 0) >= per_company:
            continue
        selected.append(job)
        counts[job["company"]] = counts.get(job["company"], 0) + 1
    return {"schemaVersion": 1, "exportedAt": datetime.now(UTC).isoformat(), "live": False, "jobs": selected[:limit], "errors": errors}


if __name__ == "__main__":
    payload = export()
    if payload["errors"] or not payload["jobs"]:
        raise SystemExit("Refresh failed; keeping the previous public snapshot: " + " | ".join(payload["errors"]))
    target = ROOT / "vercel-site/data/jobs.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"Exported {len(payload['jobs'])} European vacancies to {target}; source errors: {len(payload['errors'])}")
