"""Bounded YC company directory snapshot with vclense-style filters.

The directory mirrors the public yc-oss dataset (an unofficial daily mirror of
the YC company directory). A snapshot is fetched only on an explicit refresh
action from the single fixed HTTPS endpoint; filters run locally and
deterministically against the stored snapshot. A directory entry is never
proof of an open vacancy: the ``is_hiring`` flag is a directory-level signal,
not a per-role guarantee.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field, field_validator

from tau_job_application.company_catalog import _fetch, _optional_https

YC_ALL_URL = "https://yc-oss.github.io/api/companies/all.json"
YC_HOST = "yc-oss.github.io"
YC_STATUSES = ("Active", "Acquired", "Public", "Inactive")
MAX_DIRECTORY_RECORDS = 10_000
MAX_FILTER_LIMIT = 500
# The full directory JSON is ~11 MB today; bound it explicitly.
MAX_DIRECTORY_BYTES = 24_000_000


def _clean_text(value: object, *, maximum: int = 500) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:maximum] or None


def _clean_list(value: object, *, maximum_items: int = 40) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    cleaned = []
    for item in value:
        text = _clean_text(item, maximum=120)
        if text:
            cleaned.append(text)
        if len(cleaned) >= maximum_items:
            break
    return tuple(cleaned)


class YCCompany(BaseModel):
    """One public YC directory record; shared reference data, not personal data."""

    slug: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    status: str = "Unknown"
    batch: str | None = None
    is_hiring: bool | None = None
    top_company: bool = False
    nonprofit: bool = False
    team_size: int | None = Field(default=None, ge=0)
    stage: str | None = None
    one_liner: str | None = None
    industries: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    locations: str | None = None
    website: str | None = None
    directory_url: str

    @field_validator("status")
    @classmethod
    def status_must_be_known(cls, value: str) -> str:
        cleaned = str(value).strip()
        return cleaned if cleaned in YC_STATUSES else "Unknown"

    @field_validator("website", "directory_url")
    @classmethod
    def url_must_be_https(cls, value: object) -> str | None:
        return _optional_https(value)


class YCFilters(BaseModel):
    """Deterministic local filters mirroring the ycglobe-style query flags."""

    statuses: tuple[str, ...] = ()
    hiring_only: bool = False
    top_only: bool = False
    batches: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    query: str = ""
    min_team_size: int | None = Field(default=None, ge=0)
    max_team_size: int | None = Field(default=None, ge=0)
    limit: int = Field(default=100, ge=1, le=MAX_FILTER_LIMIT)

    @field_validator("statuses")
    @classmethod
    def statuses_must_be_known(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = [status for status in value if status not in YC_STATUSES]
        if unknown:
            raise ValueError(f"Unknown YC status filter: {', '.join(unknown)}")
        return value

    @field_validator("query")
    @classmethod
    def query_is_bounded(cls, value: str) -> str:
        return value.strip()[:200]


def parse_yc_directory(payload: object, *, limit: int = MAX_DIRECTORY_RECORDS) -> list[YCCompany]:
    """Parse a bounded yc-oss ``all.json`` payload into validated records."""

    if not 1 <= limit <= MAX_DIRECTORY_RECORDS:
        raise ValueError(f"Directory limit must be between 1 and {MAX_DIRECTORY_RECORDS}")
    if not isinstance(payload, list):
        raise ValueError("YC directory response was not a list")
    companies: list[YCCompany] = []
    for item in payload[:limit]:
        if not isinstance(item, dict) or not item.get("name") or not item.get("slug"):
            continue
        team_size = item.get("team_size")
        companies.append(YCCompany(
            slug=str(item["slug"])[:200],
            name=str(item["name"])[:200],
            status=str(item.get("status") or "Unknown"),
            batch=_clean_text(item.get("batch"), maximum=40),
            is_hiring=bool(item["isHiring"]) if item.get("isHiring") is not None else None,
            top_company=bool(item.get("top_company")),
            nonprofit=bool(item.get("nonprofit")),
            team_size=int(team_size) if isinstance(team_size, int) and team_size >= 0 else None,
            stage=_clean_text(item.get("stage"), maximum=80),
            one_liner=_clean_text(item.get("one_liner")),
            industries=_clean_list(item.get("industries")),
            regions=_clean_list(item.get("regions")),
            tags=_clean_list(item.get("tags")),
            locations=_clean_text(item.get("all_locations")),
            website=_optional_https(item.get("website")),
            directory_url=_optional_https(item.get("url"))
            or f"https://www.ycombinator.com/companies/{item['slug']}",
        ))
    return companies


def fetch_yc_directory(*, fetcher: Callable[..., bytes] = _fetch) -> list[YCCompany]:
    """Explicitly refresh the directory from the single fixed yc-oss endpoint."""

    data = fetcher(YC_ALL_URL, expected_host=YC_HOST, max_bytes=MAX_DIRECTORY_BYTES)
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("YC directory returned invalid JSON") from exc
    return parse_yc_directory(payload)


def _matches_any(haystack: tuple[str, ...], needles: tuple[str, ...]) -> bool:
    lowered = [entry.casefold() for entry in haystack]
    return any(needle.casefold() in entry for needle in needles for entry in lowered)


def filter_yc_companies(companies: list[YCCompany], filters: YCFilters) -> list[YCCompany]:
    """Apply local filters; ordering stays the snapshot's stable name order."""

    needle = filters.query.casefold()
    results: list[YCCompany] = []
    for company in sorted(companies, key=lambda entry: entry.name.casefold()):
        if filters.statuses and company.status not in filters.statuses:
            continue
        if filters.hiring_only and company.is_hiring is not True:
            continue
        if filters.top_only and not company.top_company:
            continue
        if filters.batches and (company.batch or "") not in filters.batches:
            continue
        if filters.industries and not _matches_any(company.industries, filters.industries):
            continue
        if filters.regions and not _matches_any((*company.regions, company.locations or ""), filters.regions):
            continue
        if filters.min_team_size is not None and (company.team_size is None or company.team_size < filters.min_team_size):
            continue
        if filters.max_team_size is not None and (company.team_size is None or company.team_size > filters.max_team_size):
            continue
        if needle:
            searchable = " ".join(
                [company.name, company.one_liner or "", *company.industries, *company.tags, company.batch or ""]
            ).casefold()
            if needle not in searchable:
                continue
        results.append(company)
        if len(results) >= filters.limit:
            break
    return results


