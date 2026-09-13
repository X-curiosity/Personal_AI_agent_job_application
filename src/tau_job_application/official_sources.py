"""User-initiated connectors for official APIs and user-provided data exports.

These connectors deliberately do not perform profile search, scraping, messaging,
or application submission. Access tokens are supplied per action or through the
local environment; they are never written to the local SQLite history.
"""

from __future__ import annotations

import csv
from io import StringIO
import json
import re
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from tau_job_application.models import ContactLead, JobPosting
from tau_job_application.parsing import parse_job_text


class AuthorizedIdentity(BaseModel):
    platform: str
    subject: str
    name: str | None = None
    email: str | None = None
    profile_url: str | None = None
    raw_fields: dict[str, str] = Field(default_factory=dict)


class OpportunitySignal(BaseModel):
    platform: str
    id: str
    text: str
    url: str | None = None
    author_id: str | None = None
    created_at: str | None = None
    metrics: dict[str, int] = Field(default_factory=dict)


def fetch_linkedin_authorized_identity(access_token: str) -> AuthorizedIdentity:
    """Fetch only the connected user's OIDC identity from LinkedIn's official API.

    LinkedIn's official APIs do not provide a general profile-search API for this
    application. This function is an account/consent check, not a people finder.
    """
    payload = _request_json("https://api.linkedin.com/v2/userinfo", access_token)
    return AuthorizedIdentity(
        platform="linkedin",
        subject=str(payload.get("sub", "")),
        name=payload.get("name"),
        email=payload.get("email"),
        profile_url=payload.get("profile"),
        raw_fields={key: str(value) for key, value in payload.items() if key in {"given_name", "family_name", "email_verified"}},
    )


def fetch_x_recent_posts(query: str, bearer_token: str, max_results: int = 10) -> list[OpportunitySignal]:
    """Read recent public X posts through the official X API v2 search endpoint."""
    query = query.strip()
    if not query:
        raise ValueError("Enter an X API search query")
    maximum = max(10, min(int(max_results), 100))
    params = urlencode({"query": query, "max_results": maximum, "tweet.fields": "created_at,public_metrics,author_id"})
    payload = _request_json(f"https://api.x.com/2/tweets/search/recent?{params}", bearer_token)
    return [
        OpportunitySignal(
            platform="x", id=str(post["id"]), text=str(post.get("text", "")),
            url=f"https://x.com/i/web/status/{post['id']}", author_id=post.get("author_id"),
            created_at=post.get("created_at"), metrics={key: int(value) for key, value in post.get("public_metrics", {}).items() if isinstance(value, int)},
        )
        for post in payload.get("data", [])
    ]


def fetch_smartrecruiters_postings(company_identifier: str, smart_token: str) -> list[JobPosting]:
    """Fetch published roles using SmartRecruiters' official Posting API.

    The company must provide an API token with the required Posting API access.
    This is a user-initiated read only; the token is not persisted.
    """
    identifier = company_identifier.strip()
    if not identifier.replace("-", "").replace("_", "").isalnum():
        raise ValueError("SmartRecruiters company identifier contains unsupported characters")
    payload = _request_json(
        f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings",
        smart_token,
        token_header="X-SmartToken",
    )
    postings = payload.get("content", payload.get("postings", []))
    jobs = []
    for posting in postings:
        title = posting.get("name") or posting.get("jobAd", {}).get("title")
        description = posting.get("jobAd", {}).get("sections", {}).get("jobDescription", "") or posting.get("description", "")
        if not title:
            continue
        try:
            jobs.append(parse_job_text(str(description), title=str(title), company=identifier, url=posting.get("ref") or posting.get("applyUrl")))
        except ValueError:
            continue
    return jobs


def import_contact_export(content: bytes, filename: str) -> list[ContactLead]:
    """Import a user-provided CSV/JSON export without contacting anyone.

    Supported columns/keys: name, role/title, profile_url/linkedin_url/x_url,
    public_email/email, evidence/source. Any imported record remains user-reviewed.
    """
    rows = _rows_from_export(content, filename)
    leads = []
    for row in rows:
        name = _value(row, "name", "full_name")
        role = _value(row, "role", "title", "headline")
        if not name or not role:
            continue
        profile_url = _value(row, "profile_url", "url", "linkedin_url", "x_url")
        email = _value(row, "public_email", "email")
        leads.append(ContactLead(
            name=name, role=role, profile_url=profile_url if _web_url(profile_url) else None,
            public_email=email if _email(email) else None,
            evidence=_value(row, "evidence", "source", "source_url") or "User-provided import; verify publication and relevance before outreach.",
            confidence="needs_review",
        ))
    return leads


def import_job_export(content: bytes, filename: str) -> list[JobPosting]:
    """Import user-provided job data from a CSV/JSON export into the evidence model."""
    rows = _rows_from_export(content, filename)
    jobs = []
    for row in rows:
        title, company = _value(row, "title", "job_title"), _value(row, "company", "company_name")
        description = _value(row, "description", "job_description", "content")
        required, preferred = _value(row, "required_skills", "required skills"), _value(row, "preferred_skills", "preferred skills")
        if not title or not company:
            continue
        text = description or ""
        if required:
            text += f"\nRequired skills: {required}"
        if preferred:
            text += f"\nPreferred skills: {preferred}"
        try:
            jobs.append(parse_job_text(text, title=title, company=company, url=_value(row, "url", "job_url") or None))
        except ValueError:
            continue
    return jobs


def _rows_from_export(content: bytes, filename: str) -> list[dict[str, object]]:
    if len(content) > 5_000_000:
        raise ValueError("Import is limited to 5 MB")
    text = content.decode("utf-8-sig")
    if filename.casefold().endswith(".json"):
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = parsed.get("data", parsed.get("items", []))
        if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
            raise ValueError("JSON import must be a list of objects or contain a data/items list")
        return parsed[:500]
    if filename.casefold().endswith(".csv"):
        return list(csv.DictReader(StringIO(text)))[:500]
    raise ValueError("Upload a .csv or .json export")


def _request_json(url: str, token: str, *, token_header: str = "Authorization") -> dict:
    if not token.strip():
        raise ValueError("Provide an official API token for this one-time request")
    credential = f"Bearer {token.strip()}" if token_header == "Authorization" else token.strip()
    request = Request(url, headers={token_header: credential, "Accept": "application/json", "User-Agent": "job-readiness-assistant/0.2"})
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed official endpoints only
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Official API request failed: {exc}") from exc


def _value(row: dict[str, object], *names: str) -> str:
    normalized = {str(key).casefold().strip(): str(value).strip() for key, value in row.items() if value is not None}
    for name in names:
        if value := normalized.get(name.casefold()):
            return value
    return ""


def _web_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


def _email(value: str) -> bool:
    return bool(re.fullmatch(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value))
