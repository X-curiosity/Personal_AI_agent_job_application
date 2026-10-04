"""Candidate-owned role and project evidence matching.

This module deliberately does *not* discover people, inspect employee profiles, or
estimate a chance of being hired.  It compares explicit job requirements with
confirmed CV skills and with completed, candidate-confirmed project evidence.
An optional hiring-pattern component is reserved for a narrowly-scoped,
employer-authorized anonymous capability rubric; it never accepts individual
employee or historical-hire records.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal
import re

from pydantic import BaseModel, Field, field_validator, model_validator

from tau_job_application.matching import calculate_match, normalize_skill
from tau_job_application.models import CandidateProfile, JobPosting


class ProjectStatus(StrEnum):
    """A project must be complete before it can count as evidence."""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ProjectProofKind(StrEnum):
    """The modest, reviewable kinds of proof a candidate can choose to add."""

    REPOSITORY = "repository"
    README = "readme"
    TEST = "test"
    DEMO = "demo"
    BENCHMARK = "benchmark"
    DEPLOYMENT = "deployment"
    CASE_STUDY = "case_study"
    WRITEUP = "writeup"


class ProjectProof(BaseModel):
    """A reference the candidate can open and explain; it is never fetched here."""

    kind: ProjectProofKind
    reference: str = Field(min_length=3, max_length=1_000)
    confirmed: bool = False

    @field_validator("reference")
    @classmethod
    def clean_reference(cls, value: str) -> str:
        return " ".join(value.split())


class CandidateProject(BaseModel):
    """Candidate-owned project evidence scoped to one Job Workspace.

    A deliberately incomplete, planned, or unconfirmed record can be retained for
    the user's own inventory, but it cannot earn score credit.
    """

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=180)
    skills: tuple[str, ...] = Field(default_factory=tuple)
    contribution: str = Field(min_length=8, max_length=4_000)
    proofs: tuple[ProjectProof, ...] = Field(default_factory=tuple)
    outcome_or_test: str | None = Field(default=None, max_length=2_000)
    status: ProjectStatus = ProjectStatus.COMPLETED
    candidate_confirmed: bool = False

    @field_validator("title", "contribution")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("skills")
    @classmethod
    def require_distinct_skills(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                raise ValueError("Project skills must be text")
            text = " ".join(value.split())
            key = normalize_skill(text)
            if not text:
                continue
            if key not in seen:
                seen.add(key)
                cleaned.append(text)
        if not cleaned:
            raise ValueError("Add at least one skill the completed project demonstrates")
        return tuple(cleaned)

    @field_validator("outcome_or_test")
    @classmethod
    def clean_outcome(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class HiringPatternMode(StrEnum):
    """Only non-personal, rights-attested sources are eligible."""

    EMPLOYER_AUTHORIZED_AGGREGATE = "employer_authorized_aggregate"
    LICENSED_AGGREGATE = "licensed_aggregate"
    COMPANY_PUBLISHED_FRAMEWORK = "company_published_framework"


class HiringPatternCriterion(BaseModel):
    """One skill from a published/authorized anonymous role rubric."""

    skill: str = Field(min_length=1, max_length=160)
    weight: int = Field(gt=0, le=100)
    source_quote: str = Field(min_length=3, max_length=2_000)

    @field_validator("skill", "source_quote")
    @classmethod
    def clean_criterion_text(cls, value: str) -> str:
        return " ".join(value.split())


class HiringPattern(BaseModel):
    """A safe future integration contract, intentionally without person fields.

    The UI currently has no importer for this object.  Keeping the contract
    explicit makes an unavailable company component honest rather than replacing
    it with scraped profiles or a synthetic hiring-history estimate.
    """

    id: str = Field(min_length=1, max_length=100)
    company: str = Field(min_length=1, max_length=180)
    role_family: str = Field(min_length=1, max_length=180)
    criteria: tuple[HiringPatternCriterion, ...] = Field(min_length=1)
    source_url: str = Field(min_length=8, max_length=1_000)
    valid_from: date
    valid_to: date
    rights_attested: bool = False
    anonymisation_attested: bool = False
    mode: HiringPatternMode = HiringPatternMode.EMPLOYER_AUTHORIZED_AGGREGATE
    minimum_cohort_size: int | None = Field(default=None, ge=3)

    @field_validator("company", "role_family", "source_url")
    @classmethod
    def clean_pattern_text(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def validate_safe_aggregate_contract(self) -> "HiringPattern":
        if self.valid_to < self.valid_from:
            raise ValueError("A hiring-pattern source cannot expire before it starts")
        if not self.rights_attested or not self.anonymisation_attested:
            raise ValueError("A hiring-pattern source requires rights and anonymisation attestations")
        if self.mode != HiringPatternMode.COMPANY_PUBLISHED_FRAMEWORK and self.minimum_cohort_size is None:
            raise ValueError("Aggregate hiring-pattern sources require a minimum cohort policy")
        return self


class ProjectRequirementSupport(BaseModel):
    """Why a requirement did or did not receive project-evidence credit."""

    skill: str
    required: bool
    support: float = Field(ge=0, le=1)
    project_ids: tuple[str, ...] = Field(default_factory=tuple)
    project_titles: tuple[str, ...] = Field(default_factory=tuple)
    explanation: str


class EvidenceMatch(BaseModel):
    """Transparent evidence components, never a score of hiring likelihood."""

    score: int | None = Field(default=None, ge=0, le=100)
    role_coverage: int = Field(ge=0, le=100)
    project_coverage: int | None = Field(default=None, ge=0, le=100)
    pattern_coverage: int | None = Field(default=None, ge=0, le=100)
    project_status: Literal[
        "not_provided", "no_eligible_projects", "no_matching_project_evidence",
        "insufficient_role_evidence", "scored"
    ]
    pattern_status: Literal["unavailable", "scope_or_expiry_mismatch", "scored"]
    requirement_supports: tuple[ProjectRequirementSupport, ...] = Field(default_factory=tuple)
    matched_project_titles: tuple[str, ...] = Field(default_factory=tuple)
    limitations: tuple[str, ...] = Field(default_factory=tuple)


_FULL_PROOF_KINDS = {
    ProjectProofKind.TEST,
    ProjectProofKind.DEMO,
    ProjectProofKind.BENCHMARK,
    ProjectProofKind.DEPLOYMENT,
}


def calculate_evidence_match(
    candidate: CandidateProfile,
    job: JobPosting,
    projects: tuple[CandidateProject, ...] | list[CandidateProject] = (),
    patterns: tuple[HiringPattern, ...] | list[HiringPattern] = (),
    *,
    today: date | None = None,
) -> EvidenceMatch:
    """Return explainable role/project evidence coverage for one target job.

    Role coverage is intentionally the application's existing confirmed-CV
    coverage, so callers can compare it directly with the Overview card.  Project
    evidence has its own denominator and is unavailable when the user has not
    supplied an eligible completed project—missing information is never scored as
    failure.
    """

    role_coverage = calculate_match(candidate, job).score
    requirements = tuple(requirement for requirement in job.requirements if requirement.importance != "uncertain")
    all_projects = tuple(projects)
    eligible_projects = tuple(project for project in all_projects if _is_eligible_project(project))

    project_coverage: int | None = None
    supports: tuple[ProjectRequirementSupport, ...] = ()
    matched_titles: tuple[str, ...] = ()
    if not all_projects:
        project_status: Literal[
            "not_provided", "no_eligible_projects", "no_matching_project_evidence",
            "insufficient_role_evidence", "scored"
        ] = "not_provided"
    elif not requirements:
        project_status = "insufficient_role_evidence"
    elif not eligible_projects:
        project_status = "no_eligible_projects"
    elif not _has_role_skill_overlap(requirements, eligible_projects):
        project_status = "no_matching_project_evidence"
    else:
        project_status = "scored"
        project_coverage, supports, matched_titles = _project_coverage(requirements, eligible_projects)

    pattern_coverage, pattern_status = _pattern_coverage(
        candidate=candidate,
        job=job,
        eligible_projects=eligible_projects,
        patterns=tuple(patterns),
        today=today or date.today(),
    )
    score = _combined_score(role_coverage, project_coverage, pattern_coverage)
    limitations = [
        "Evidence match is not a prediction of an interview, offer, or hiring outcome.",
        "Only confirmed CV skills and candidate-confirmed completed project evidence can contribute.",
        "Planned projects and unconfirmed GitHub language signals never earn score credit.",
        "The app does not search employee profiles, infer historical hires, or scrape LinkedIn.",
    ]
    if pattern_coverage is None:
        limitations.append(
            "No eligible employer-provided anonymous role benchmark is available for this company and role."
        )
    return EvidenceMatch(
        score=score,
        role_coverage=role_coverage,
        project_coverage=project_coverage,
        pattern_coverage=pattern_coverage,
        project_status=project_status,
        pattern_status=pattern_status,
        requirement_supports=supports,
        matched_project_titles=matched_titles,
        limitations=tuple(limitations),
    )


def _is_eligible_project(project: CandidateProject) -> bool:
    """Gate score credit on status, user confirmation, proof, and an outcome."""

    return bool(
        project.status == ProjectStatus.COMPLETED
        and project.candidate_confirmed
        and project.outcome_or_test
        and any(proof.confirmed for proof in project.proofs)
    )


def _project_strength(project: CandidateProject) -> float:
    """Use a best proof, never an accumulating count of repositories/screenshots."""

    kinds = {proof.kind for proof in project.proofs if proof.confirmed}
    if ProjectProofKind.REPOSITORY in kinds and kinds & _FULL_PROOF_KINDS:
        return 1.0
    return 0.7


def _has_role_skill_overlap(requirements, projects: tuple[CandidateProject, ...]) -> bool:
    requirement_skills = {normalize_skill(requirement.skill) for requirement in requirements}
    return any(
        requirement_skills & {normalize_skill(skill) for skill in project.skills}
        for project in projects
    )


def _project_coverage(requirements, projects: tuple[CandidateProject, ...]):
    supports: list[ProjectRequirementSupport] = []
    weighted_support = 0.0
    total_weight = 0
    used_titles: list[str] = []
    for requirement in requirements:
        weight = 2 if requirement.required else 1
        total_weight += weight
        requirement_key = normalize_skill(requirement.skill)
        matches = [project for project in projects if requirement_key in {normalize_skill(skill) for skill in project.skills}]
        if matches:
            best_strength = max(_project_strength(project) for project in matches)
            best = [project for project in matches if _project_strength(project) == best_strength]
            explanation = (
                "Completed, confirmed project evidence with a repository and observable proof."
                if best_strength == 1.0
                else "Completed, confirmed project evidence with a supplied proof reference and outcome/test."
            )
            project_ids = tuple(project.id for project in best)
            project_titles = tuple(project.title for project in best)
            used_titles.extend(project_titles)
        else:
            best_strength = 0.0
            project_ids = ()
            project_titles = ()
            explanation = "No eligible completed project explicitly demonstrates this requirement."
        weighted_support += weight * best_strength
        supports.append(ProjectRequirementSupport(
            skill=requirement.skill,
            required=requirement.required,
            support=best_strength,
            project_ids=project_ids,
            project_titles=project_titles,
            explanation=explanation,
        ))
    score = round((weighted_support / total_weight) * 100) if total_weight else None
    return score, tuple(supports), tuple(dict.fromkeys(used_titles))


def _confirmed_candidate_skills(candidate: CandidateProfile) -> set[str]:
    confirmed_ids = {item.id for item in candidate.evidence if item.confirmed}
    skills: set[str] = set()
    for skill in candidate.skills:
        evidence_id = f"candidate-skill-{_slug(skill)}"
        if evidence_id in confirmed_ids:
            skills.add(normalize_skill(skill))
    return skills


def _pattern_coverage(
    *,
    candidate: CandidateProfile,
    job: JobPosting,
    eligible_projects: tuple[CandidateProject, ...],
    patterns: tuple[HiringPattern, ...],
    today: date,
) -> tuple[int | None, Literal["unavailable", "scope_or_expiry_mismatch", "scored"]]:
    if not patterns:
        return None, "unavailable"
    matching = tuple(pattern for pattern in patterns if _pattern_matches(pattern, job, today))
    if not matching:
        return None, "scope_or_expiry_mismatch"
    pattern = matching[0]
    supported_skills = _confirmed_candidate_skills(candidate)
    supported_skills.update(
        normalize_skill(skill)
        for project in eligible_projects
        for skill in project.skills
    )
    denominator = sum(criterion.weight for criterion in pattern.criteria)
    numerator = sum(
        criterion.weight
        for criterion in pattern.criteria
        if normalize_skill(criterion.skill) in supported_skills
    )
    return (round((numerator / denominator) * 100) if denominator else None), "scored"


def _pattern_matches(pattern: HiringPattern, job: JobPosting, today: date) -> bool:
    return bool(
        pattern.company.casefold() == job.company.casefold()
        and _title_key(pattern.role_family) == _title_key(job.title)
        and pattern.valid_from <= today <= pattern.valid_to
    )


def _combined_score(role: int, project: int | None, pattern: int | None) -> int | None:
    """Combine only provided components; an unavailable component is not a zero."""

    if project is None:
        return None
    if pattern is None:
        return round(((role * 0.55) + (project * 0.30)) / 0.85)
    return round((role * 0.55) + (project * 0.30) + (pattern * 0.15))


def _title_key(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
