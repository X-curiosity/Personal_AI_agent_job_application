"""Local, user-controlled state for public Role Market openings.

This store deliberately records only the candidate's *viewing* choices:
``Saved``, ``Hidden``, and ``Tracking``.  It does not infer that an
application was submitted, an employer was contacted, or a hiring process has
started.  Each record is bound to one Job Workspace thread and retains the
source opening snapshot that the candidate acted on, so a later discovery
refresh cannot erase a saved item.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
import sqlite3

from pydantic import BaseModel, Field, field_validator

from tau_job_application.role_discovery import DiscoveredOpening


class RoleMarketStatus(str, Enum):
    """Candidate-controlled Role Market states; none imply an application."""

    SAVED = "saved"
    HIDDEN = "hidden"
    TRACKING = "tracking"

    @property
    def label(self) -> str:
        """A short presentation label without changing the stored value."""

        return self.value.title()


class RoleMarketState(BaseModel):
    """One candidate state plus the source opening snapshot it applies to."""

    opening_key: str = Field(min_length=1)
    status: RoleMarketStatus
    opening: DiscoveredOpening
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)

    @field_validator("opening_key", "created_at", "updated_at")
    @classmethod
    def _require_text(cls, value: str) -> str:
        if not isinstance(value, str) or not (cleaned := value.strip()):
            raise ValueError("Role Market state fields need text")
        return cleaned


def opening_key(opening: DiscoveredOpening) -> str:
    """Return a stable, source-owned identity for an opening.

    A canonical official listing URL is preferred.  Where a source does not
    expose one, its source/board/external-id triple is sufficient.  We do not
    fall back to a title, company name, description, or location: those are
    display fields and can change or collide across distinct openings.
    """

    if canonical_url := opening.canonical_url:
        return f"url:{canonical_url}"
    if opening.source_identifier and opening.external_id:
        return "source:{}:{}:{}".format(
            opening.source.casefold(),
            opening.source_identifier.casefold(),
            opening.external_id.casefold(),
        )
    raise ValueError(
        "A Role Market state needs a canonical source URL or source, board, and external ID"
    )


class RoleMarketStateStore:
    """Persist Role Market state per Job Workspace with strict scope checks.

    ``career_track_id`` is accepted on every public operation and verified
    against ``career_threads.workspace_id``.  The database key is the thread
    plus an opening's source-owned identity, allowing state to follow a thread
    if the candidate reorganizes that thread into a different career track.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS role_market_states (
                    thread_id TEXT NOT NULL REFERENCES career_threads(id) ON DELETE CASCADE,
                    opening_key TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('saved', 'hidden', 'tracking')),
                    opening_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (thread_id, opening_key)
                );
                CREATE INDEX IF NOT EXISTS role_market_states_thread_status_idx
                    ON role_market_states(thread_id, status, updated_at, opening_key);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _scope_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not (cleaned := value.strip()):
            raise ValueError(f"{field_name} is required")
        return cleaned

    @classmethod
    def _thread(cls, db: sqlite3.Connection, career_track_id: str, thread_id: str) -> None:
        career_track_id = cls._scope_text(career_track_id, "Career track ID")
        thread_id = cls._scope_text(thread_id, "Thread ID")
        row = db.execute(
            "SELECT 1 FROM career_threads WHERE workspace_id=? AND id=?",
            (career_track_id, thread_id),
        ).fetchone()
        if row is None:
            raise ValueError("Job workspace not found in this career direction")

    @staticmethod
    def _status(status: RoleMarketStatus | str) -> RoleMarketStatus:
        if isinstance(status, RoleMarketStatus):
            return status
        if isinstance(status, str):
            try:
                return RoleMarketStatus(status.strip().casefold())
            except ValueError as exc:
                raise ValueError("Role Market status must be Saved, Hidden, or Tracking") from exc
        raise ValueError("Role Market status must be Saved, Hidden, or Tracking")

    @staticmethod
    def _snapshot(opening: DiscoveredOpening) -> str:
        snapshot = opening.model_dump_json()
        if len(snapshot) > 250_000:
            raise ValueError("Role Market source snapshot is limited to 250,000 characters")
        return snapshot

    @staticmethod
    def _decode(row: sqlite3.Row) -> RoleMarketState:
        return RoleMarketState(
            opening_key=row["opening_key"],
            status=row["status"],
            opening=DiscoveredOpening.model_validate_json(row["opening_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def set_status(
        self,
        career_track_id: str,
        thread_id: str,
        opening: DiscoveredOpening,
        status: RoleMarketStatus | str,
    ) -> RoleMarketState:
        """Create or update one viewing state and replace its source snapshot.

        Calling this with a refreshed copy of the same source opening updates
        only the stored source snapshot and state; it never creates a second
        record based on display text.
        """

        key = opening_key(opening)
        normalized_status = self._status(status)
        snapshot = self._snapshot(opening)
        now = self._now()
        with self._connect() as db:
            self._thread(db, career_track_id, thread_id)
            existing = db.execute(
                "SELECT created_at FROM role_market_states WHERE thread_id=? AND opening_key=?",
                (thread_id, key),
            ).fetchone()
            if existing is None:
                db.execute(
                    """
                    INSERT INTO role_market_states
                        (thread_id, opening_key, status, opening_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (thread_id, key, normalized_status.value, snapshot, now, now),
                )
                created_at = now
            else:
                db.execute(
                    """
                    UPDATE role_market_states
                    SET status=?, opening_json=?, updated_at=?
                    WHERE thread_id=? AND opening_key=?
                    """,
                    (normalized_status.value, snapshot, now, thread_id, key),
                )
                created_at = existing["created_at"]
        return RoleMarketState(
            opening_key=key,
            status=normalized_status,
            opening=opening,
            created_at=created_at,
            updated_at=now,
        )

    def state_for(
        self,
        career_track_id: str,
        thread_id: str,
        opening: DiscoveredOpening,
    ) -> RoleMarketState | None:
        """Return this thread's state for the source identity, if it has one."""

        key = opening_key(opening)
        with self._connect() as db:
            self._thread(db, career_track_id, thread_id)
            row = db.execute(
                """
                SELECT opening_key, status, opening_json, created_at, updated_at
                FROM role_market_states
                WHERE thread_id=? AND opening_key=?
                """,
                (thread_id, key),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def list_states(self, career_track_id: str, thread_id: str) -> list[RoleMarketState]:
        """Return saved snapshots, newest state change first, for one thread."""

        with self._connect() as db:
            self._thread(db, career_track_id, thread_id)
            rows = db.execute(
                """
                SELECT opening_key, status, opening_json, created_at, updated_at
                FROM role_market_states
                WHERE thread_id=?
                ORDER BY updated_at DESC, opening_key
                """,
                (thread_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def clear_status(
        self,
        career_track_id: str,
        thread_id: str,
        opening: DiscoveredOpening,
    ) -> None:
        """Remove a candidate-controlled viewing state from one thread."""

        key = opening_key(opening)
        with self._connect() as db:
            self._thread(db, career_track_id, thread_id)
            db.execute(
                "DELETE FROM role_market_states WHERE thread_id=? AND opening_key=?",
                (thread_id, key),
            )
