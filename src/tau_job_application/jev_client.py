"""Optional Jev decision-model client for ambiguous skill pairs.

Jev (TypeSafe AI) is a *decision* model: you send state and it returns a typed
judgment instead of chat text. It is used here for exactly one narrow job —
settling skill pairs the local decision model reports as ambiguous.

Design rules enforced in this module:

- **Opt-in only.** Nothing is called unless ``JEV_API_KEY`` is exported by the
  user *and* the caller passes an explicit opt-in.
- **Advisory only.** The result adjusts an advisory refinement; canonical
  evidence scores never depend on this module.
- **No candidate PII.** Only two skill labels are sent, never CV text, job
  adverts, account data, or replies.
- **Fixed host, no redirects, bounded read, short timeout.** Same discipline as
  :mod:`tau_job_application.accounts`.
- **Deterministic fallback.** Any failure returns ``None`` and the caller keeps
  the local verdict.

The exact request/response schema is vendor-specific and deliberately
configurable: set ``JEV_API_URL`` from the official documentation (see
``docs/JEV_NOTES.md``). Without that variable the client refuses to run rather
than guessing an endpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 100_000
REQUEST_TIMEOUT_SECONDS = 12
CACHE_TTL = timedelta(days=30)
DEFAULT_QUESTION = "Do these two labels describe the same professional skill?"


class _NoRedirect(HTTPRedirectHandler):
    """Refuse redirects so an API key can never be forwarded to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = build_opener(_NoRedirect())


def jev_api_url() -> str | None:
    """Return the configured endpoint, or ``None`` when the experiment is off."""

    url = os.environ.get("JEV_API_URL", "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return url


def jev_available() -> bool:
    """True only when both an API key and an explicit endpoint are configured."""

    return bool(os.environ.get("JEV_API_KEY", "").strip()) and jev_api_url() is not None


def _extract_probability(payload: object) -> float | None:
    """Read a yes/no probability from the vendor response, tolerantly.

    The published schema is not stable enough to hard-code one key, so the
    common shapes are accepted and anything else is treated as "no answer"
    (the caller then keeps the local verdict).
    """

    if isinstance(payload, bool):
        return 1.0 if payload else 0.0
    if isinstance(payload, (int, float)):
        return float(payload)
    if isinstance(payload, dict):
        for key in ("probability", "yes_probability", "p_yes", "confidence", "score", "value"):
            value = payload.get(key)
            if isinstance(value, (int, float, bool)):
                return float(value)
        for key in ("output", "decision", "result", "data", "answer"):
            if key in payload:
                found = _extract_probability(payload[key])
                if found is not None:
                    return found
        # A labelled choice such as {"choice": "yes"} is a decision too.
        for key in ("choice", "label", "verdict"):
            value = str(payload.get(key, "")).strip().casefold()
            if value in {"yes", "true", "same", "match"}:
                return 1.0
            if value in {"no", "false", "different", "no_match"}:
                return 0.0
    return None


def _cache(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jev_skill_decisions (
            cache_key TEXT PRIMARY KEY,
            probability REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    return connection


def _cache_key(left: str, right: str, question: str) -> str:
    a, b = sorted((left.strip().casefold(), right.strip().casefold()))
    return hashlib.sha256(f"{question}\x00{a}\x00{b}".encode("utf-8")).hexdigest()


def _cached(connection: sqlite3.Connection, key: str, *, now: datetime) -> float | None:
    row = connection.execute(
        "SELECT probability, created_at FROM jev_skill_decisions WHERE cache_key=?", (key,)
    ).fetchone()
    if row is None:
        return None
    try:
        created = datetime.fromisoformat(row["created_at"])
    except ValueError:
        return None
    return float(row["probability"]) if now - created <= CACHE_TTL else None


def _store(connection: sqlite3.Connection, key: str, probability: float, *, now: datetime) -> None:
    connection.execute(
        """INSERT INTO jev_skill_decisions(cache_key, probability, created_at) VALUES(?,?,?)
           ON CONFLICT(cache_key) DO UPDATE SET probability=excluded.probability, created_at=excluded.created_at""",
        (key, probability, now.isoformat()),
    )


def jev_skill_probability(
    left: str,
    right: str,
    *,
    database_path: Path | None = None,
    question: str = DEFAULT_QUESTION,
    poster: Callable[..., object] | None = None,
    now: datetime | None = None,
) -> float | None:
    """Return P(same skill) from Jev, or ``None`` (caller keeps local verdict).

    ``poster`` is injected for tests; the default performs one bounded HTTPS
    POST. Results are cached for :data:`CACHE_TTL` so a repeated role page load
    never re-pays for the same pair.
    """

    if not jev_available():
        return None
    moment = now or datetime.now(UTC)
    connection = None
    key = _cache_key(left, right, question)
    if database_path is not None:
        connection = _cache(path=database_path)
        cached = _cached(connection, key, now=moment)
        if cached is not None:
            connection.close()
            return cached

    try:
        answer = (poster or _post_decision)(left=left, right=right, question=question)
    except Exception:
        answer = None
    probability: float | None
    try:
        probability = None if answer is None else max(0.0, min(1.0, float(answer)))
    except (TypeError, ValueError):
        # A malformed answer is treated exactly like no answer.
        probability = None
    finally:
        if connection is not None:
            if probability is not None:
                _store(connection, key, probability, now=moment)
                connection.commit()
            connection.close()
    return probability


def _post_decision(*, left: str, right: str, question: str) -> float | None:
    """One bounded, no-redirect POST to the user-configured Jev endpoint."""

    url = jev_api_url()
    api_key = os.environ.get("JEV_API_KEY", "").strip()
    if url is None or not api_key:
        return None
    # Only the two labels and a fixed question leave the machine: no CV text,
    # no advert content, no identifiers.
    body = json.dumps({
        "primitive": "yes_no",
        "question": question,
        "context": {"left_skill": left[:120], "right_skill": right[:120]},
    }).encode("utf-8")
    request = Request(
        url, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CoApplyGPT/0.2 (+optional skill-decision)",
        },
    )
    with _opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 - user-configured HTTPS endpoint
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        return None
    try:
        return _extract_probability(json.loads(payload.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def jev_resolver(database_path: Path | None = None) -> Callable[[str, str], float | None]:
    """Build the resolver passed to :func:`skill_decision.decide_skill_match`."""

    def resolve(left: str, right: str) -> float | None:
        return jev_skill_probability(left, right, database_path=database_path)

    return resolve
