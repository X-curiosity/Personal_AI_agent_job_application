"""Export the SQLite store to the public JSON the frontend consumes."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.store import Store

ROOT = Path(__file__).resolve().parents[1]
SITE_DATA = ROOT / "vercel-site" / "data"

# Skill vocabulary used to summarize role requirements from the description.
_SKILLS = [
    "python", "javascript", "typescript", "react", "node", "node.js", "sql", "postgresql", "mysql",
    "mongodb", "redis", "aws", "gcp", "google cloud", "azure", "docker", "kubernetes", "terraform",
    "machine learning", "ml", "ai", "data science", "pytorch", "tensorflow", "data engineering",
    "c++", "java", "golang", "go", "rust", "ruby", "php", "swift", "kotlin", "scala", "matlab",
    "excel", "tableau", "power bi", "figma", "git", "ci/cd", "linux", "kafka", "graphql", "rest",
    "microservices", "devops", "cloud", "security", "testing", "qa", "agile", "scrum", "analytics",
    "computer vision", "nlp", "llm", "blockchain", "embedded", "robotics",
    "product management", "project management", "sales", "marketing", "seo", "growth",
    "business development", "finance", "accounting", "compliance", "customer success", "operations",
    "supply chain", "logistics", "communication", "leadership",
]


def extract_requirements(description: str) -> dict:
    """Summarize a job description into structured requirements (skills,
    experience, degrees) instead of serving the raw advert text."""
    text = (description or "").lower()
    skills = sorted({s for s in _SKILLS if re.search(rf"(?<![a-z0-9]){re.escape(s)}(?![a-z0-9])", text)})
    experience = ""
    years = re.findall(r"(\d+)\+?\s*(?:years?|yrs)", text)
    if years:
        experience = f"{min(int(y) for y in years)}+ years"
    degrees: list[str] = []
    if re.search(r"\bphd\b|doctorate", text):
        degrees.append("PhD")
    if re.search(r"master", text):
        degrees.append("Master's")
    if re.search(r"bachelor|undergraduate", text):
        degrees.append("Bachelor's")
    return {"skills": skills[:15], "experience": experience, "degrees": degrees[:3]}


def main() -> None:
    store = Store()
    SITE_DATA.mkdir(parents=True, exist_ok=True)

    startups = store.all_startups()
    jobs = store.all_jobs(visible_only=True)

    # startups.json — mirror startupmap's startup schema
    for s in startups:
        s["accelerators"] = json.loads(s["accelerators"] or "[]")
        # Split the conflated "stage" into company type (public/private) vs
        # funding stage (seed/series A/… — only meaningful for private companies).
        stage = s.get("stage") or ""
        if stage in ("public", "private"):
            s["company_type"] = stage
            s["stage"] = ""
        elif stage == "unknown":
            s["company_type"] = ""
            s["stage"] = ""
        elif stage:
            s["company_type"] = "private"  # a funding stage implies not yet public
        else:
            s["company_type"] = ""
    (SITE_DATA / "startups.json").write_text(json.dumps(startups, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # jobs.json — mirror startupmap's job schema (type[] parsed back to list).
    # Cap descriptions to a preview length so the snapshot stays light; the
    # full advert lives on the apply link.
    for j in jobs:
        j["type"] = json.loads(j["type"] or "[]")
        full = j.get("description") or ""
        j["requirements"] = extract_requirements(full)  # run on the full advert
        j["description"] = full[:800]  # cap only what's shown
    (SITE_DATA / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"Exported {len(startups)} startups, {len(jobs)} jobs to {SITE_DATA}")


if __name__ == "__main__":
    main()
