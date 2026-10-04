from __future__ import annotations

import pytest

from tau_job_application.evidence_match_store import EvidenceMatchStore
from tau_job_application.hiring_match import CandidateProject, ProjectProof
from tau_job_application.workspaces import WorkspaceStore


def _project(project_id: str = "project-1") -> CandidateProject:
    return CandidateProject(
        id=project_id,
        title="Reliable API",
        skills=("Python", "Docker"),
        contribution="Designed the API contract and built the containerized service.",
        proofs=(ProjectProof(kind="repository", reference="https://example.test/reliable-api", confirmed=True),),
        outcome_or_test="The end-to-end test suite passes locally.",
        candidate_confirmed=True,
    )


def test_projects_are_scoped_to_one_job_workspace_and_updatable(tmp_path) -> None:
    db = tmp_path / "local.sqlite"
    workspaces = WorkspaceStore(db)
    evidence = EvidenceMatchStore(db)
    one, two = workspaces.create_workspace("One"), workspaces.create_workspace("Two")
    first = workspaces.create_thread(one, "First")
    second = workspaces.create_thread(two, "Second")

    evidence.save_project(one, first, _project())
    assert [project.title for project in evidence.list_projects(one, first)] == ["Reliable API"]
    assert evidence.list_projects(two, second) == []
    with pytest.raises(ValueError):
        evidence.list_projects(two, first)
    with pytest.raises(ValueError):
        evidence.save_project(two, first, _project())

    revised = _project().model_copy(update={"title": "Reliable API v2"})
    evidence.save_project(one, first, revised)
    assert [project.title for project in evidence.list_projects(one, first)] == ["Reliable API v2"]


def test_deleting_a_job_workspace_cascades_its_project_evidence(tmp_path) -> None:
    db = tmp_path / "local.sqlite"
    workspaces = WorkspaceStore(db)
    evidence = EvidenceMatchStore(db)
    workspace_id = workspaces.create_workspace("One")
    thread_id = workspaces.create_thread(workspace_id, "First")
    evidence.save_project(workspace_id, thread_id, _project())

    workspaces.delete_thread(workspace_id, thread_id)

    with evidence._connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM career_project_evidence WHERE thread_id=?", (thread_id,)
        ).fetchone()[0]
    assert count == 0
