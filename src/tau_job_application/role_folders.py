"""Role folders: persisted job-search targets and per-role scoring + project ideas.

A folder encodes one target search (role keywords, region, company type,
optional sector/sub-sector). The "general agent" runs each folder as a
deterministic sub-task: discover matching roles in the public vacancy
snapshot, score each against the folder's CV, and produce a project
description addressing the role's skill gaps. No LLM or provider key is
required; an optional model-backed interpretation can be added later without
changing the deterministic contract below.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sqlite3

from tau_job_application.hosted_matching import cv_text, match_cv_to_job
from tau_job_application.job_skills import extract_skills

DEFAULT_DATABASE = Path(__file__).resolve().parents[2] / ".job_assistant" / "assistant.sqlite"
DEFAULT_JOBS = Path(__file__).resolve().parents[2] / "vercel-site" / "data" / "jobs.json"
DEFAULT_COMPANIES = Path(__file__).resolve().parents[2] / "vercel-site" / "data" / "companies.json"

# Country name (casefolded) -> canonical region. Kept intentionally small and
# honest: unknown countries fall back to "Other" rather than being guessed.
_EUROPE = {
    "united kingdom", "uk", "england", "germany", "france", "netherlands",
    "switzerland", "sweden", "denmark", "norway", "finland", "ireland", "spain",
    "portugal", "italy", "austria", "belgium", "luxembourg", "poland",
    "czech republic", "czechia", "slovakia", "hungary", "romania", "bulgaria",
    "greece", "estonia", "latvia", "lithuania", "croatia", "slovenia", "iceland",
}
_UNITED_STATES = {"united states", "usa", "us", "u.s.", "united states of america", "america"}
_ASIA = {"china", "india", "japan", "south korea", "korea", "singapore", "hong kong",
         "taiwan", "vietnam", "thailand", "malaysia", "indonesia", "philippines",
         "pakistan", "bangladesh", "sri lanka", "israel", "united arab emirates",
         "uae", "saudi arabia", "qatar", "turkey", "turkiye", "russia"}
_AFRICA = {"nigeria", "kenya", "egypt", "south africa", "ghana", "morocco",
           "tunisia", "ethiopia", "tanzania", "uganda", "rwanda", "senegal"}
_AMERICAS = {"canada", "mexico", "brazil", "argentina", "chile", "colombia", "peru"}
_OCEANIA = {"australia", "new zealand"}

REGIONS = ("Any", "Europe", "United States", "Asia", "Africa", "Americas", "Oceania", "Other")
COMPANY_TYPES = ("any", "startup", "public", "private")


def region_for_country(country: str) -> str:
    value = re.sub(r"[^a-z. ]", "", str(country or "").casefold()).strip()
    if value in _UNITED_STATES:
        return "United States"
    if value in _EUROPE:
        return "Europe"
    if value in _ASIA:
        return "Asia"
    if value in _AFRICA:
        return "Africa"
    if value in _AMERICAS:
        return "Americas"
    if value in _OCEANIA:
        return "Oceania"
    return "Other"


def normalize_region(region: str) -> str:
    value = str(region or "").strip().casefold()
    aliases = {"us": "United States", "usa": "United States", "america": "United States",
               "north america": "United States", "eu": "Europe"}
    canonical = aliases.get(value)
    if canonical:
        return canonical
    for candidate in REGIONS:
        if value == candidate.casefold():
            return candidate
    return "Any" if value in {"", "any", "worldwide", "global"} else "Other"


@dataclass
class RoleFolder:
    name: str
    role_keywords: list[str] = field(default_factory=list)
    sector: str = ""
    sub_sector: str = ""
    region: str = "Any"
    company_type: str = "any"
    id: int | None = None

    @property
    def normalized_region(self) -> str:
        return normalize_region(self.region)

    def role_terms(self) -> list[str]:
        terms = [term for term in (re.sub(r"\s+", " ", kw).strip().casefold() for kw in self.role_keywords) if term]
        if not terms:
            # Fallback: the leading segment of a "role - region - type" name is the role.
            first = re.split(r"[-–—:·,/]", self.name, maxsplit=1)[0].strip().casefold()
            if first and first not in {"all", "all roles", "any", "everything", "jobs", "roles"}:
                terms = [first]
        return terms

    def to_record(self) -> dict:
        return {"name": self.name, "role_keywords": self.role_keywords, "sector": self.sector,
                "sub_sector": self.sub_sector, "region": self.region, "company_type": self.company_type}


@dataclass
class FolderMatch:
    job_id: str
    title: str
    company: str
    area: str
    url: str
    locations: list[str]
    score: int | None
    matched: list[str]
    missing: list[str]
    project: dict


def load_jobs(path: Path = DEFAULT_JOBS) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("jobs", []) if isinstance(payload, dict) else []
    jobs = []
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("url") or "").startswith("https://"):
            continue
        locations = [loc for loc in row.get("locations", []) if isinstance(loc, dict) and loc.get("label")]
        jobs.append({
            "id": str(row.get("id") or ""), "title": str(row.get("title") or ""),
            "company": str(row.get("company") or ""), "companyType": str(row.get("companyType") or ""),
            "area": str(row.get("area") or "Other"), "description": str(row.get("description") or ""),
            "skills": [str(s) for s in row.get("skills", []) if s],
            "locations": locations, "url": row["url"], "source": str(row.get("source") or ""),
        })
    return jobs


def load_companies(path: Path = DEFAULT_COMPANIES) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("companies", []) if isinstance(payload, dict) else []
    return {str(row.get("name") or "").casefold(): row for row in rows if isinstance(row, dict) and row.get("name")}


def _token_match(term: str, haystack: str) -> bool:
    """A term matches when all its words appear (substring for >=3 chars,
    whole-word for 2-char tokens such as "ml", single chars ignored)."""
    words = re.findall(r"[a-z0-9+#]+", term.casefold())
    if not words:
        return False
    for word in words:
        if len(word) >= 3:
            if word not in haystack:
                return False
        elif len(word) == 2:
            if not re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", haystack):
                return False
    return True


def discover_roles(folder: RoleFolder, jobs: list[dict]) -> list[dict]:
    """Roles matching a folder's keywords, region and company type."""
    terms = folder.role_terms()
    region = folder.normalized_region
    company_type = str(folder.company_type or "any").casefold()
    matched = []
    for job in jobs:
        haystack = " ".join([job["title"], job["area"], *job["skills"], job["description"]]).casefold()
        if terms and not any(_token_match(term, haystack) for term in terms):
            continue
        if region != "Any":
            job_regions = {region_for_country(loc.get("country") or "") for loc in job["locations"]}
            if region not in job_regions:
                continue
        if company_type != "any":
            if job["companyType"].casefold() != company_type:
                continue
        matched.append(job)
    return matched


