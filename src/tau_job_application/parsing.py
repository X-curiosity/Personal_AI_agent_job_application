"""Local document parsing with source spans retained for every extracted fact.

This module deliberately supports a small, editable schema first.  It also makes a
best-effort extraction from ordinary CV/job text so the UI is useful before an LLM
is configured.  Ambiguous text is never treated as confirmed competence.
"""

from __future__ import annotations

from pathlib import Path
import re
from zipfile import ZipFile
from xml.etree import ElementTree

from pypdf import PdfReader

from tau_job_application.models import CandidateProfile, EvidenceItem, JobPosting, JobRequirement

KNOWN_SKILLS = (
    "Python", "SQL", "FastAPI", "Docker", "Kubernetes", "AWS", "GCP", "Azure",
    "Git", "pytest", "PostgreSQL", "Linux", "Java", "JavaScript", "TypeScript",
    "React", "Node.js", "C++", "C", "Rust", "Go", "TensorFlow", "PyTorch",
    "Machine Learning", "Data Analysis", "Pandas", "NumPy", "Spark", "Airflow",
    "Terraform", "CI/CD", "System Design", "REST APIs", "GraphQL", "Figma",
)


def load_document(path: Path) -> str:
    """Load local text, Markdown, PDF, or DOCX text. Scanned PDFs need OCR first."""
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    suffix = path.suffix.casefold()
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8")
    elif suffix == ".pdf":
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        text = _read_docx(path)
    else:
        raise ValueError("Supported documents are .txt, .md, .pdf, and .docx")
    if not text.strip():
        raise ValueError("No selectable text found; a scanned PDF needs OCR")
    return text


def parse_candidate_text(text: str, *, links: dict[str, str] | None = None) -> CandidateProfile:
    """Create a candidate profile without claiming that keyword mentions prove skill."""
    fields = _parse_fields(text)
    name = fields.get("name") or _guess_name(text) or "Candidate (please confirm)"
    explicit_skills = _split_list(fields.get("skills", ""))
    skills = _dedupe(explicit_skills or _find_skills(text))
    skill_quote = f"Skills: {fields['skills']}" if fields.get("skills") else "Skills inferred from CV text; confirm each one."
    confirmed = bool(explicit_skills)
    evidence = [
        EvidenceItem(
            id=f"candidate-skill-{_slug(skill)}",
            source="candidate",
            quote=skill_quote,
            location="Skills" if explicit_skills else "CV keyword extraction",
            confirmed=confirmed,
        )
        for skill in skills
    ]
    evidence.append(EvidenceItem(
        id="candidate-cv-source",
        source="candidate",
        quote=_clip(text),
        location="Imported CV",
        confirmed=True,
    ))
    return CandidateProfile(
        name=name,
        headline=fields.get("headline") or _first_nonempty_line(text),
        skills=skills,
        experience_summary=fields.get("experience") or _experience_summary(text),
        links=links or {},
        raw_cv=text,
        evidence=evidence,
    )


def parse_job_text(
    text: str, *, title: str | None = None, company: str | None = None, url: str | None = None
) -> JobPosting:
    """Parse a job description, retaining requirement wording and confidence context."""
    fields = _parse_fields(text)
    required = _split_list(fields.get("required skills", ""))
    preferred = _split_list(fields.get("preferred skills", ""))
    if not required and not preferred:
        required, preferred = _extract_job_skills(text)
    if not required and not preferred:
        raise ValueError(
            "No skills were found. Add lines such as 'Required skills: Python, SQL' "
            "or include a more complete job description."
        )
    requirements: list[JobRequirement] = []
    evidence: list[EvidenceItem] = [EvidenceItem(
        id="job-description-source", source="job", quote=_clip(text),
        location="Imported job description", confirmed=True, url=url,
    )]
    seen: set[str] = set()
    for is_required, skills, field_name in ((True, required, "Required skills"), (False, preferred, "Preferred skills")):
        for skill in skills:
            key = _slug(skill)
            if key in seen:
                continue
            seen.add(key)
            evidence_id = f"job-skill-{key}"
            quote = f"{field_name}: {fields[field_name.casefold()]}" if fields.get(field_name.casefold()) else _skill_context(text, skill)
            requirements.append(JobRequirement(skill=skill, required=is_required, evidence_id=evidence_id))
            evidence.append(EvidenceItem(
                id=evidence_id, source="job", quote=quote, location=field_name,
                confirmed=True, url=url,
            ))
    return JobPosting(
        title=title or fields.get("title") or _guess_job_title(text) or "Role (please confirm)",
        company=company or fields.get("company") or _guess_company(text) or "Company (please confirm)",
        location=fields.get("location"), url=url, description=text, requirements=requirements, evidence=evidence,
    )


def _read_docx(path: Path) -> str:
    try:
        with ZipFile(path) as archive:
            document = archive.read("word/document.xml")
        root = ElementTree.fromstring(document)
    except Exception as exc:  # zip/xml errors should be useful at the boundary
        raise ValueError(f"Could not read DOCX file: {exc}") from exc
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "\n".join("".join(node.text or "" for node in paragraph.iter(f"{namespace}t")) for paragraph in root.iter(f"{namespace}p"))


def _parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if value.strip():
            fields[key.strip().casefold()] = value.strip()
    return fields


def _split_list(value: str) -> list[str]:
    return [item.strip(" -•\t") for item in re.split(r"[,;|]", value) if item.strip(" -•\t")]


def _find_skills(text: str) -> list[str]:
    return [skill for skill in KNOWN_SKILLS if re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", text, re.I)]


def _extract_job_skills(text: str) -> tuple[list[str], list[str]]:
    required: list[str] = []
    preferred: list[str] = []
    preferred_markers = ("preferred", "nice to have", "bonus", "plus", "ideally")
    for line in text.splitlines() or [text]:
        found = _find_skills(line)
        if not found:
            continue
        target = preferred if any(marker in line.casefold() for marker in preferred_markers) else required
        target.extend(found)
    return _dedupe(required), _dedupe(preferred)


def _guess_name(text: str) -> str | None:
    first = _first_nonempty_line(text)
    if first and 1 <= len(first.split()) <= 5 and len(first) < 70 and not any(char.isdigit() for char in first):
        return first.strip("# ")
    return None


def _guess_job_title(text: str) -> str | None:
    for line in text.splitlines()[:8]:
        cleaned = line.strip("# -*•\t")
        if re.search(r"\b(engineer|designer|analyst|manager|developer|intern|scientist|consultant)\b", cleaned, re.I):
            return cleaned[:120]
    return None


def _guess_company(text: str) -> str | None:
    match = re.search(r"(?:about|join)\s+([A-Z][\w&.-]+(?:\s+[A-Z][\w&.-]+){0,3})", text)
    return match.group(1) if match else None


def _first_nonempty_line(text: str) -> str | None:
    return next((line.strip("# \t") for line in text.splitlines() if line.strip()), None)


def _experience_summary(text: str) -> str | None:
    lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
    bullets = [line for line in lines if line.startswith(("Built", "Led", "Developed", "Created", "Worked", "Implemented"))]
    return " ".join(bullets[:3]) or None


def _skill_context(text: str, skill: str) -> str:
    for line in text.splitlines():
        if re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", line, re.I):
            return line.strip()[:500]
    return f"Mentioned in job description: {skill}"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _clip(text: str, maximum: int = 600) -> str:
    normalized = " ".join(text.split())
    return normalized[:maximum] + ("…" if len(normalized) > maximum else "")
