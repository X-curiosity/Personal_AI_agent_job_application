"""Registered employer job sources, ATS auto-detection, and ingestion.

This is the scalable counterpart to the small hand-vetted board list: a
database of company → official careers ATS, plus bounded, SSRF-safe detection
of which ATS a company uses, and a runner that refreshes openings from every
enabled source. Detection only reads public pages; ingestion only calls the
documented public board APIs in ``sources.fetch_public_board_openings``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from ipaddress import ip_address
import json
from pathlib import Path
import re
import socket
import sqlite3
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from tau_job_application.sources import fetch_public_board_openings

USER_AGENT = "hired-job-sources/0.1 (public career-page detection)"
MAX_DETECT_BYTES = 2_000_000
SUPPORTED_SOURCES = ("Greenhouse", "Lever", "Ashby", "Workable", "Recruitee", "Feed")

# ATS board URL patterns. The captured group is the board identifier.
_ATS_PATTERNS = (
    ("Greenhouse", re.compile(r"https?://boards\.greenhouse\.io/([A-Za-z0-9-]+)")),
    ("Lever", re.compile(r"https?://jobs\.lever\.co/([A-Za-z0-9-]+)")),
    ("Ashby", re.compile(r"https?://jobs\.ashbyhq\.com/([A-Za-z0-9.-]+)")),
    ("Workable", re.compile(r"https?://(?:apply\.)?workable\.com/jobs/([A-Za-z0-9-]+)")),
    ("Recruitee", re.compile(r"https?://([A-Za-z0-9-]+)\.recruitee\.com")),
)

_CAREERS_PATHS = ("/careers", "/jobs", "/company/careers")


def _project_root() -> Path:
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / "pyproject.toml").is_file() or (directory / "fixtures").is_dir():
            return directory
    return Path.cwd()


DEFAULT_DATABASE = _project_root() / ".job_assistant" / "assistant.sqlite"


@dataclass
class JobSource:
    company: str
    source: str
    board_identifier: str
    board_url: str
    company_type: str = "unknown"
    region_hint: str = ""
    website: str = ""
    enabled: bool = True
    detected_from: str = ""
    last_success: str | None = None
    last_error: str | None = None
    id: int | None = None


def _assert_public_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Only public HTTPS pages can be fetched")
    for record in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        address = ip_address(record[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValueError("Page resolved to a non-public address")


def fetch_public_text(url: str, *, max_bytes: int = MAX_DETECT_BYTES, timeout: float = 10) -> str:
    _assert_public_https(url)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - public https asserted above
        final = urlparse(response.geturl())
        if final.scheme != "https" or not final.hostname:
            raise ValueError("Page redirected off HTTPS")
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"Response exceeded {max_bytes} bytes")
    for encoding in ("utf-8", "latin-1"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", "replace")


def detect_ats_from_text(text: str) -> list[dict[str, str]]:
    """Return the ATS boards referenced in an HTML page, deduplicated."""
    found: dict[tuple[str, str], dict[str, str]] = {}
    for source, pattern in _ATS_PATTERNS:
        for match in pattern.finditer(text):
            identifier = unescape(match.group(1)).strip()
            key = (source, identifier.casefold())
            if key not in found:
                found[key] = {"source": source, "board_identifier": identifier, "board_url": match.group(0)}
    return list(found.values())


def detect_company_ats(website: str, *, careers_url: str = "", fetcher=fetch_public_text) -> list[dict[str, str]]:
    """Detect a company's ATS board(s) from its website and careers pages.

    Bounded and best-effort: a small set of well-known careers paths is tried;
    failures are ignored rather than retried, so the caller can register what
    was found without stalling on unreachable sites.
    """
    website = website.rstrip("/")
    candidates = []
    if careers_url:
        candidates.append(careers_url)
    if website.startswith("https://"):
        candidates.append(website)
        candidates.extend(urljoin(website, path) for path in _CAREERS_PATHS)
    results: dict[tuple[str, str], dict[str, str]] = {}
    for url in dict.fromkeys(candidates):
        try:
            for found in detect_ats_from_text(fetcher(url)):
                results[(found["source"], found["board_identifier"].casefold())] = found
        except Exception:
            continue
    return list(results.values())


def _feed_entry(title, url, description, location, published):
    return {
        "title": (title or "").strip()[:300],
        "url": url.strip(),
        "description": (description or "").strip()[:4000],
        "location": (location or "").strip()[:300],
        "source_id": re.sub(r"[^a-z0-9]", "", str(url or title or "").casefold())[:40] or "feed-item",
        "source": "Feed",
        "source_timestamp": published or None,
        "source_timestamp_kind": "published" if published else None,
    }


def _xml_text(node, tag):
    child = node.find("{*}" + tag) if node is not None else None
    return (child.text or "").strip() if child is not None and child.text else ""


def _parse_feed(text: str, default_country: str) -> list[dict]:
    stripped = text.lstrip()
    openings: list[dict] = []
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        items = data.get("items", []) if isinstance(data, dict) else data
        for item in items[:200] if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name") or ""
            url = item.get("url") or item.get("link") or ""
            if not str(url).startswith("https://"):
                continue
            openings.append(_feed_entry(title, url, item.get("content_text") or item.get("summary") or item.get("description") or "",
                                        item.get("location") or item.get("city") or default_country, item.get("date_published")))
        return openings
    root = ElementTree.fromstring(stripped)
    for item in root.iter():
        tag = item.tag.rsplit("}", 1)[-1].casefold()
        if tag not in {"item", "entry"}:
            continue
        title = _xml_text(item, "title")
        link = _xml_text(item, "link")
        if not link:  # Atom link is an attribute
            link_node = item.find("{*}link")
            link = (link_node.get("href") or "") if link_node is not None else ""
        if not str(link).startswith("https://"):
            continue
        openings.append(_feed_entry(title, link, _xml_text(item, "description") or _xml_text(item, "summary") or _xml_text(item, "content"),
                                    _xml_text(item, "location") or default_country, _xml_text(item, "pubDate") or _xml_text(item, "published")))
    return openings


def fetch_feed_openings(feed_url: str, *, default_country: str = "") -> list[dict]:
    """Ingest openings from a public RSS/Atom/JSON job feed (regional boards).

    Bounded and SSRF-safe; entries without a location fall back to the
    caller-supplied country so the export can still place them at country level.
    """
    text = fetch_public_text(feed_url, max_bytes=5_000_000)
    openings = _parse_feed(text, default_country)
    if not openings:
        raise ValueError("Feed contained no parseable job entries")
    return openings


class JobSourceStore:
    def __init__(self, path: Path | str = DEFAULT_DATABASE) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS job_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL,
                    source TEXT NOT NULL,
                    board_identifier TEXT NOT NULL,
                    board_url TEXT NOT NULL,
                    company_type TEXT NOT NULL DEFAULT 'unknown',
                    region_hint TEXT NOT NULL DEFAULT '',
                    website TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    detected_from TEXT NOT NULL DEFAULT '',
                    last_success TEXT,
                    last_error TEXT,
                    UNIQUE(source, board_identifier)
                );
            """)

    def register(self, source: JobSource) -> int:
        """Insert or update one source; returns its id."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO job_sources (company, source, board_identifier, board_url, company_type, region_hint, website, enabled, detected_from) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source, board_identifier) DO UPDATE SET company=excluded.company, board_url=excluded.board_url, "
                "company_type=excluded.company_type, region_hint=excluded.region_hint, website=excluded.website, enabled=excluded.enabled",
                (source.company, source.source, source.board_identifier, source.board_url, source.company_type,
                 source.region_hint, source.website, int(source.enabled), source.detected_from),
            )
            row = connection.execute(
                "SELECT id FROM job_sources WHERE source = ? AND board_identifier = ?",
                (source.source, source.board_identifier),
            ).fetchone()
            return int(row["id"])

    def list(self, *, enabled_only: bool = False) -> list[dict]:
        query = "SELECT id, company, source, board_identifier, board_url, company_type, region_hint, website, enabled, detected_from, last_success, last_error FROM job_sources"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY company, source"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query).fetchall()]

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM job_sources").fetchone()[0])

    def set_enabled(self, source_id: int, enabled: bool) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE job_sources SET enabled = ? WHERE id = ?", (int(enabled), source_id))

    def delete(self, source_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM job_sources WHERE id = ?", (source_id,))

    def mark_success(self, source_id: int) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE job_sources SET last_success = ?, last_error = NULL WHERE id = ?", (self._now(), source_id))

    def mark_error(self, source_id: int, error: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE job_sources SET last_error = ? WHERE id = ?", (error[:400], source_id))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()


def ingest_sources(store: JobSourceStore, openings_fetcher=fetch_public_board_openings) -> list[dict]:
    """Refresh openings from every enabled source and record sync status.

    Returns raw, normalized openings (each already carries the company name).
    Failed sources are marked and skipped; their prior jobs are not fabricated.
    """
    openings: list[dict] = []
    for source in store.list(enabled_only=True):
        try:
            rows = openings_fetcher(source["source"], source["board_identifier"], company=source["company"])
            for row in rows:
                row["company"] = source["company"]
            openings.extend(rows)
            store.mark_success(source["id"])
        except Exception as exc:
            store.mark_error(source["id"], str(exc))
    return openings
