"""Local, explicitly reviewed extraction memory; never trains on CVs or mere frequency."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from tau_job_application.models import EvidenceItem, JobRequirement


def document_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RequirementMemory:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS skill_alias_memory (
                    phrase TEXT PRIMARY KEY, skill TEXT NOT NULL, source_quote TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requirement_reviews (
                    document_hash TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requirement_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, document_hash TEXT NOT NULL,
                    rating TEXT NOT NULL, comment TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)

    def _connect(self):
        return sqlite3.connect(self.path)

    def aliases(self) -> dict[str, str]:
        with self._connect() as db:
            return dict(db.execute("SELECT phrase, skill FROM skill_alias_memory ORDER BY phrase"))

    def learn_alias(self, phrase: str, skill: str, *, source_quote: str, user_confirmed: bool) -> None:
        phrase, skill = phrase.strip(), skill.strip()
        if not user_confirmed:
            raise ValueError("A user must explicitly confirm a reusable mapping")
        if not 2 <= len(phrase) <= 120 or not 1 <= len(skill) <= 100:
            raise ValueError("Use a short source phrase and a concise skill name")
        if not re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", source_quote, re.I):
            raise ValueError("The phrase must occur in the reviewed source quote")
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO skill_alias_memory VALUES (?, ?, ?, ?)",
                       (phrase.casefold(), skill, source_quote, datetime.now(UTC).isoformat()))

    def forget_alias(self, phrase: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM skill_alias_memory WHERE phrase = ?", (phrase.casefold(),))

    def save_review(self, text: str, requirements: list[JobRequirement], evidence: list[EvidenceItem]) -> None:
        if not requirements:
            raise ValueError("Keep or add at least one requirement before saving")
        by_id = {item.id: item for item in evidence}
        if len(by_id) != len(evidence) or len({r.evidence_id for r in requirements}) != len(requirements):
            raise ValueError("Review evidence IDs must be unique")
        for requirement in requirements:
            item = by_id.get(requirement.evidence_id)
            if item is None or item.quote not in text:
                raise ValueError("Each reviewed skill must cite exact text from this job description")
            if requirement.required != (requirement.importance != "preferred"):
                raise ValueError("Requirement importance and required flag disagree")
            if requirement.extraction_method != "reviewed":
                raise ValueError("Only user-reviewed requirements can be saved")
        payload = json.dumps({"requirements": [r.model_dump() for r in requirements],
                              "evidence": [e.model_dump() for e in evidence]})
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO requirement_reviews VALUES (?, ?, ?)",
                       (document_key(text), payload, datetime.now(UTC).isoformat()))

    def save_feedback(self, text: str, rating: str, comment: str = "") -> None:
        if rating not in {"useful", "partly useful", "not useful"}:
            raise ValueError("Choose a supported extraction feedback rating")
        if len(comment) > 2_000:
            raise ValueError("Feedback is limited to 2,000 characters")
        with self._connect() as db:
            db.execute("INSERT INTO requirement_feedback (document_hash, rating, comment, created_at) VALUES (?, ?, ?, ?)",
                       (document_key(text), rating, comment.strip(), datetime.now(UTC).isoformat()))

    def feedback(self, text: str) -> list[dict[str, str]]:
        with self._connect() as db:
            rows = db.execute("SELECT rating, comment, created_at FROM requirement_feedback WHERE document_hash=? ORDER BY id DESC", (document_key(text),)).fetchall()
        return [{"rating": row[0], "comment": row[1], "created_at": row[2]} for row in rows]

    def reviewed(self, text: str) -> tuple[list[JobRequirement], list[EvidenceItem]] | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM requirement_reviews WHERE document_hash = ?", (document_key(text),)).fetchone()
        if not row:
            return None
        payload = json.loads(row[0])
        return ([JobRequirement.model_validate(r) for r in payload["requirements"]],
                [EvidenceItem.model_validate(e) for e in payload["evidence"]])

    def forget_review(self, text: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM requirement_reviews WHERE document_hash = ?", (document_key(text),))
