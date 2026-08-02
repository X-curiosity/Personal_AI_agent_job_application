"""Transparent, deterministic candidate/job matching."""

from tau_job_application.models import (
    CandidateProfile,
    JobPosting,
    MatchResult,
    RequirementMatch,
    RequirementStatus,
)


def normalize_skill(skill: str) -> str:
    """Normalize exact names; add an explicit alias table as the project grows."""

    aliases = {"postgres": "postgresql", "py": "python"}
    normalized = " ".join(skill.casefold().split())
    return aliases.get(normalized, normalized)


def calculate_match(candidate: CandidateProfile, job: JobPosting) -> MatchResult:
    candidate_evidence = {
        normalize_skill(skill): evidence.id
        for skill, evidence in zip(candidate.skills, candidate.evidence, strict=False)
    }
    items: list[RequirementMatch] = []

    for requirement in job.requirements:
        normalized = normalize_skill(requirement.skill)
        evidence_id = candidate_evidence.get(normalized)
        items.append(
            RequirementMatch(
                skill=requirement.skill,
                required=requirement.required,
                status=(
                    RequirementStatus.MATCHED
                    if evidence_id
                    else RequirementStatus.MISSING
                ),
                job_evidence_id=requirement.evidence_id,
                candidate_evidence_ids=[evidence_id] if evidence_id else [],
            )
        )

    required_items = [item for item in items if item.required]
    preferred_items = [item for item in items if not item.required]
    required_score = _matched_fraction(required_items)
    preferred_score = _matched_fraction(preferred_items)
    score = round((required_score * 0.8 + preferred_score * 0.2) * 100)

    return MatchResult(
        score=score,
        required_score=required_score,
        preferred_score=preferred_score,
        requirements=items,
    )


def _matched_fraction(items: list[RequirementMatch]) -> float:
    if not items:
        return 1.0
    matched = sum(item.status == RequirementStatus.MATCHED for item in items)
    return matched / len(items)