def score_role(job: dict, cv_content: bytes | None, cv_mime: str | None) -> tuple[int | None, list[str], list[str]]:
    if not cv_content:
        return None, [], []
    try:
        result = match_cv_to_job(cv_content, cv_mime or "text/plain", job)
    except ValueError:
        return None, [], []
    return result.coverage, list(result.matched), list(result.missing)


# Skill (casefolded substring) -> a concrete, buildable project direction. The
# fallback keeps projects domain-aware even for skills outside this list.
_PROJECT_IDEAS = {
    "machine learning": "train and evaluate a small model end-to-end (data split, metrics, a written critique of what the metrics do and do not show)",
    "sql": "model a realistic dataset as a normalized schema, write and index a set of analytical queries, and document the trade-offs",
    "python": "build a small command-line tool with tests, type hints, and a README that a new contributor could follow",
    "docker": "containerize an application with a reproducible build, a healthcheck, and a documented multi-stage image",
    "kubernetes": "deploy a small service to a local cluster with manifests, probes, and a rollback plan",
    "aws": "provision a minimal service with infrastructure-as-code and explain the cost and security choices",
    "react": "build a small interactive UI with typed components, tests, and a state-management rationale",
    "typescript": "add strict typing to a small codebase and document the decisions that reduce a real bug class",
    "javascript": "build a small front-end feature with tests and accessibility checks",
    "pcb design": "design a small board (schematic + layout), generate manufacturing files, and document the design rules",
    "embedded": "build firmware for a small microcontroller with tests and a hardware-in-the-loop demo",
    "fpga": "implement a small digital design with simulation and an on-board demo",
    "trading": "backtest one clearly-scoped strategy against historical data and report its assumptions and failure modes",
    "finance": "build a small financial model with sensitivity analysis and documented assumptions",
    "data": "build a small end-to-end data pipeline with validation, tests, and a dashboard or report",
    "security": "implement and test one small security control with a threat model and a write-up",
}


