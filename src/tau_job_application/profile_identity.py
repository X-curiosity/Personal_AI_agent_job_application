"""Local profile identity: your name and email, saved only in the local database.

This is deliberately not an account: there is no password, no verification, no
server, and nothing is sent anywhere. It is the identity the app uses when it
needs to know who you are locally — prefilling document drafts and addressing
reply review — stored permission-locked alongside everything else.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
import sqlite3

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


class ProfileIdentity(BaseModel):
    """One candidate identity row; single-row store, editable and removable."""

    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    updated_at: str

    @field_validator("name")
    @classmethod
    def name_is_clean(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Enter your name")
        return cleaned

    @field_validator("email")
    @classmethod
    def email_looks_valid(cls, value: str) -> str:
        cleaned = value.strip().casefold()
        if not _EMAIL_RE.fullmatch(cleaned):
            raise ValueError("Enter a valid email address")
        return cleaned


class ProfileIdentityStore:
    """Single-row SQLite store inside the existing local database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS profile_identity (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def load(self) -> ProfileIdentity | None:
        with self._connect() as db:
            row = db.execute("SELECT name, email, updated_at FROM profile_identity WHERE id=1").fetchone()
        return ProfileIdentity(**dict(row)) if row else None

    def save(self, name: str, email: str) -> ProfileIdentity:
        record = ProfileIdentity(
            name=name, email=email, updated_at=datetime.now(UTC).isoformat(),
        )
        with self._connect() as db:
            db.execute(
                """INSERT INTO profile_identity(id, name, email, updated_at) VALUES(1,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, email=excluded.email, updated_at=excluded.updated_at""",
                (record.name, record.email, record.updated_at),
            )
        return record

    def clear(self) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM profile_identity WHERE id=1")
        return cursor.rowcount > 0
