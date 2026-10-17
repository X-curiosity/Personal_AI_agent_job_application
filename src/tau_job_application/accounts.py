"""Connected accounts: link external accounts and load profile preferences.

Only official, user-authorized paths exist:

- **GitHub**: public API lookup by username. Public profile facts only;
  languages remain unconfirmed signals, exactly like the existing enrichment.
- **LinkedIn**: OpenID Connect (Sign in with LinkedIn using OpenID Connect).
  Requires the user to register their own LinkedIn app and export client
  credentials. Identity claims only (name, email, picture): LinkedIn offers
  no API for CV data or job preferences to regular applications, and nothing
  is ever scraped or automated.
- **Gmail**: reply reading stays in `career_inbox` (bound conversations with
  per-thread consent and a user-provisioned token). The account row only
  records that Gmail replies were connected.

Tokens are never stored: GitHub needs none, the LinkedIn access token is
discarded after the identity call, and Gmail tokens live outside the app.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, Field, field_validator

from tau_job_application.company_catalog import _optional_https

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_SCOPE = "openid profile email"
GITHUB_API = "https://api.github.com"
MAX_RESPONSE_BYTES = 1_000_000

Provider = Literal["github", "linkedin", "gmail"]


class _NoRedirect(HTTPRedirectHandler):
    """Refuse redirects on credential-bearing calls.

    urllib's default redirect handler re-sends request headers — including a
    bearer token — to the redirect target. Refusing redirects guarantees a
    token can never leave the fixed, expected host.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = build_opener(_NoRedirect())


class ConnectedAccount(BaseModel):
    provider: Provider
    subject: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    avatar_url: str | None = None
    detail: str | None = Field(default=None, max_length=500)
    connected_at: str

    @field_validator("avatar_url")
    @classmethod
    def avatar_must_be_https(cls, value: object) -> str | None:
        return _optional_https(value)


def _https_json(url: str, *, expected_host: str, method: str = "GET", data: bytes | None = None,
                headers: dict[str, str] | None = None) -> dict:
    """Bounded JSON call to one fixed HTTPS host; redirects rejected."""

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise ValueError("Only the configured account endpoints can be called")
    request = Request(url, data=data, method=method,
                      headers={"Accept": "application/json", "User-Agent": "CoApplyGPT/0.2 (+local account link)", **(headers or {})})
    try:
        with _opener.open(request, timeout=15) as response:  # noqa: S310 - fixed allow-listed endpoints
            if urlparse(response.geturl()).hostname != expected_host:
                raise ValueError("Account endpoint redirected to an unexpected host")
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not reach {expected_host}: {exc}") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError("Account endpoint response exceeded the 1 MB safety limit")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{expected_host} returned invalid JSON") from exc
    if not isinstance(payload, (dict, list)):
        raise RuntimeError(f"{expected_host} returned an unexpected payload")
    return payload


def connect_github(username: str, *, fetcher: Callable[..., dict] = _https_json) -> ConnectedAccount:
    """Link a GitHub account from public data; no token is needed or kept."""

    cleaned = username.strip().strip("/").split("/")[-1][:100]
    if not cleaned or not all(char.isalnum() or char == "-" for char in cleaned):
        raise ValueError("Enter a valid GitHub username (letters, digits, hyphens)")
    profile = fetcher(f"{GITHUB_API}/users/{cleaned}", expected_host="api.github.com")
    if "login" not in profile:
        raise RuntimeError("GitHub did not return that user; check the username")
    repos = fetcher(f"{GITHUB_API}/users/{cleaned}/repos?per_page=100&sort=updated", expected_host="api.github.com")
    languages: list[str] = []
    if isinstance(repos, list):
        languages = sorted({str(repo["language"]) for repo in repos if isinstance(repo, dict) and repo.get("language")})
    return ConnectedAccount(
        provider="github", subject=str(profile["login"]),
        display_name=str(profile.get("name") or profile["login"])[:200],
        avatar_url=_optional_https(profile.get("avatar_url")),
        detail=(f"{profile.get('public_repos', 0)} public repositories"
                + (f" · languages: {', '.join(languages[:8])}" if languages else "")
                + " (language signals, not proof of proficiency)")[:500],
        connected_at=datetime.now(UTC).isoformat(),
    )


