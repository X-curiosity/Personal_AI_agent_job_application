"""Transparent deterministic matching. LLMs may propose mappings, never scores."""

from tau_job_application.models import CandidateProfile, JobPosting, MatchResult, RequirementMatch, RequirementStatus

ALIASES = {
    "py": "python", "postgres": "postgresql", "postgre sql": "postgresql",
    "amazon web services": "aws", "google cloud platform": "gcp",
    "unit testing": "pytest", "rest": "rest apis",
}


def normalize_skill(skill: str) -> str:
    return ALIASES.get(" ".join(skill.casefold().split()), " ".join(skill.casefold().split()))


def calculate_match(candidate: CandidateProfile, job: JobPosting) -> MatchResult:
    evidence_by_skill = {
        normalize_skill(skill): f"candidate-skill-{_slug(skill)}" for skill in candidate.skills
    }
    confirmed_ids = {item.id for item in candidate.evidence if item.confirmed}
    items: list[RequirementMatch] = []
    for requirement in job.requirements:
        evidence_id = evidence_by_skill.get(normalize_skill(requirement.skill))
        # A heuristic keyword extraction is explicitly unconfirmed, so does not earn score credit.
        is_confirmed = evidence_id in confirmed_ids
        items.append(RequirementMatch(
            skill=requirement.skill,
            required=requirement.required,
            status=RequirementStatus.MATCHED if evidence_id and is_confirmed else RequirementStatus.MISSING,
            job_evidence_id=requirement.evidence_id,
            candidate_evidence_ids=[evidence_id] if evidence_id and is_confirmed else [],
        ))
    required_items = [item for item in items if item.required]
    preferred_items = [item for item in items if not item.required]
    required_score = _matched_fraction(required_items)
    preferred_score = _matched_fraction(preferred_items)
    return MatchResult(
        score=round((required_score * 0.8 + preferred_score * 0.2) * 100),
        required_score=required_score,
        preferred_score=preferred_score,
        requirements=items,
    )


def _matched_fraction(items: list[RequirementMatch]) -> float:
    return 1.0 if not items else sum(item.status == RequirementStatus.MATCHED for item in items) / len(items)


def _slug(value: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