def directory_facets(companies: list[YCCompany]) -> dict[str, list[str]]:
    """Distinct filter values available in the current snapshot."""

    batches, industries, regions = set(), set(), set()
    for company in companies:
        if company.batch:
            batches.add(company.batch)
        industries.update(company.industries)
        regions.update(company.regions)
    return {
        "statuses": list(YC_STATUSES),
        "batches": sorted(batches, reverse=True),
        "industries": sorted(industries, key=str.casefold),
        "regions": sorted(regions, key=str.casefold),
    }


class YCDirectoryStore:
    """Local snapshot of the shared YC directory; refreshed only on demand."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS yc_directory (
                    slug TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    snapshot_id INTEGER NOT NULL REFERENCES yc_directory_snapshots(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS yc_directory_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url TEXT NOT NULL,
                    refreshed_at TEXT NOT NULL,
                    record_count INTEGER NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def refresh(self, companies: list[YCCompany], *, source_url: str = YC_ALL_URL) -> int:
        if not 1 <= len(companies) <= MAX_DIRECTORY_RECORDS:
            raise ValueError("A directory refresh must contain between 1 and 10,000 companies")
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO yc_directory_snapshots(source_url,refreshed_at,record_count) VALUES(?,?,?)",
                (source_url, now, len(companies)),
            )
            snapshot_id = cursor.lastrowid
            db.execute("DELETE FROM yc_directory")
            for company in companies:
                record = YCCompany.model_validate(company)
                db.execute(
                    "INSERT INTO yc_directory(slug,name,payload_json,snapshot_id) VALUES(?,?,?,?)",
                    (record.slug, record.name, record.model_dump_json(), snapshot_id),
                )
        return len(companies)

    def snapshot(self) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT id,source_url,refreshed_at,record_count FROM yc_directory_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def companies(self) -> list[YCCompany]:
        with self._connect() as db:
            rows = db.execute("SELECT payload_json FROM yc_directory ORDER BY name COLLATE NOCASE").fetchall()
        return [YCCompany.model_validate_json(row["payload_json"]) for row in rows]

    def search(self, filters: YCFilters) -> list[YCCompany]:
        return filter_yc_companies(self.companies(), filters)
