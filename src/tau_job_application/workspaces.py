"""Local career directions, independent job threads, shared profile and conversations.

Workspace names organize targets; they never filter jobs by exact title. Every
thread operation checks its parent workspace. Existing analysis tables are untouched.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from tau_job_application.matching import normalize_skill
from tau_job_application.models import AnalysisResult, SkillNode
from tau_job_application.planning import build_project_plans

PROFILE_FIELDS = ("cv_text", "github", "portfolio", "linkedin", "x")
DRAFT_FIELDS = (*PROFILE_FIELDS, "job_title", "company", "job_url", "job_text")


def fingerprint(draft: dict) -> str:
    return hashlib.sha256(json.dumps({key: draft.get(key, "") for key in DRAFT_FIELDS}, sort_keys=True).encode()).hexdigest()


def _clean_draft(draft: dict) -> dict[str, str]:
    if any(not isinstance(value, str) for key, value in draft.items() if key in DRAFT_FIELDS):
        raise ValueError("Draft fields must be text")
    result = {key: draft.get(key, "") for key in DRAFT_FIELDS}
    if sum(len(value) for value in result.values()) > 200_000:
        raise ValueError("Thread input is limited to 200,000 characters")
    return result


class WorkspaceStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS career_workspaces (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS career_threads (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES career_workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, draft_json TEXT NOT NULL, analysis_json TEXT,
                    analysis_fingerprint TEXT, invalidated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS career_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL REFERENCES career_threads(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL, mode TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS career_shared_profile (
                    id INTEGER PRIMARY KEY CHECK(id=1), profile_json TEXT NOT NULL, updated_at TEXT NOT NULL
                );
            """)

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _now():
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _name(name):
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("Choose a name between 1 and 100 characters")
        return name

    def list_workspaces(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM career_workspaces ORDER BY created_at, id")]

    def create_workspace(self, name: str) -> str:
        name, key = self._name(name), uuid4().hex
        with self._connect() as db:
            try:
                db.execute("INSERT INTO career_workspaces VALUES (?, ?, ?)", (key, name, self._now()))
            except sqlite3.IntegrityError as exc:
                raise ValueError("That career direction already exists") from exc
        return key

    def _workspace(self, db, workspace_id):
        if db.execute("SELECT 1 FROM career_workspaces WHERE id=?", (workspace_id,)).fetchone() is None:
            raise ValueError("Career direction not found")

    def _thread(self, db, workspace_id, thread_id):
        row = db.execute("SELECT * FROM career_threads WHERE workspace_id=? AND id=?", (workspace_id, thread_id)).fetchone()
        if row is None:
            raise ValueError("Thread not found in this career direction")
        return row

    def shared_profile(self) -> dict[str, str]:
        with self._connect() as db:
            row = db.execute("SELECT profile_json FROM career_shared_profile WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {key: "" for key in PROFILE_FIELDS}

    def save_shared_profile(self, profile: dict):
        profile = {key: value for key, value in _clean_draft(profile).items() if key in PROFILE_FIELDS}
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO career_shared_profile VALUES (1, ?, ?)", (json.dumps(profile), self._now()))

    def create_thread(self, workspace_id: str, name: str, draft: dict | None = None) -> str:
        key, name = uuid4().hex, self._name(name)
        inputs = _clean_draft(draft if draft is not None else self.shared_profile())
        now = self._now()
        with self._connect() as db:
            self._workspace(db, workspace_id)
            db.execute("INSERT INTO career_threads (id, workspace_id, name, draft_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (key, workspace_id, name, json.dumps(inputs), now, now))
        return key

    def list_threads(self, workspace_id):
        with self._connect() as db:
            self._workspace(db, workspace_id)
            rows = db.execute("SELECT * FROM career_threads WHERE workspace_id=? ORDER BY created_at, id", (workspace_id,)).fetchall()
        return [self._decode(row) for row in rows]

    @staticmethod
    def _decode(row):
        item = dict(row)
        item["draft"] = json.loads(item.pop("draft_json"))
        payload = item.pop("analysis_json")
        item["analysis"] = AnalysisResult.model_validate_json(payload) if payload else None
        item["stale"] = bool(payload) and (bool(item["invalidated"]) or item["analysis_fingerprint"] != fingerprint(item["draft"]))
        return item

    def thread(self, workspace_id, thread_id):
        with self._connect() as db:
            return self._decode(self._thread(db, workspace_id, thread_id))

    def save_draft(self, workspace_id, thread_id, draft: dict):
        draft = _clean_draft(draft)
        with self._connect() as db:
            row = self._thread(db, workspace_id, thread_id)
            if json.loads(row["draft_json"]) != draft:
                db.execute("UPDATE career_threads SET draft_json=?, updated_at=? WHERE id=?", (json.dumps(draft), self._now(), thread_id))

    def save_analysis(self, workspace_id, thread_id, result: AnalysisResult):
        with self._connect() as db:
            row = self._thread(db, workspace_id, thread_id)
            draft = json.loads(row["draft_json"])
            if (result.candidate.raw_cv != draft["cv_text"] or result.job.description != draft["job_text"] or
                (draft["job_title"] and result.job.title != draft["job_title"]) or
                (draft["company"] and result.job.company != draft["company"]) or
                (result.job.url or "") != draft["job_url"]):
                raise ValueError("Analysis does not belong to the saved thread inputs")
            db.execute("UPDATE career_threads SET analysis_json=?, analysis_fingerprint=?, invalidated=0, updated_at=? WHERE id=?",
                       (result.model_dump_json(), fingerprint(draft), self._now(), thread_id))

    def invalidate(self, workspace_id, thread_id):
        with self._connect() as db:
            self._thread(db, workspace_id, thread_id)
            db.execute("UPDATE career_threads SET invalidated=1 WHERE id=?", (thread_id,))

    def invalidate_description(self, text: str):
        """A corrected job interpretation invalidates every snapshot using that exact text."""
        with self._connect() as db:
            ids = [(row["id"],) for row in db.execute("SELECT id, draft_json FROM career_threads")
                   if json.loads(row["draft_json"]).get("job_text") == text]
            db.executemany("UPDATE career_threads SET invalidated=1 WHERE id=?", ids)

    def rename_thread(self, workspace_id, thread_id, name):
        with self._connect() as db:
            self._thread(db, workspace_id, thread_id)
            db.execute("UPDATE career_threads SET name=? WHERE id=?", (self._name(name), thread_id))

    def move_thread(self, workspace_id, thread_id, destination_id):
        """Reorganize a direction without duplicating or losing the job's conversation."""
        with self._connect() as db:
            self._thread(db, workspace_id, thread_id)
            self._workspace(db, destination_id)
            db.execute("UPDATE career_threads SET workspace_id=?, updated_at=? WHERE id=?", (destination_id, self._now(), thread_id))

    def delete_thread(self, workspace_id, thread_id):
        with self._connect() as db:
            self._thread(db, workspace_id, thread_id)
            db.execute("DELETE FROM career_threads WHERE id=?", (thread_id,))

    def delete_workspace(self, workspace_id):
        with self._connect() as db:
            self._workspace(db, workspace_id)
            db.execute("DELETE FROM career_workspaces WHERE id=?", (workspace_id,))

    def messages(self, workspace_id, thread_id):
        with self._connect() as db:
            self._thread(db, workspace_id, thread_id)
            return [dict(row) for row in db.execute("SELECT role, content, mode, created_at FROM career_messages WHERE thread_id=? ORDER BY id", (thread_id,))]

    def save_exchange(self, workspace_id, thread_id, question, answer, *, mode="local"):
        if not question.strip() or not answer.strip() or len(question) > 4_000 or len(answer) > 30_000:
            raise ValueError("Conversation turns need text within the 4,000/30,000 character limits")
        if mode not in {"local", "model"}:
            raise ValueError("Unknown conversation mode")
        with self._connect() as db:
            self._thread(db, workspace_id, thread_id)
            now = self._now()
            db.executemany("INSERT INTO career_messages (thread_id, role, content, mode, created_at) VALUES (?, ?, ?, ?, ?)",
                           [(thread_id, "user", question, mode, now), (thread_id, "assistant", answer, mode, now)])


def direction_summary(threads: list[dict]) -> dict:
    """Aggregate current snapshots by skills, never exact job titles or guessed families."""
    skills, jobs, nodes = {}, [], {}
    stale = 0
    for thread in threads:
        analysis = thread["analysis"]
        if not analysis:
            continue
        if thread["stale"]:
            stale += 1
            continue
        jobs.append({"thread": thread["name"], "title": analysis.job.title, "company": analysis.job.company,
                     "score": analysis.match.score, "id": thread["id"]})
        statuses = {item.job_evidence_id: item.status for item in analysis.match.requirements}
        for req in analysis.job.requirements:
            key = normalize_skill(req.skill)
            entry = skills.setdefault(key, {"skill": req.skill, "threads": set(), "required": set(), "preferred": set(), "missing": set(), "matched": set(), "uncertain": set()})
            entry["threads"].add(thread["id"])
            if req.importance == "uncertain":
                entry["uncertain"].add(thread["id"])
            else:
                entry["required" if req.required else "preferred"].add(thread["id"])
                status = statuses.get(req.evidence_id, "unknown")
                if status in {"matched", "missing"}:
                    entry[status].add(thread["id"])
        for node in analysis.skill_tree:
            nodes.setdefault(normalize_skill(node.skill), node)
    ordered = sorted(skills.values(), key=lambda e: (-len(e["required"] & e["missing"]), -len(e["missing"]), -len(e["threads"]), e["skill"]))
    gaps: list[SkillNode] = []
    for entry in ordered:
        if not entry["missing"]:
            continue
        node = nodes.get(normalize_skill(entry["skill"]))
        if node:
            gaps.append(node.model_copy(update={"reason": f"Missing evidence in {len(entry['missing'])} current job thread(s); required in {len(entry['required'] & entry['missing'])} of them.",
                                               "priority": "high" if entry["required"] & entry["missing"] else "medium"}))
    return {"jobs": jobs, "skills": [{k: sorted(v) if isinstance(v, set) else v for k, v in entry.items()} for entry in ordered],
            "gaps": gaps, "projects": build_project_plans(gaps), "stale_count": stale}
