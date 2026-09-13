"""User-triggered job-source monitoring with local deduplication and auditability.

There is intentionally no background scraper or hidden scheduler. A user refreshes a
configured, permitted source, then this module records the stable source snapshot
and reports jobs not seen in prior refreshes.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3

from tau_job_application.models import JobPosting


class JobMonitor:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS job_watches (
                    watch_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    identifier TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_checked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS watched_jobs (
                    watch_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    job_json TEXT NOT NULL,
                    PRIMARY KEY (watch_key, fingerprint),
                    FOREIGN KEY (watch_key) REFERENCES job_watches(watch_key)
                );
            """)

    def refresh(self, *, source: str, identifier: str, jobs: list[JobPosting]) -> list[JobPosting]:
        """Record a user-initiated permitted-source response and return newly seen jobs."""
        if not source.strip() or not identifier.strip():
            raise ValueError("A source and identifier are required for monitoring")
        watch_key = self._watch_key(source, identifier)
        now = datetime.now(UTC).isoformat()
        new_jobs = []
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO job_watches (watch_key, source, identifier, created_at) VALUES (?, ?, ?, ?)",
                (watch_key, source, identifier, now),
            )
            for job in jobs:
                fingerprint = self._job_fingerprint(job)
                exists = connection.execute("SELECT 1 FROM watched_jobs WHERE watch_key = ? AND fingerprint = ?", (watch_key, fingerprint)).fetchone()
                if exists is None:
                    new_jobs.append(job)
                    connection.execute(
                        "INSERT INTO watched_jobs (watch_key, fingerprint, first_seen_at, last_seen_at, job_json) VALUES (?, ?, ?, ?, ?)",
                        (watch_key, fingerprint, now, now, job.model_dump_json()),
                    )
                else:
                    connection.execute(
                        "UPDATE watched_jobs SET last_seen_at = ?, job_json = ? WHERE watch_key = ? AND fingerprint = ?",
                        (now, job.model_dump_json(), watch_key, fingerprint),
                    )
            connection.execute("UPDATE job_watches SET last_checked_at = ? WHERE watch_key = ?", (now, watch_key))
        return new_jobs

    def watches(self) -> list[dict[str, str | int | None]]:
        with self._connect() as connection:
            rows = connection.execute("""
                SELECT watch_key, source, identifier, created_at, last_checked_at,
                       (SELECT COUNT(*) FROM watched_jobs wj WHERE wj.watch_key = jw.watch_key) AS known_jobs
                FROM job_watches jw ORDER BY last_checked_at DESC
            """).fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _watch_key(source: str, identifier: str) -> str:
        return hashlib.sha256(f"{source.casefold()}\0{identifier.casefold()}".encode()).hexdigest()

    @staticmethod
    def _job_fingerprint(job: JobPosting) -> str:
        stable = {"url": job.url, "title": job.title.casefold(), "company": job.company.casefold(), "requirements": sorted((requirement.skill.casefold(), requirement.required) for requirement in job.requirements)}
        return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
