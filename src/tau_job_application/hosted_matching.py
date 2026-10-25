"""Private CV extraction and deterministic public-vacancy comparison."""
from __future__ import annotations

from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

from tau_job_application.job_skills import extract_skills
from tau_job_application.parsing import infer_profile_links

MAX_JOBS = 500


@dataclass(frozen=True)
class CVMatch:
    cv_skills: tuple[str, ...]
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    coverage: int | None
    links: dict[str, str]


def cv_text(filename: str, mime_type: str, content: bytes) -> str:
    if not content:
        raise ValueError("The CV file is empty.")
    if mime_type == "application/pdf":
        try:
            return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
        except Exception as exc:
            raise ValueError("This PDF could not be read. Try a selectable-text PDF.") from exc
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 20_000_000 or info.file_size > max(1_000_000, info.compress_size * 200):
                    raise ValueError("DOCX document content is too large or suspiciously compressed.")
                root = ElementTree.fromstring(archive.read("word/document.xml", pwd=None))
            return "\n".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
        except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError("This DOCX could not be read.") from exc
    if mime_type in {"text/plain", "text/markdown"}:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Text CVs must use UTF-8 encoding.") from exc
    raise ValueError(f"Unsupported CV type for {Path(filename).name}.")


def match_cv_to_job(cv_content: bytes, mime_type: str, job: dict) -> CVMatch:
    text = cv_text(str(job.get("title", "CV")), mime_type, cv_content)
    candidate = tuple(extract_skills(text[:2_000_000]))
    candidate_keys = {skill.casefold() for skill in candidate}
    required = tuple(str(skill) for skill in job.get("skills", []) if str(skill).strip())
    matched = tuple(skill for skill in required if skill.casefold() in candidate_keys)
    missing = tuple(skill for skill in required if skill.casefold() not in candidate_keys)
    coverage = round(100 * len(matched) / len(required)) if required else None
    return CVMatch(candidate, matched, missing, coverage, infer_profile_links(text))


def load_public_jobs() -> list[dict]:
    configured = os.getenv("HOSTED_JOBS_URL", "").strip()
    if configured:
        if not configured.startswith("https://"):
            raise ValueError("HOSTED_JOBS_URL must use HTTPS.")
        request = Request(configured, headers={"Accept": "application/json", "User-Agent": "hired-hosted/0.2"})
        with urlopen(request, timeout=12) as response:  # noqa: S310 - operator-configured HTTPS public snapshot
            payload = json.loads(response.read(10_000_001).decode("utf-8"))
    else:
        path = Path(__file__).resolve().parents[2] / "vercel-site" / "data" / "jobs.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("jobs", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list) or len(rows) > MAX_JOBS:
        raise ValueError("Unsupported public job snapshot.")
    jobs = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("url"), str) or not row["url"].startswith("https://"):
            continue
        if not row.get("id") or not row.get("title") or not row.get("company"):
            continue
        jobs.append({
            "id": str(row["id"]), "title": str(row["title"])[:200], "company": str(row["company"])[:160],
            "url": row["url"], "source": str(row.get("source") or ""), "area": str(row.get("area") or "Other"),
            "description": str(row.get("description") or "")[:4000],
            "skills": [str(skill)[:60] for skill in row.get("skills", []) if isinstance(skill, str)][:20],
            "locations": [str(place.get("label"))[:300] for place in row.get("locations", []) if isinstance(place, dict) and place.get("label")][:20],
        })
    return jobs


def filter_jobs(jobs: list[dict], query: str = "", area: str = "") -> list[dict]:
    terms = [re.sub(r"\s+", " ", term.casefold()).strip() for term in query.split() if term.strip()]
    return [
        job for job in jobs
        if (not area or job["area"] == area)
        and all(term in " ".join([job["title"], job["company"], *job["skills"], *job["locations"]]).casefold() for term in terms)
    ]
