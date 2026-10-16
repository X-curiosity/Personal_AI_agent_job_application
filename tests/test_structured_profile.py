import pytest

from tau_job_application.application_tracker import ApplicationTrackerStore
from tau_job_application.career_hub import HubStore, Interests
from tau_job_application.eligibility import ResidencyProfile, ResidencyStore
from tau_job_application.evidence_match_store import EvidenceMatchStore
from tau_job_application.hiring_match import CandidateProject, ProjectStatus
from tau_job_application.interview import (
    MAX_LEVEL,
    build_interview_questions,
    difficulty_level,
    level_progress,
)
from tau_job_application.parsing import parse_candidate_text, parse_job_text
from tau_job_application.structured_profile import (
    RecruiterCriteria,
    build_structured_profile,
    evaluate_recruiter_query,
)
from tau_job_application.workspaces import WorkspaceStore


def _attempt(score):
    return {"score": score, "category": "technical", "question_id": "q"}


def test_difficulty_level_progression_rule():
    assert difficulty_level([]) == 1
    assert difficulty_level([_attempt(80), _attempt(90)]) == 1
    assert difficulty_level([_attempt(80)] * 3) == 2
    assert difficulty_level([_attempt(80)] * 3 + [_attempt(10)]) == 2
    assert difficulty_level([_attempt(90)] * 6) == 3
    assert difficulty_level([_attempt(90)] * 100) == MAX_LEVEL
    assert level_progress([_attempt(80)]) == (1, 3)
    assert level_progress([_attempt(80)] * 3) == (0, 3)
    assert level_progress([_attempt(80)] * 100) == (3, 3)


def test_questions_get_harder_with_level():
    candidate = parse_candidate_text("Name: Alex\nSkills: Python")
    job = parse_job_text("Title: Backend Engineer\nCompany: Example\nRequired skills: Python, Docker")
    level_one = build_interview_questions(candidate, job, level=1)
    level_five = build_interview_questions(candidate, job, level=5)
    tech_one = next(q.question for q in level_one if q.id == "technical-1")
    tech_five = next(q.question for q in level_five if q.id == "technical-1")
    assert "Walk me through" in tech_one
    assert "Cross-examination" in tech_five and "Python" in tech_five
    assert any(q.id == "ambiguity" for q in build_interview_questions(candidate, job, level=4))
    assert not any(q.id == "ambiguity" for q in level_one)
    with pytest.raises(ValueError):
        build_interview_questions(candidate, job, level=6)


def _seed(tmp_path):
    database = tmp_path / "db.sqlite"
    workspaces = WorkspaceStore(database)
    track = workspaces.create_workspace("Hardware")
    workspaces.save_shared_profile({
        "cv_text": "Name: Alex Example\nSkills: Python, SQL\nExperience: Built a Python service with automated tests.",
        "github": "https://github.com/alex", "portfolio": "", "linkedin": "", "x": "",
    })
    hub = HubStore(database)
    hub.save_interests(track, Interests(fields=["Engineering"], subfields=[], roles=["Hardware Engineer"]))
    residency = ResidencyStore(database)
    residency.save(track, ResidencyProfile(citizenships=("France",), residence_country="France"))
    evidence = EvidenceMatchStore(database)
    thread = workspaces.create_thread(track, "Hardware Engineer — Example Co")
    evidence.save_project(track, thread, CandidateProject(
        id="p1", title="RISC-V toy core", skills=("Python",), contribution="Designed and tested the core",
        status=ProjectStatus.COMPLETED,
    ))
    evidence.save_project(track, thread, CandidateProject(
        id="p2", title="Planned FPGA build", skills=("Verilog",), contribution="Only a plan so far",
        status=ProjectStatus.PLANNED,
    ))
    applications = ApplicationTrackerStore(database)
    return workspaces, hub, residency, evidence, applications, track


def test_build_structured_profile_aggregates_local_stores(tmp_path):
    workspaces, hub, residency, evidence, applications, track = _seed(tmp_path)
    profile = build_structured_profile(
        workspaces=workspaces, hub_store=hub, residency_store=residency,
        evidence_store=evidence, application_store=applications, track=track,
    )
    assert profile.full_name == "Alex Example"
    assert profile.links == {"github": "https://github.com/alex"}
    assert profile.citizenships == ("France",) and profile.residence_country == "France"
    assert set(profile.skills) == {"Python", "SQL"}
    titles = {project.title: project.status for project in profile.evidence_projects}
    assert titles == {"RISC-V toy core": "completed", "Planned FPGA build": "planned"}
    assert profile.role_targets == ("Hardware Engineer",)
    assert profile.interview.current_level == 1 and profile.interview.rehearsals == 0
    # Export is valid JSON the user can hand to anyone.
    assert '"full_name":"Alex Example"' in profile.model_dump_json()


def test_recruiter_query_failures_flags_and_pass(tmp_path):
    workspaces, hub, residency, evidence, applications, track = _seed(tmp_path)
    profile = build_structured_profile(
        workspaces=workspaces, hub_store=hub, residency_store=residency,
        evidence_store=evidence, application_store=applications, track=track,
    )
    passing = evaluate_recruiter_query(profile, RecruiterCriteria(
        skills_all=("Python",), min_completed_projects=1, job_country="Germany",
    ))
    assert passing.qualified
    assert passing.reasons == ("All criteria satisfied.",)

    sponsorship = evaluate_recruiter_query(profile, RecruiterCriteria(job_country="United States"))
    assert sponsorship.qualified  # sponsorship is a flag, not a rejection
    assert any("sponsorship" in reason for reason in sponsorship.reasons)

    failing = evaluate_recruiter_query(profile, RecruiterCriteria(
        skills_all=("Rust",), min_completed_projects=2, min_interview_level=3,
    ))
    assert not failing.qualified
    assert any("Rust" in reason for reason in failing.reasons)
    assert any("completed evidence project" in reason for reason in failing.reasons)
    assert any("Interview level" in reason for reason in failing.reasons)

    no_residency = evaluate_recruiter_query(
        profile.model_copy(update={"citizenships": (), "residence_country": None}),
        RecruiterCriteria(job_country="Germany"),
    )
    assert not no_residency.qualified
    assert any("residency profile" in reason for reason in no_residency.reasons)