def build_project(job: dict, company: dict | None, missing: list[str], folder: RoleFolder) -> dict:
    domain = (company or {}).get("industry") or (company or {}).get("summary") or job["area"]
    domain = (str(domain or "").strip() or job["area"])[:220]
    top_gaps = [g for g in missing[:2] if g]
    tasks = []
    for gap in top_gaps:
        idea = next((text for key, text in _PROJECT_IDEAS.items() if key in gap.casefold()), None)
        tasks.append(f"{gap}: {idea or 'produce a small, tested proof-of-work and a short write-up showing how you applied it.'}")
    if not tasks:
        tasks.append(f"Demonstrate a differentiating, tested piece of work in {job['area']} aligned with {job['company']}'s focus.")
    deliverables = ["A public repository with a README and instructions to run it", "Automated tests for the core behaviour",
                    "A short technical write-up explaining the decisions and limitations"]
    acceptance = ["The README lets a reviewer reproduce the result from a clean checkout",
                  "The tests pass and cover the key path", "The write-up names at least one real limitation and one follow-up"]
    return {
        "title": f"{job['title']} proof project for {job['company']}",
        "domain": domain,
        "gap_skills": top_gaps,
        "goal": f"A small, working project that demonstrates the {job['area']} skills the role asks for, focused on {domain}.",
        "tasks": tasks,
        "deliverables": deliverables,
        "acceptance": acceptance,
        "why": f"Addresses the role's skill gaps ({', '.join(top_gaps) or 'a differentiator'}) for {job['title']} at {job['company']}.",
    }


