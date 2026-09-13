"""Small local SQLite store for user-owned analysis snapshots and audit records."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

from tau_job_application.models import AnalysisResult


class LocalStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    candidate_name TEXT NOT NULL,
                    job_title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    match_score INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
            """)

    def save_analysis(self, result: AnalysisResult) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO analyses (created_at, candidate_name, job_title, company, match_score, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                (self._now(), result.candidate.name, result.job.title, result.job.company, result.match.score, result.model_dump_json()),
            )
            return int(cursor.lastrowid)

    def list_analyses(self, limit: int = 20) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id, created_at, candidate_name, job_title, company, match_score FROM analyses ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def record_event(self, event_type: str, details: dict[str, object]) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO audit_events (created_at, event_type, details_json) VALUES (?, ?, ?)", (self._now(), event_type, json.dumps(details)))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
