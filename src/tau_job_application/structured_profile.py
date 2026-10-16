"""The structured candidate profile — Zenply's core asset.

Recruiters filter on structured data; applicants only have unstructured,
self-reported documents. This module assembles the candidate's canonical
structured profile from the local stores (CV parse, confirmed skills,
completed evidence projects, declared residency, role targets, rehearsal
history) and evaluates deterministic recruiter-style criteria against it.

Boundaries: only completed evidence projects count as proof; residency facts
stay user-declared; a profile is assembled on demand and exported only when
the user downloads it — nothing is shared with recruiters automatically.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from tau_job_application.eligibility import eligibility_checklist
from tau_job_application.interview import difficulty_level
from tau_job_application.parsing import parse_candidate_text


class EvidenceProjectEntry(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    skills: tuple[str, ...] = ()
    status: str = Field(min_length=1, max_length=40)
    thread: str | None = None


class InterviewReadiness(BaseModel):
    rehearsals: int = 0
    average_score: int | None = None
    current_level: int = 1
    level_name: str = "Fundamentals"


class StructuredProfile(BaseModel):
    """The queryable candidate record; exported only by explicit download."""

    full_name: str | None = None
    links: dict[str, str] = Field(default_factory=dict)
    citizenships: tuple[str, ...] = ()
    residence_country: str | None = None
    work_permits: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    evidence_projects: tuple[EvidenceProjectEntry, ...] = ()
    role_targets: tuple[str, ...] = ()
    applications_by_stage: dict[str, int] = Field(default_factory=dict)
    interview: InterviewReadiness = Field(default_factory=InterviewReadiness)


class RecruiterCriteria(BaseModel):
    """A deterministic recruiter filter, evaluated against one profile."""

    skills_all: tuple[str, ...] = ()
    min_completed_projects: int = Field(default=0, ge=0, le=50)
    min_interview_level: int = Field(default=1, ge=1, le=5)
    job_country: str | None = None


class RecruiterQueryResult(BaseModel):
    qualified: bool
    reasons: tuple[str, ...]


def build_structured_profile(
    *,
    workspaces,
    hub_store,
    residency_store,
    evidence_store,
    application_store,
    track: str,
) -> StructuredProfile:
    """Assemble the profile on demand from the local stores (no copying)."""

    shared = workspaces.shared_profile()
    cv_text = shared.get("cv_text", "").strip()
    candidate = parse_candidate_text(cv_text) if cv_text else None
    links = {field: shared.get(field, "").strip() for field in ("github", "portfolio", "linkedin", "x") if shared.get(field, "").strip()}

    residency = residency_store.get(track)
    interests = hub_store.interests(track)

    projects: list[EvidenceProjectEntry] = []
    attempts: list[dict] = []
    for thread in workspaces.list_threads(track):
        for project in evidence_store.list_projects(track, thread["id"]):
            projects.append(EvidenceProjectEntry(
                title=project.title, skills=tuple(project.skills), status=str(project.status), thread=thread["name"],
            ))
        attempts.extend(workspaces.interview_attempts(track, thread["id"]))

    stages: dict[str, int] = {}
    for record in application_store.list_records(track):
        stage = record.progress.stage.label if hasattr(record.progress.stage, "label") else str(record.progress.stage)
        stages[stage] = stages.get(stage, 0) + 1

    from tau_job_application.interview import LEVEL_NAMES

    average = round(sum(a["score"] for a in attempts) / len(attempts)) if attempts else None
    level = difficulty_level(attempts)
    return StructuredProfile(
        full_name=(candidate.name or None) if candidate else None,
        links=links,
        citizenships=residency.citizenships if residency else (),
        residence_country=residency.residence_country if residency else None,
        work_permits=residency.work_permits if residency else (),
        skills=tuple(sorted({skill for skill in (candidate.skills if candidate else ()) if skill.strip()}, key=str.casefold)),
        evidence_projects=tuple(projects),
        role_targets=tuple(interests.roles) if interests else (),
        applications_by_stage=stages,
        interview=InterviewReadiness(
            rehearsals=len(attempts), average_score=average,
            current_level=level, level_name=LEVEL_NAMES[level],
        ),
    )


def evaluate_recruiter_query(profile: StructuredProfile, criteria: RecruiterCriteria) -> RecruiterQueryResult:
    """Deterministic recruiter filter — hard failures vs flags, no model judgement.

    Missing skills, insufficient completed evidence, a low interview level,
    or an unevaluable residency profile are hard failures. A sponsorship
    requirement is a flag: the candidate still qualifies, with a note.
    """

    failures: list[str] = []
    flags: list[str] = []
    profile_skills = {skill.casefold() for skill in profile.skills}
    missing = [skill for skill in criteria.skills_all if skill.strip().casefold() not in profile_skills]
    if missing:
        failures.append("Missing skill(s): " + ", ".join(missing))
    completed = [project for project in profile.evidence_projects if project.status == "completed"]
    if len(completed) < criteria.min_completed_projects:
        failures.append(f"Only {len(completed)} completed evidence project(s); {criteria.min_completed_projects} required.")
    if profile.interview.current_level < criteria.min_interview_level:
        failures.append(f"Interview level {profile.interview.current_level} below required {criteria.min_interview_level}.")
    if criteria.job_country:
        if not profile.residence_country or not profile.citizenships:
            failures.append("No residency profile saved; work eligibility cannot be evaluated.")
        else:
            from tau_job_application.eligibility import ResidencyProfile

            checklist = eligibility_checklist(
                ResidencyProfile(
                    citizenships=profile.citizenships,
                    residence_country=profile.residence_country,
                    work_permits=profile.work_permits,
                ),
                criteria.job_country,
            )
            if checklist.pathway == "sponsorship":
                flags.append(f"{criteria.job_country}: employer sponsorship required (visa step).")
    reasons = (*failures, *flags) or ("All criteria satisfied.",)
    return RecruiterQueryResult(qualified=not failures, reasons=reasons)
