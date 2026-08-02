"""Small deterministic parsers used by the starter vertical slice.

The fixture format is intentionally simple: one ``Field: value`` per line.
Replace or extend these functions with evidence-grounded model extraction later.
"""

from pathlib import Path
import re

from pypdf import PdfReader

from tau_job_application.models import (
    CandidateProfile,
    EvidenceItem,
    JobPosting,
    JobRequirement,
)


def load_document(path: Path) -> str:
    """Load a UTF-8 text file or a selectable-text PDF."""

    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    if path.suffix.casefold() == ".txt":
        text = path.read_text(encoding="utf-8")
    elif path.suffix.casefold() == ".pdf":
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        raise ValueError("Only .txt and .pdf files are supported by the template")

    if not text.strip():
        raise ValueError("No selectable text found; a scanned PDF needs OCR")
    return text


def parse_candidate_text(text: str) -> CandidateProfile:
    fields = _parse_fields(text)
    name = _required(fields, "name")
    skills = _split_list(_required(fields, "skills"))
    skill_line = f"Skills: {fields['skills']}"
    evidence = [
        EvidenceItem(
            id=f"candidate-skill-{_slug(skill)}",
            source="candidate",
            quote=skill_line,
            location="Skills",
            confirmed=True,
        )
        for skill in skills
    ]
    return CandidateProfile(
        name=name,
        headline=fields.get("headline"),
        skills=skills,
        experience_summary=fields.get("experience"),
        evidence=evidence,
    )


def parse_job_text(text: str) -> JobPosting:
    fields = _parse_fields(text)
    required = _split_list(fields.get("required skills", ""))
    preferred = _split_list(fields.get("preferred skills", ""))
    if not required and not preferred:
        raise ValueError("The job must contain Required skills or Preferred skills")

    requirements: list[JobRequirement] = []
    evidence: list[EvidenceItem] = []
    for is_required, skills, field_name in (
        (True, required, "Required skills"),
        (False, preferred, "Preferred skills"),
    ):
        if not skills:
            continue
        quote = f"{field_name}: {fields[field_name.casefold()]}"
        for skill in skills:
            evidence_id = f"job-skill-{_slug(skill)}"
            requirements.append(
                JobRequirement(skill=skill, required=is_required, evidence_id=evidence_id)
            )
            evidence.append(
                EvidenceItem(
                    id=evidence_id,
                    source="job",
                    quote=quote,
                    location=field_name,
                    confirmed=True,
                )
            )

    return JobPosting(
        title=_required(fields, "title"),
        company=_required(fields, "company"),
        location=fields.get("location"),
        requirements=requirements,
        evidence=evidence,
    )


def _parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if value.strip():
            fields[key.strip().casefold()] = value.strip()
    return fields


def _required(fields: dict[str, str], name: str) -> str:
    value = fields.get(name.casefold())
    if not value:
        raise ValueError(f"Missing required field: {name}")
    return value


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
