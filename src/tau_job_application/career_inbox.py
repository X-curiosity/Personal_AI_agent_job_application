"""Bounded read-only connectors and conservative application-status proposals."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from tau_job_application.application_tracker import ApplicationStage, ApplicationProgress


class Reply(BaseModel):
    source: str = Field(pattern=r"^(gmail|slack|manual)$")
    message_id: str = Field(min_length=1, max_length=200)
    conversation: str = Field(min_length=1, max_length=200)
    sender: str = Field(max_length=320)
    text: str = Field(min_length=1, max_length=12_000)
    received_at: datetime


def classify_reply(text):
    """Literal outcome cues only; ambiguous/negated/conflicting text needs review."""
    text = " ".join(text.casefold().split())
    if any(cue in text for cue in ("not an offer", "no offer", "not a rejection", "not invite", "cannot offer", "unable to offer")):
        return None
    if re.search(r"\b(?:not|never|won't|cannot|can't|unable to)\b.{0,25}\b(?:offer|invite|interview)\b", text):
        return None
    patterns = {
        ApplicationStage.CLOSED: ("will not be moving forward", "not been selected", "application was unsuccessful", "decided not to proceed"),
        ApplicationStage.INTERVIEW: ("invite you to interview", "invite you for an interview", "schedule your interview", "invitation to interview"),
        ApplicationStage.OFFER: ("pleased to offer you", "offer you the position", "formal offer of employment"),
        ApplicationStage.CONTACTED: ("received your application", "thank you for applying"),
    }
    found = [stage for stage, cues in patterns.items() if any(cue in text for cue in cues)]
    return found[0] if len(found) == 1 else None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get(url, token):
    # Only callers below construct fixed official service URLs. No user URL fetch.
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect).open(request, timeout=15) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("Connector response exceeded the size limit")
        return json.loads(data)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        # Never surface a token, response body, or private message in errors.
        raise ValueError("Connector unavailable. Check access, expiry, permissions, and rate limits.") from None


def read_gmail(token: str, conversation: str) -> list[Reply]:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,200}", conversation):
        raise ValueError("Provide the Gmail API conversation ID")
    result = _get("https://gmail.googleapis.com/gmail/v1/users/me/threads/" + quote(conversation, safe="") + "?format=metadata", token)
    replies = []
    for message in result.get("messages", [])[-10:]:
        if message.get("threadId") != conversation or {"SENT", "DRAFT", "SPAM", "TRASH"}.intersection(message.get("labelIds", [])):
            continue
        headers = {header["name"].casefold(): header["value"] for header in message.get("payload", {}).get("headers", [])}
        replies.append(Reply(source="gmail", message_id=message["id"], conversation=conversation,
                             sender=parseaddr(headers.get("from", ""))[1].casefold(),
                             text=(headers.get("subject", "") + "\n" + message.get("snippet", ""))[:12_000],
                             received_at=datetime.fromtimestamp(int(message["internalDate"]) / 1000, UTC)))
    return replies


def read_slack(token: str, channel: str) -> list[Reply]:
    if not re.fullmatch(r"[CDG][A-Z0-9]{6,30}", channel):
        raise ValueError("Provide a Slack conversation ID")
    result = _get("https://slack.com/api/conversations.history?" + urlencode({"channel": channel, "limit": 15}), token)
    if not result.get("ok"):
        raise ValueError("Slack access failed. Check channel access and history scope.")
    return [Reply(source="slack", message_id=item["ts"], conversation=channel,
                  sender=item.get("user", ""), text=item["text"][:12_000],
                  received_at=datetime.fromtimestamp(float(item["ts"]), UTC))
            for item in result.get("messages", [])[:15] if item.get("text") and not item.get("subtype")]


class InboxStore:
    def __init__(self, tracker):
        self.tracker = tracker
        with tracker._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS career_reply_bindings (
                    application_id TEXT PRIMARY KEY REFERENCES tracked_applications(id) ON DELETE CASCADE,
                    source TEXT NOT NULL, conversation TEXT NOT NULL, sender TEXT NOT NULL,
                    auto_update INTEGER NOT NULL DEFAULT 0, bound_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS career_reply_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id TEXT NOT NULL REFERENCES tracked_applications(id) ON DELETE CASCADE,
                    source TEXT NOT NULL, message_id TEXT NOT NULL, text TEXT NOT NULL,
                    proposed_stage TEXT, state TEXT NOT NULL, received_at TEXT NOT NULL,
                    UNIQUE(application_id, source, message_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS career_reply_binding_identity
                    ON career_reply_bindings(source, conversation, sender);
            """)

    def binding(self, track, app):
        self.tracker.get(track, app)
        with self.tracker._connect() as db:
            row = db.execute("SELECT * FROM career_reply_bindings WHERE application_id=?", (app,)).fetchone()
        return dict(row) if row else None

    def bind(self, track, app, *, source, conversation, sender, auto_update=False):
        self.tracker.get(track, app)
        if source not in {"gmail", "slack"} or not conversation.strip() or not sender.strip() or max(len(conversation), len(sender)) > 320:
            raise ValueError("Choose a source, conversation, and exact expected sender")
        with self.tracker._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM career_reply_bindings WHERE source=? AND conversation=? AND sender=? AND application_id<>?",
                          (source, conversation.strip(), sender.strip().casefold(), app)).fetchone():
                raise ValueError("That conversation and sender are already bound to another application. Use manual review if it covers several roles.")
            db.execute("INSERT INTO career_reply_bindings VALUES (?,?,?,?,?,?) ON CONFLICT(application_id) DO UPDATE SET source=excluded.source, conversation=excluded.conversation, sender=excluded.sender, auto_update=excluded.auto_update, bound_at=excluded.bound_at",
                       (app, source, conversation.strip(), sender.strip().casefold(), int(auto_update and source == "gmail"), datetime.now(UTC).isoformat()))

    def ingest(self, track, app, reply: Reply, *, trusted_connector=False):
        reply = Reply.model_validate(reply.model_dump())
        if reply.received_at.tzinfo is None:
            raise ValueError("Reply timestamps must include their timezone")
        binding = self.binding(track, app)
        if not binding or (reply.source, reply.conversation, reply.sender.casefold()) != (binding["source"], binding["conversation"], binding["sender"]):
            return "unmatched"
        stage = classify_reply(reply.text)
        record = self.tracker.get(track, app)
        # Old mail is retained for review, never replayed as a current outcome.
        auto = bool(trusted_connector and reply.source == "gmail" and binding["auto_update"] and stage
                    and reply.received_at >= datetime.fromisoformat(binding["bound_at"])
                    and reply.received_at <= datetime.now(UTC) + timedelta(minutes=5)
                    and record.progress.stage in {ApplicationStage.APPLIED, ApplicationStage.CONTACTED, ApplicationStage.INTERVIEW}
                    and (stage == ApplicationStage.CLOSED or list(ApplicationStage).index(stage) > list(ApplicationStage).index(record.progress.stage)))
        with self.tracker._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.tracker._owned_row(db, track, app)
            cursor = db.execute("INSERT OR IGNORE INTO career_reply_events (application_id,source,message_id,text,proposed_stage,state,received_at) VALUES (?,?,?,?,?,?,?)",
                                (app, reply.source, reply.message_id, reply.text, stage.value if stage else None, "review", reply.received_at.isoformat()))
            if not cursor.rowcount:
                return "duplicate"
            event_id = cursor.lastrowid
        if auto:
            self.apply(track, app, event_id, expected_updated_at=record.updated_at)
            return "updated"
        return "review"

    def events(self, track, app):
        self.tracker.get(track, app)
        with self.tracker._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM career_reply_events WHERE application_id=? ORDER BY received_at DESC,id DESC LIMIT 30", (app,))]

    def apply(self, track, app, event_id, *, expected_updated_at=None):
        with self.tracker._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self.tracker._decode(self.tracker._owned_row(db, track, app))
            event = db.execute("SELECT * FROM career_reply_events WHERE id=? AND application_id=? AND state='review'", (event_id, app)).fetchone()
            if not event or not event["proposed_stage"]:
                raise ValueError("No unambiguous status proposal is available")
            if expected_updated_at and record.updated_at != expected_updated_at:
                raise ValueError("Application changed; review this reply before updating")
            stage = ApplicationStage(event["proposed_stage"])
            progress = ApplicationProgress.model_validate({**record.progress.model_dump(), "stage": stage,
                       "stage_on": datetime.fromisoformat(event["received_at"]).astimezone(ZoneInfo("Europe/Zurich")).date(),
                       "closed_reason": "rejected" if stage is ApplicationStage.CLOSED else ""})
            now = self.tracker._now()
            db.execute("UPDATE tracked_applications SET progress_json=?, updated_at=? WHERE id=?", (progress.model_dump_json(), now, app))
            self.tracker._event(db, app, "reply_status_update", now, ("stage", "stage_on", "closed_reason"), progress)
            db.execute("UPDATE career_reply_events SET state='applied' WHERE id=?", (event_id,))
