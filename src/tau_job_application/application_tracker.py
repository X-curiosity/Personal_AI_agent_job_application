"""Candidate-entered application progress, saved openings, and change history."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from tau_job_application.role_discovery import DiscoveredOpening
from tau_job_application.role_market_state import opening_key


class ApplicationStage(str, Enum):
    SAVED = "saved"
    PREPARING = "preparing"
    APPLIED = "applied"
    CONTACTED = "contacted"
    INTERVIEW = "interview"
    OFFER = "offer"
    CLOSED = "closed"

    @property
    def label(self) -> str:
        return self.value.title()


class ApplicationProgress(BaseModel):
    """Editable candidate facts. Availability is independent of progress."""

    stage: ApplicationStage = ApplicationStage.SAVED
    stage_on: date | None = None
    applied_on: date | None = None
    deadline: date | None = None
    next_step: str = Field(default="", max_length=500)
    next_step_on: date | None = None
    notes: str = Field(default="", max_length=10_000)
    closed_reason: str = ""
    availability: str = "unverified"

    @field_validator("next_step", "notes", "closed_reason", "availability")
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _consistent_fields(self):
        if self.next_step_on and not self.next_step:
            raise ValueError("Add a next step to go with its date")
        if self.closed_reason not in {"", "rejected", "withdrawn", "other"}:
            raise ValueError("Choose a valid closing reason")
        if self.stage is not ApplicationStage.CLOSED and self.closed_reason:
            raise ValueError("A closing reason belongs to a closed application")
        if self.availability not in {"unverified", "open", "expired"}:
            raise ValueError("Choose a valid listing availability")
        return self


class TrackedApplication(BaseModel):
    id: str
    thread_id: str
    opening_key: str
    opening: DiscoveredOpening
    progress: ApplicationProgress
    relevance: int | None = Field(default=None, ge=0, le=100)
    created_at: str
    updated_at: str


class ApplicationEvent(BaseModel):
    id: int
    action: str
    occurred_at: str
    changed_fields: tuple[str, ...]
    progress: ApplicationProgress


class ApplicationTrackerStore:
    """SQLite progress tied to an official opening inside a job workspace.

    Saving an existing opening is idempotent and never resets progress or its
    original source snapshot. A thread move keeps its tracker/history. All
    operations check the owning career track; deletion cascades with the thread.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tracked_applications (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES career_threads(id) ON DELETE CASCADE,
                    opening_key TEXT NOT NULL,
                    opening_json TEXT NOT NULL,
                    progress_json TEXT NOT NULL,
                    relevance INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(thread_id, opening_key)
                );
                CREATE TABLE IF NOT EXISTS application_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id TEXT NOT NULL REFERENCES tracked_applications(id) ON DELETE CASCADE,
                    action TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    changed_fields_json TEXT NOT NULL,
                    progress_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS application_events_application_idx
                    ON application_events(application_id, id);
                CREATE TABLE IF NOT EXISTS application_shortlist_imports (
                    thread_id TEXT NOT NULL REFERENCES career_threads(id) ON DELETE CASCADE,
                    opening_key TEXT NOT NULL,
                    PRIMARY KEY(thread_id, opening_key)
                );
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
    def _thread(db, career_track_id: str, thread_id: str) -> None:
        if not db.execute(
            "SELECT 1 FROM career_threads WHERE workspace_id=? AND id=?", (career_track_id, thread_id)
        ).fetchone():
            raise ValueError("Job workspace not found in this career track")

    @staticmethod
    def _owned_row(db, career_track_id: str, application_id: str):
        row = db.execute("""
            SELECT a.* FROM tracked_applications a JOIN career_threads t ON t.id=a.thread_id
            WHERE t.workspace_id=? AND a.id=?
        """, (career_track_id, application_id)).fetchone()
        if row is None:
            raise ValueError("Application not found in this career track")
        return row

    @staticmethod
    def _decode(row) -> TrackedApplication:
        return TrackedApplication(
            id=row["id"], thread_id=row["thread_id"], opening_key=row["opening_key"],
            opening=DiscoveredOpening.model_validate_json(row["opening_json"]),
            progress=ApplicationProgress.model_validate_json(row["progress_json"]),
            relevance=row["relevance"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _event(db, application_id: str, action: str, now: str, changed, progress: ApplicationProgress):
        db.execute("""
            INSERT INTO application_events
                (application_id, action, occurred_at, changed_fields_json, progress_json)
            VALUES (?, ?, ?, ?, ?)
        """, (application_id, action, now, json.dumps(list(changed)), progress.model_dump_json()))

    def _insert_saved(self, db, thread_id, opening, *, relevance=None, now=None, action="saved"):
        key = opening_key(opening)
        existing = db.execute(
            "SELECT * FROM tracked_applications WHERE thread_id=? AND opening_key=?", (thread_id, key)
        ).fetchone()
        if existing:
            return self._decode(existing)
        snapshot = opening.model_dump_json()
        if len(snapshot) > 250_000:
            raise ValueError("The saved opening is too large")
        now = now or self._now()
        record = TrackedApplication(
            id=uuid4().hex, thread_id=thread_id, opening_key=key, opening=opening,
            progress=ApplicationProgress(), relevance=relevance, created_at=now, updated_at=now,
        )
        db.execute("""
            INSERT INTO tracked_applications
                (id, thread_id, opening_key, opening_json, progress_json, relevance, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (record.id, thread_id, key, snapshot, record.progress.model_dump_json(), relevance, now, now))
        self._event(db, record.id, action, now, (), record.progress)
        return record

    def save(self, career_track_id: str, thread_id: str, opening: DiscoveredOpening, *, relevance=None):
        with self._connect() as db:
            self._thread(db, career_track_id, thread_id)
            return self._insert_saved(db, thread_id, opening, relevance=relevance)

    def import_shortlist(self, career_track_id: str) -> int:
        """Carry earlier saved/tracking choices forward as Saved, once per item.

        An import receipt survives removing a tracker record, so a later render
        never resurrects a record the candidate removed. Hidden rows are ignored.
        """
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM career_workspaces WHERE id=?", (career_track_id,)).fetchone():
                raise ValueError("Career track not found")
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='role_market_states'").fetchone():
                return 0
            rows = db.execute("""
                SELECT s.* FROM role_market_states s JOIN career_threads t ON t.id=s.thread_id
                WHERE t.workspace_id=? AND s.status IN ('saved','tracking')
                AND NOT EXISTS (SELECT 1 FROM application_shortlist_imports i
                    WHERE i.thread_id=s.thread_id AND i.opening_key=s.opening_key)
            """, (career_track_id,)).fetchall()
            for row in rows:
                opening = DiscoveredOpening.model_validate_json(row["opening_json"])
                self._insert_saved(db, row["thread_id"], opening, now=row["created_at"], action="imported_saved_role")
                db.execute("INSERT INTO application_shortlist_imports VALUES (?, ?)",
                           (row["thread_id"], row["opening_key"]))
            return len(rows)

    def list_records(self, career_track_id: str, *, thread_id: str | None = None):
        with self._connect() as db:
            if thread_id:
                self._thread(db, career_track_id, thread_id)
            elif not db.execute("SELECT 1 FROM career_workspaces WHERE id=?", (career_track_id,)).fetchone():
                raise ValueError("Career track not found")
            rows = db.execute("""
                SELECT a.* FROM tracked_applications a JOIN career_threads t ON t.id=a.thread_id
                WHERE t.workspace_id=? AND (? IS NULL OR a.thread_id=?)
                ORDER BY a.updated_at DESC, a.id
            """, (career_track_id, thread_id, thread_id)).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, career_track_id: str, application_id: str):
        with self._connect() as db:
            return self._decode(self._owned_row(db, career_track_id, application_id))

    def update(self, career_track_id: str, application_id: str, progress: ApplicationProgress,
               *, expected_updated_at: str | None = None):
        progress = ApplicationProgress.model_validate(progress.model_dump())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = self._decode(self._owned_row(db, career_track_id, application_id))
            if expected_updated_at and expected_updated_at != previous.updated_at:
                raise ValueError("This application changed in another view. Reload before saving your edits.")
            changed = tuple(name for name in ApplicationProgress.model_fields
                            if getattr(previous.progress, name) != getattr(progress, name))
            if not changed:
                return previous
            now = self._now()
            db.execute("UPDATE tracked_applications SET progress_json=?, updated_at=? WHERE id=?",
                       (progress.model_dump_json(), now, application_id))
            self._event(db, application_id, "updated", now, changed, progress)
        return previous.model_copy(update={"progress": progress, "updated_at": now})

    def history(self, career_track_id: str, application_id: str):
        with self._connect() as db:
            self._owned_row(db, career_track_id, application_id)
            rows = db.execute("SELECT * FROM application_events WHERE application_id=? ORDER BY id DESC",
                              (application_id,)).fetchall()
        return [ApplicationEvent(id=row["id"], action=row["action"], occurred_at=row["occurred_at"],
                                 changed_fields=tuple(json.loads(row["changed_fields_json"])),
                                 progress=ApplicationProgress.model_validate_json(row["progress_json"])) for row in rows]

    def delete(self, career_track_id: str, application_id: str) -> None:
        with self._connect() as db:
            record = self._decode(self._owned_row(db, career_track_id, application_id))
            db.execute("INSERT OR IGNORE INTO application_shortlist_imports VALUES (?, ?)",
                       (record.thread_id, record.opening_key))
            db.execute("DELETE FROM tracked_applications WHERE id=?", (application_id,))