def linkedin_authorization_url(*, client_id: str, redirect_uri: str, state: str,
                               nonce: str | None = None, code_challenge: str | None = None) -> str:
    """Build the official authorization URL; state is generated per attempt.

    ``nonce`` binds the returned OIDC identity to this attempt and
    ``code_challenge`` (S256) protects the authorization code from
    interception on the localhost redirect.
    """

    if not client_id.strip() or len(client_id) > 100:
        raise ValueError("LinkedIn client id looks invalid")
    if not _optional_https(redirect_uri) and not redirect_uri.startswith("http://127.0.0.1") and not redirect_uri.startswith("http://localhost"):
        raise ValueError("Redirect URI must be HTTPS (or localhost for local development)")
    params = {
        'response_type': 'code', 'client_id': client_id, 'redirect_uri': redirect_uri,
        'state': state, 'scope': LINKEDIN_SCOPE,
    }
    if nonce:
        params['nonce'] = nonce
    if code_challenge:
        params['code_challenge'] = code_challenge
        params['code_challenge_method'] = 'S256'
    return f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"


def new_oauth_state() -> str:
    return secrets.token_urlsafe(24)


def new_pkce_verifier() -> str:
    """High-entropy PKCE verifier within the RFC 7636 length bounds."""

    return secrets.token_urlsafe(64)[:128]


def pkce_challenge(verifier: str) -> str:
    """S256 code challenge for a PKCE verifier."""

    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _id_token_claims(id_token: str) -> dict:
    """Decode id_token claims to bind the OIDC nonce.

    The token arrives over the authenticated TLS back-channel from LinkedIn's
    fixed token endpoint, and the identity claims used by this app are read
    independently from the userinfo endpoint. The nonce comparison here binds
    that back-channel identity to the browser attempt that requested it.
    """

    parts = id_token.split(".")
    if len(parts) < 2:
        return {}
    padding = "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
    except (ValueError, json.JSONDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def complete_linkedin_signin(
    *, code: str, client_id: str, client_secret: str, redirect_uri: str,
    code_verifier: str | None = None, nonce: str | None = None,
    poster: Callable[..., dict] = _https_json, fetcher: Callable[..., dict] = _https_json,
) -> ConnectedAccount:
    """Exchange the authorization code, read identity claims, discard the token."""

    if not code.strip() or len(code) > 2_000:
        raise ValueError("The LinkedIn authorization code looks invalid")
    form = {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect_uri, "client_id": client_id, "client_secret": client_secret,
    }
    if code_verifier:
        form["code_verifier"] = code_verifier
    token = poster(
        LINKEDIN_TOKEN_URL, expected_host="www.linkedin.com", method="POST",
        data=urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    access_token = str(token.get("access_token") or "")
    if not access_token:
        raise RuntimeError("LinkedIn did not return an access token; check the app credentials and redirect URI")
    if nonce and token.get("id_token"):
        claims = _id_token_claims(str(token["id_token"]))
        if claims.get("nonce") != nonce:
            raise RuntimeError("LinkedIn identity did not match this sign-in attempt; start again")
    claims = fetcher(LINKEDIN_USERINFO_URL, expected_host="api.linkedin.com",
                     headers={"Authorization": f"Bearer {access_token}"})
    subject = str(claims.get("sub") or "")
    if not subject:
        raise RuntimeError("LinkedIn did not return identity claims")
    return ConnectedAccount(
        provider="linkedin", subject=subject,
        display_name=str(claims.get("name") or "")[:200] or None,
        email=str(claims.get("email") or "")[:320] or None,
        avatar_url=_optional_https(claims.get("picture")),
        detail="Identity verified with LinkedIn OpenID Connect. LinkedIn does not provide CV or job-preference APIs; your preferences stay the ones you set here.",
        connected_at=datetime.now(UTC).isoformat(),
    )


class ConnectedAccountStore:
    """Local account links; one row per provider, removable at any time."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS connected_accounts (
                    provider TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    connected_at TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def save(self, account: ConnectedAccount) -> None:
        record = ConnectedAccount.model_validate(account)
        with self._connect() as db:
            db.execute(
                """INSERT INTO connected_accounts(provider,subject,payload_json,connected_at) VALUES(?,?,?,?)
                   ON CONFLICT(provider) DO UPDATE SET
                   subject=excluded.subject,payload_json=excluded.payload_json,connected_at=excluded.connected_at""",
                (record.provider, record.subject, record.model_dump_json(), record.connected_at),
            )

    def get(self, provider: Provider) -> ConnectedAccount | None:
        with self._connect() as db:
            row = db.execute("SELECT payload_json FROM connected_accounts WHERE provider=?", (provider,)).fetchone()
        return ConnectedAccount.model_validate_json(row["payload_json"]) if row else None

    def all(self) -> list[ConnectedAccount]:
        with self._connect() as db:
            rows = db.execute("SELECT payload_json FROM connected_accounts ORDER BY provider").fetchall()
        return [ConnectedAccount.model_validate_json(row["payload_json"]) for row in rows]

    def remove(self, provider: Provider) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM connected_accounts WHERE provider=?", (provider,))
        return cursor.rowcount > 0
