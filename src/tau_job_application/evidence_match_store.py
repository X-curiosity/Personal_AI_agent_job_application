"""SQLite persistence for candidate-confirmed project evidence.

The records belong to one Job Workspace.  They are kept outside a CV draft and
outside an analysis snapshot so a candidate can add, correct, or delete proof
without silently changing an older job analysis.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from tau_job_application.hiring_match import CandidateProject


class EvidenceMatchStore:
    """Persist only candidate-owned project records, scoped to a career thread."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS career_project_evidence (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES career_threads(id) ON DELETE CASCADE,
                    project_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS career_project_evidence_thread_idx
                    ON career_project_evidence(thread_id, created_at, id);
            """)

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _thread(db, workspace_id: str, thread_id: str) -> None:
        row = db.execute(
            "SELECT 1 FROM career_threads WHERE workspace_id=? AND id=?",
            (workspace_id, thread_id),
        ).fetchone()
        if row is None:
            raise ValueError("Job workspace not found in this career direction")

    def list_projects(self, workspace_id: str, thread_id: str) -> list[CandidateProject]:
        with self._connect() as db:
            self._thread(db, workspace_id, thread_id)
            rows = db.execute(
                "SELECT project_json FROM career_project_evidence WHERE thread_id=? ORDER BY created_at, id",
                (thread_id,),
            ).fetchall()
        return [CandidateProject.model_validate_json(row["project_json"]) for row in rows]

    def save_project(
        self,
        workspace_id: str,
        thread_id: str,
        project: CandidateProject,
    ) -> CandidateProject:
        """Create or replace one scoped project record after scope validation."""

        if len(projects_json := project.model_dump_json()) > 20_000:
            raise ValueError("Project evidence is limited to 20,000 characters")
        now = self._now()
        with self._connect() as db:
            self._thread(db, workspace_id, thread_id)
            existing = db.execute(
                "SELECT 1 FROM career_project_evidence WHERE id=? AND thread_id=?",
                (project.id, thread_id),
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE career_project_evidence SET project_json=?, updated_at=? WHERE id=? AND thread_id=?",
                    (projects_json, now, project.id, thread_id),
                )
            else:
                db.execute(
                    "INSERT INTO career_project_evidence (id, thread_id, project_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (project.id, thread_id, projects_json, now, now),
                )
        return project

    def create_project(
        self,
        workspace_id: str,
        thread_id: str,
        **fields,
    ) -> CandidateProject:
        """Assign a local opaque record id; titles/URLs never become database keys."""

        project = CandidateProject(id=uuid4().hex, **fields)
        return self.save_project(workspace_id, thread_id, project)

    def delete_project(self, workspace_id: str, thread_id: str, project_id: str) -> None:
        with self._connect() as db:
            self._thread(db, workspace_id, thread_id)
            deleted = db.execute(
                "DELETE FROM career_project_evidence WHERE id=? AND thread_id=?",
                (project_id, thread_id),
            ).rowcount
        if not deleted:
            raise ValueError("Project evidence not found in this job workspace")
