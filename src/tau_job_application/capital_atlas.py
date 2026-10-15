"""Global Capital Atlas: local snapshot of large companies ($10B+).

capital.theojaffee.net is a single-page atlas whose company records ship
inside its JavaScript bundle. The fetcher reads only the fixed homepage and
the referenced page asset on the same host (redirects rejected, 8 MB bound),
tolerantly parses the embedded record array, and stores a local snapshot that
filters run against. An explicit refresh is the only network access. A
valuation entry is never proof of an open vacancy.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from tau_job_application.company_catalog import CatalogCompany, _fetch, _optional_https

ATLAS_HOME_URL = "https://capital.theojaffee.net/"
ATLAS_HOST = "capital.theojaffee.net"
MAX_ATLAS_RECORDS = 3_000
MAX_ASSET_BYTES = 8_000_000
VALUE_THRESHOLDS = (10, 25, 50, 100, 250, 500, 1000)
OWNERSHIP_TYPES = ("Public", "Private", "Other")

_PAGE_ASSET_RE = re.compile(r'(?:href|src)="(/assets/page-[^"]+\.js)"')
_ARRAY_START_RE = re.compile(r"=\s*(\[\s*\{\s*rank\s*:)")

_WHITESPACE = " \t\r\n,"
_NUMBER_RE = re.compile(r"-?\d*\.?\d+(?:[eE][+-]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_LITERALS = {"true": True, "false": False, "null": None, "undefined": None}


def _skip_filler(text: str, index: int) -> int:
    while index < len(text) and text[index] in _WHITESPACE:
        index += 1
    return index


def _parse_string(text: str, index: int) -> tuple[str, int]:
    quote = text[index]
    index += 1
    out: list[str] = []
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            escape = text[index + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(escape, escape))
            index += 2
            continue
        if char == quote:
            return "".join(out), index + 1
        out.append(char)
        index += 1
    raise ValueError("Unterminated string in atlas data")


def _parse_value(text: str, index: int, depth: int = 0):
    if depth > 12:
        raise ValueError("Atlas data nesting exceeded the safety bound")
    index = _skip_filler(text, index)
    if index >= len(text):
        raise ValueError("Unexpected end of atlas data")
    char = text[index]
    if char in "`\"'":
        return _parse_string(text, index)
    if char == "[":
        items: list = []
        index += 1
        while True:
            index = _skip_filler(text, index)
            if index >= len(text):
                raise ValueError("Unterminated array in atlas data")
            if text[index] == "]":
                return items, index + 1
            value, index = _parse_value(text, index, depth + 1)
            items.append(value)
    if char == "{":
        record: dict = {}
        index += 1
        while True:
            index = _skip_filler(text, index)
            if index >= len(text):
                raise ValueError("Unterminated object in atlas data")
            if text[index] == "}":
                return record, index + 1
            if text[index] in "`\"'":
                key, index = _parse_string(text, index)
            else:
                match = _IDENT_RE.match(text, index)
                if not match:
                    raise ValueError(f"Unexpected object key at offset {index}")
                key, index = match.group(0), match.end()
            index = _skip_filler(text, index)
            if index >= len(text) or text[index] != ":":
                raise ValueError(f"Expected ':' after key {key!r}")
            value, index = _parse_value(text, index + 1, depth + 1)
            record[key] = value
    if text.startswith("!0", index):
        return True, index + 2
    if text.startswith("!1", index):
        return False, index + 2
    number = _NUMBER_RE.match(text, index)
    if number:
        raw = number.group(0)
        return (float(raw) if any(mark in raw for mark in ".eE") else int(raw)), number.end()
    ident = _IDENT_RE.match(text, index)
    if ident and ident.group(0) in _LITERALS:
        return _LITERALS[ident.group(0)], ident.end()
    raise ValueError(f"Unexpected token at offset {index}")


def _format_value(billions: float | int | None) -> str | None:
    if not isinstance(billions, (int, float)) or billions <= 0:
        return None
    if billions >= 1000:
        return f"${billions / 1000:.1f}T"
    return f"${billions:g}B"


def _clean(value: object, *, maximum: int) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:maximum] or None


class AtlasCompany(BaseModel):
    """One public atlas record; shared reference data, not personal data."""

    slug: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    ownership: str = "Other"
    rank: int | None = None
    value_billions: float = Field(gt=0)
    country: str | None = None
    ticker: str | None = None
    industry: str | None = None
    address: str | None = None
    website: str | None = None
    description: str | None = None
    source_url: str

    @field_validator("ownership")
    @classmethod
    def ownership_must_be_known(cls, value: str) -> str:
        cleaned = str(value).strip()
        return cleaned if cleaned in OWNERSHIP_TYPES else "Other"

    @field_validator("website", "source_url")
    @classmethod
    def url_must_be_https(cls, value: object) -> str | None:
        return _optional_https(value)

    @property
    def formatted_value(self) -> str:
        return _format_value(self.value_billions) or "Unknown"


class AtlasFilters(BaseModel):
    """Deterministic local filters over the stored atlas snapshot."""

    min_value_billions: int = 10
    ownership: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    query: str = ""
    limit: int = Field(default=100, ge=1, le=500)

    @field_validator("min_value_billions")
    @classmethod
    def threshold_must_be_known(cls, value: int) -> int:
        if value not in VALUE_THRESHOLDS:
            raise ValueError("Minimum value must be one of 10, 25, 50, 100, 250, 500, 1000 (billions USD)")
        return value

    @field_validator("ownership")
    @classmethod
    def ownership_must_be_valid(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = [item for item in value if item not in OWNERSHIP_TYPES]
        if unknown:
            raise ValueError(f"Unknown ownership filter: {', '.join(unknown)}")
        return value

    @field_validator("query")
    @classmethod
    def query_is_bounded(cls, value: str) -> str:
        return value.strip()[:200]


def _slug(name: str, fallback: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:200] or fallback


def parse_atlas_companies(js_text: str, *, limit: int = MAX_ATLAS_RECORDS) -> list[AtlasCompany]:
    """Parse the embedded record array into validated atlas companies."""

    if not 1 <= limit <= MAX_ATLAS_RECORDS:
        raise ValueError(f"Parse limit must be between 1 and {MAX_ATLAS_RECORDS}")
    if len(js_text.encode("utf-8", errors="replace")) > MAX_ASSET_BYTES:
        raise ValueError("Atlas asset exceeded the 8 MB safety limit")
    start = _ARRAY_START_RE.search(js_text)
    if not start:
        raise ValueError("Atlas data array was not found in the page asset")
    records, _ = _parse_value(js_text, start.start(1))
    if not isinstance(records, list):
        raise ValueError("Atlas data was not an array")
    if len(records) > MAX_ATLAS_RECORDS:
        raise ValueError(f"Atlas returned more than {MAX_ATLAS_RECORDS} records; refusing the import")

    companies: list[AtlasCompany] = []
    seen: set[str] = set()
    for record in records:
        if len(companies) >= limit:
            break
        if not isinstance(record, dict) or not record.get("name"):
            continue
        value = record.get("value")
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        name = str(record["name"]).strip()[:200]
        slug = _slug(name, f"rank-{record.get('rank', len(companies) + 1)}")
        if slug in seen:
            continue
        seen.add(slug)
        companies.append(AtlasCompany(
            slug=slug, name=name,
            ownership=str(record.get("ownership") or "Other"),
            rank=int(record["rank"]) if isinstance(record.get("rank"), int) else None,
            value_billions=float(value),
            country=_clean(record.get("country"), maximum=100),
            ticker=_clean(record.get("ticker"), maximum=40),
            industry=_clean(record.get("subIndustry") or record.get("industry"), maximum=200),
            address=_clean(record.get("address"), maximum=300),
            website=_optional_https(record.get("website")),
            description=_clean(record.get("description"), maximum=500),
            source_url=_optional_https(record.get("source")) or ATLAS_HOME_URL,
        ))
    if not companies:
        raise ValueError("No atlas companies were parsed from the page asset")
    return sorted(companies, key=lambda company: company.value_billions, reverse=True)


def filter_atlas_companies(companies: list[AtlasCompany], filters: AtlasFilters) -> list[AtlasCompany]:
    """Apply local filters; ordering stays value-descending."""

    needle = filters.query.casefold()
    results: list[AtlasCompany] = []
    for company in sorted(companies, key=lambda entry: entry.value_billions, reverse=True):
        if company.value_billions < filters.min_value_billions:
            continue
        if filters.ownership and company.ownership not in filters.ownership:
            continue
        if filters.industries and not any(
            needle_industry.casefold() in (company.industry or "").casefold()
            for needle_industry in filters.industries
        ):
            continue
        if filters.countries and not any(
            needle_country.casefold() in (company.country or "").casefold()
            for needle_country in filters.countries
        ):
            continue
        if needle:
            searchable = " ".join(filter(None, [company.name, company.description, company.industry, company.ticker])).casefold()
            if needle not in searchable:
                continue
        results.append(company)
        if len(results) >= filters.limit:
            break
    return results


def atlas_facets(companies: list[AtlasCompany]) -> dict[str, list[str]]:
    industries = sorted({company.industry for company in companies if company.industry}, key=str.casefold)
    countries = sorted({company.country for company in companies if company.country}, key=str.casefold)
    return {"industries": industries, "countries": countries, "ownership": list(OWNERSHIP_TYPES)}


def to_catalog_company(company: AtlasCompany) -> CatalogCompany:
    return CatalogCompany(
        source="Global Capital Atlas", source_key=company.slug,
        source_url=company.source_url, name=company.name,
        company_type=company.ownership, website=company.website,
        country=company.country, locations=company.address,
        industry=company.industry, funding_stage="Not applicable",
        ticker=company.ticker, rank=company.rank,
        market_cap=company.formatted_value, summary=company.description,
    )


def parse_capital_atlas(js_text: str, *, min_value_billions: int = 10, limit: int = 100) -> list[CatalogCompany]:
    """Convert the embedded atlas records into bounded catalogue leads."""

    if not 1 <= limit <= 500:
        raise ValueError("Import limit must be between 1 and 500")
    filters = AtlasFilters(min_value_billions=min_value_billions, limit=limit)
    imported = [to_catalog_company(company) for company in filter_atlas_companies(parse_atlas_companies(js_text), filters)]
    if not imported:
        raise ValueError("No atlas companies matched the selected value threshold")
    return imported


def fetch_atlas_companies(*, fetcher=_fetch) -> list[AtlasCompany]:
    """Explicitly fetch the atlas homepage and its page asset, then parse."""

    html = fetcher(ATLAS_HOME_URL, expected_host=ATLAS_HOST).decode("utf-8", errors="replace")
    asset = _PAGE_ASSET_RE.search(html)
    if not asset:
        raise RuntimeError("The atlas homepage did not reference its page asset")
    js_text = fetcher(f"{ATLAS_HOME_URL.rstrip('/')}{asset.group(1)}", expected_host=ATLAS_HOST).decode("utf-8", errors="replace")
    return parse_atlas_companies(js_text)


def fetch_capital_atlas(*, min_value_billions: int = 10, limit: int = 100, fetcher=_fetch) -> list[CatalogCompany]:
    """Explicitly fetch atlas data as catalogue leads (companies-view import)."""

    filters = AtlasFilters(min_value_billions=min_value_billions, limit=limit)
    return [to_catalog_company(company) for company in filter_atlas_companies(fetch_atlas_companies(fetcher=fetcher), filters)]


class AtlasStore:
    """Local snapshot of the shared atlas; refreshed only on demand."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS atlas_companies (
                    slug TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    snapshot_id INTEGER NOT NULL REFERENCES atlas_snapshots(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS atlas_snapshots (
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

    def refresh(self, companies: list[AtlasCompany], *, source_url: str = ATLAS_HOME_URL) -> int:
        if not 1 <= len(companies) <= MAX_ATLAS_RECORDS:
            raise ValueError(f"An atlas refresh must contain between 1 and {MAX_ATLAS_RECORDS} companies")
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO atlas_snapshots(source_url,refreshed_at,record_count) VALUES(?,?,?)",
                (source_url, now, len(companies)),
            )
            snapshot_id = cursor.lastrowid
            db.execute("DELETE FROM atlas_companies")
            for company in companies:
                record = AtlasCompany.model_validate(company)
                db.execute(
                    "INSERT INTO atlas_companies(slug,name,payload_json,snapshot_id) VALUES(?,?,?,?)",
                    (record.slug, record.name, record.model_dump_json(), snapshot_id),
                )
        return len(companies)

    def snapshot(self) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT id,source_url,refreshed_at,record_count FROM atlas_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def companies(self) -> list[AtlasCompany]:
        with self._connect() as db:
            rows = db.execute("SELECT payload_json FROM atlas_companies").fetchall()
        return [AtlasCompany.model_validate_json(row["payload_json"]) for row in rows]

    def search(self, filters: AtlasFilters) -> list[AtlasCompany]:
        return filter_atlas_companies(self.companies(), filters)