class RoleFolderStore:
    def __init__(self, path: Path = DEFAULT_DATABASE) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS role_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    role_keywords_json TEXT NOT NULL,
                    sector TEXT NOT NULL DEFAULT '',
                    sub_sector TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT 'Any',
                    company_type TEXT NOT NULL DEFAULT 'any',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS folder_documents (
                    folder_id INTEGER PRIMARY KEY REFERENCES role_folders(id) ON DELETE CASCADE,
                    cv_bytes BLOB,
                    cv_name TEXT,
                    cv_mime TEXT,
                    letter_text TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS folder_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_id INTEGER NOT NULL REFERENCES role_folders(id) ON DELETE CASCADE,
                    run_at TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    area TEXT NOT NULL,
                    url TEXT NOT NULL,
                    score INTEGER,
                    project_json TEXT NOT NULL
                );
            """)

    def create(self, folder: RoleFolder) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO role_folders (name, role_keywords_json, sector, sub_sector, region, company_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (folder.name, json.dumps(folder.role_keywords), folder.sector, folder.sub_sector,
                 folder.region, folder.company_type, self._now()),
            )
            return int(cursor.lastrowid)

    def list(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id, name, role_keywords_json, sector, sub_sector, region, company_type, created_at FROM role_folders ORDER BY id").fetchall()
        return [self._folder_row(row) for row in rows]

    def get(self, folder_id: int) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT id, name, role_keywords_json, sector, sub_sector, region, company_type, created_at FROM role_folders WHERE id = ?", (folder_id,)).fetchone()
        if not row:
            return None
        result = self._folder_row(row)
        with self._connect() as connection:
            doc = connection.execute("SELECT cv_name, cv_mime, letter_text, updated_at FROM folder_documents WHERE folder_id = ?", (folder_id,)).fetchone()
        result["cv_name"] = doc["cv_name"] if doc else None
        result["cv_mime"] = doc["cv_mime"] if doc else None
        result["letter_text"] = doc["letter_text"] if doc else None
        return result

    def set_documents(self, folder_id: int, cv_bytes: bytes | None, cv_name: str | None, cv_mime: str | None, letter_text: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO folder_documents (folder_id, cv_bytes, cv_name, cv_mime, letter_text, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(folder_id) DO UPDATE SET cv_bytes=excluded.cv_bytes, cv_name=excluded.cv_name, cv_mime=excluded.cv_mime, letter_text=excluded.letter_text, updated_at=excluded.updated_at",
                (folder_id, cv_bytes, cv_name, cv_mime, letter_text, self._now()),
            )

    def documents(self, folder_id: int) -> dict:
        with self._connect() as connection:
            doc = connection.execute("SELECT cv_bytes, cv_name, cv_mime, letter_text FROM folder_documents WHERE folder_id = ?", (folder_id,)).fetchone()
        return {"cv_bytes": doc["cv_bytes"] if doc else None, "cv_name": doc["cv_name"] if doc else None,
                "cv_mime": doc["cv_mime"] if doc else None, "letter_text": doc["letter_text"] if doc else None}

    def replace_matches(self, folder_id: int, matches: list[FolderMatch]) -> None:
        run_at = self._now()
        with self._connect() as connection:
            connection.execute("DELETE FROM folder_matches WHERE folder_id = ?", (folder_id,))
            connection.executemany(
                "INSERT INTO folder_matches (folder_id, run_at, job_id, title, company, area, url, score, project_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(folder_id, run_at, m.job_id, m.title, m.company, m.area, m.url, m.score, json.dumps(m.project)) for m in matches],
            )

    def list_matches(self, folder_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT run_at, job_id, title, company, area, url, score, project_json FROM folder_matches WHERE folder_id = ? ORDER BY score DESC NULLS LAST, company", (folder_id,)).fetchall()
        return [{"run_at": r["run_at"], "job_id": r["job_id"], "title": r["title"], "company": r["company"],
                 "area": r["area"], "url": r["url"], "score": r["score"], "project": json.loads(r["project_json"])} for r in rows]

    def delete(self, folder_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM role_folders WHERE id = ?", (folder_id,))

    @staticmethod
    def _folder_row(row: sqlite3.Row) -> dict:
        return {"id": row["id"], "name": row["name"], "role_keywords": json.loads(row["role_keywords_json"]),
                "sector": row["sector"], "sub_sector": row["sub_sector"], "region": row["region"],
                "company_type": row["company_type"], "created_at": row["created_at"]}

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()


def run_folder(store: RoleFolderStore, folder: RoleFolder, jobs: list[dict], companies: dict[str, dict]) -> list[FolderMatch]:
    documents = store.documents(folder.id) if folder.id else {}
    cv_bytes, cv_mime = documents.get("cv_bytes"), documents.get("cv_mime")
    matches = []
    for job in discover_roles(folder, jobs):
        company = companies.get(job["company"].casefold())
        score, matched, missing = score_role(job, cv_bytes, cv_mime)
        project = build_project(job, company, missing, folder)
        matches.append(FolderMatch(
            job_id=job["id"], title=job["title"], company=job["company"], area=job["area"], url=job["url"],
            locations=[str(loc.get("label")) for loc in job["locations"]], score=score,
            matched=matched, missing=missing, project=project,
        ))
    matches.sort(key=lambda m: (m.score is None, -(m.score or 0)))
    if folder.id is not None:
        store.replace_matches(folder.id, matches)
    return matches


def run_all_folders(store: RoleFolderStore, jobs: list[dict] | None = None,
                    companies: dict[str, dict] | None = None) -> dict:
    """The deterministic "general agent": run every folder as its own sub-task."""
    jobs = jobs if jobs is not None else load_jobs()
    companies = companies if companies is not None else load_companies()
    summary = {"folders": [], "total_matches": 0}
    for folder_row in store.list():
        folder = RoleFolder(
            name=folder_row["name"], role_keywords=folder_row["role_keywords"], sector=folder_row["sector"],
            sub_sector=folder_row["sub_sector"], region=folder_row["region"],
            company_type=folder_row["company_type"], id=folder_row["id"],
        )
        matches = run_folder(store, folder, jobs, companies)
        summary["folders"].append({"id": folder.id, "name": folder.name, "matches": len(matches),
                                   "scores": [m.score for m in matches if m.score is not None]})
        summary["total_matches"] += len(matches)
    return summary
