"""Evidence-bound tests for the hiring-pattern match calculation.

These tests deliberately exercise only user-confirmed, completed project work and
properly scoped aggregate hiring patterns.  They must never turn plans, unverified
claims, or an unrelated company's data into candidate evidence.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from tau_job_application.hiring_match import (
    CandidateProject,
    HiringPattern,
    HiringPatternCriterion,
    ProjectProof,
    calculate_evidence_match,
)
from tau_job_application.parsing import parse_candidate_text, parse_job_text


def _candidate():
    return parse_candidate_text("Name: Alex\nSkills: Python")


def _job():
    return parse_job_text(
        "Title: Platform Engineer\nCompany: Acme\n"
        "Required skills: Python, Docker\nPreferred skills: AWS"
    )


def _completed_project(**changes: object) -> CandidateProject:
    values: dict[str, object] = {
        "id": "project-reliable-api",
        "title": "Reliable API service",
        "contribution": "Implemented the Dockerised API deployment and monitoring.",
        "skills": ("Docker", "AWS"),
        "proofs": (
            ProjectProof(
                kind="repository",
                reference="https://github.com/example/reliable-api",
                confirmed=True,
            ),
            ProjectProof(
                kind="test",
                reference="https://github.com/example/reliable-api/actions",
                confirmed=True,
            ),
        ),
        "outcome_or_test": "Integration tests pass and the deployed endpoint was exercised.",
        "status": "completed",
        "candidate_confirmed": True,
    }
    values.update(changes)
    return CandidateProject(**values)


def _valid_pattern(**changes: object) -> HiringPattern:
    values: dict[str, object] = {
        "id": "pattern-acme-platform",
        "company": "Acme",
        "role_family": "Platform Engineer",
        "criteria": (
            HiringPatternCriterion(
                skill="Docker",
                weight=1,
                source_quote="The authorized aggregate lists Docker as a recurring capability.",
            ),
            HiringPatternCriterion(
                skill="AWS",
                weight=1,
                source_quote="The authorized aggregate lists AWS as a recurring capability.",
            ),
        ),
        "source_url": "https://careers.acme.example/hiring-patterns/platform-engineering",
        "valid_from": date(2025, 1, 1),
        "valid_to": date(2027, 1, 1),
        "rights_attested": True,
        "anonymisation_attested": True,
        "minimum_cohort_size": 3,
    }
    values.update(changes)
    return HiringPattern(**values)


def test_completed_confirmed_project_adds_only_explicit_supported_skills() -> None:
    assessment = calculate_evidence_match(
        _candidate(), _job(), projects=(_completed_project(),)
    )

    # The baseline remains the normal, confirmed-CV match: Python only.
    assert assessment.role_coverage == 40
    # Docker and AWS have full, explicit project evidence.  The project score is
    # separate from the CV score and is based on declared project skills, not
    # wording in the contribution field.
    assert assessment.project_coverage == 60
    assert tuple(assessment.matched_project_titles) == ("Reliable API service",)
    assert assessment.score is not None
    assert assessment.score > assessment.role_coverage


@pytest.mark.parametrize(
    "project",
    (
        _completed_project(status="planned"),
        _completed_project(candidate_confirmed=False),
        _completed_project(
            proofs=(
                ProjectProof(
                    kind="repository",
                    reference="https://github.com/example/reliable-api",
                    confirmed=False,
                ),
                ProjectProof(
                    kind="test",
                    reference="https://github.com/example/reliable-api/actions",
                    confirmed=False,
                ),
            )
        ),
        _completed_project(outcome_or_test=None),
    ),
    ids=("planned", "not-candidate-confirmed", "unconfirmed-proof", "no-outcome"),
)
def test_non_evidence_projects_cannot_raise_the_hiring_match(project: CandidateProject) -> None:
    baseline = calculate_evidence_match(_candidate(), _job())
    assessment = calculate_evidence_match(_candidate(), _job(), projects=(project,))

    assert assessment.project_coverage is None
    assert not assessment.matched_project_titles
    assert assessment.score == baseline.score


def test_unrelated_completed_project_does_not_create_a_zero_score_component() -> None:
    baseline = calculate_evidence_match(_candidate(), _job())
    assessment = calculate_evidence_match(
        _candidate(), _job(), projects=(_completed_project(skills=("React",)),)
    )

    assert assessment.project_status == "no_matching_project_evidence"
    assert assessment.project_coverage is None
    assert not assessment.matched_project_titles
    assert assessment.score == baseline.score


def test_partially_proven_project_is_not_reported_as_full_project_evidence() -> None:
    assessment = calculate_evidence_match(
        _candidate(),
        _job(),
        projects=(
            _completed_project(
                proofs=(
                    ProjectProof(
                        kind="repository",
                        reference="https://github.com/example/reliable-api",
                        confirmed=True,
                    ),
                ),
            ),
        ),
    )

    assert assessment.project_coverage is not None
    assert assessment.project_status == "scored"
    support_by_skill = {support.skill: support.support for support in assessment.requirement_supports}
    assert support_by_skill == {"Python": 0.0, "Docker": 0.7, "AWS": 0.7}
    assert tuple(assessment.matched_project_titles) == ("Reliable API service",)


def test_valid_scoped_aggregate_pattern_can_be_compared_with_supported_evidence() -> None:
    baseline = calculate_evidence_match(_candidate(), _job(), projects=(_completed_project(),))
    assessment = calculate_evidence_match(
        _candidate(),
        _job(),
        projects=(_completed_project(),),
        patterns=(_valid_pattern(),),
    )

    assert assessment.pattern_coverage == 100
    assert assessment.score is not None
    assert baseline.score is not None
    assert assessment.score > baseline.score


@pytest.mark.parametrize(
    "changes",
    (
        {"minimum_cohort_size": 2},
        {"rights_attested": False},
        {"anonymisation_attested": False},
        {"valid_to": date(2020, 1, 1)},
    ),
    ids=("small-cohort", "no-rights", "not-anonymised", "invalid-date-range"),
)
def test_hiring_pattern_rejects_unsafe_aggregate_contracts(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _valid_pattern(**changes)


@pytest.mark.parametrize(
    "pattern",
    (
        _valid_pattern(company="Other Company"),
        _valid_pattern(role_family="Data Analyst"),
        _valid_pattern(valid_from=date(2019, 1, 1), valid_to=date(2020, 1, 1)),
    ),
    ids=("other-company", "other-role", "expired"),
)
def test_unscoped_or_unattested_hiring_patterns_cannot_change_a_score(pattern: HiringPattern) -> None:
    baseline = calculate_evidence_match(_candidate(), _job(), projects=(_completed_project(),))
    assessment = calculate_evidence_match(
        _candidate(), _job(), projects=(_completed_project(),), patterns=(pattern,)
    )

    assert assessment.pattern_coverage is None
    assert assessment.score == baseline.score
