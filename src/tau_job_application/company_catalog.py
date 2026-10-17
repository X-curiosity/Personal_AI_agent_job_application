"""Bounded company discovery imports and reviewed first-party job-board mappings.

Directory imports create local company leads. They never turn a directory page
into a job advert and never crawl a company's site. Openings are fetched only
after an employer board has been mapped to one of the supported public ATS APIs.
"""
from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from ipaddress import ip_address
import json
import socket
import sqlite3
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator

from tau_job_application.role_discovery import CompanyFacts, UNKNOWN, VettedCompanyBoard


CMC_URL = "https://companiesmarketcap.com/"
YC_HIRING_URL = "https://yc-oss.github.io/api/companies/hiring.json"
CATALOG_USER_AGENT = "CareerWorkspace/0.2 (+local user-initiated company import)"
MAX_RESPONSE_BYTES = 8_000_000
SUPPORTED_BOARDS = {
    "Greenhouse": ("https://boards.greenhouse.io/{identifier}", "boards.greenhouse.io"),
    "Lever": ("https://jobs.lever.co/{identifier}", "jobs.lever.co"),
    "Ashby": ("https://jobs.ashbyhq.com/{identifier}", "jobs.ashbyhq.com"),
}


def _optional_https(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return text


def _required(value: str, label: str, maximum: int = 200) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"{label} must be between 1 and {maximum} characters")
    return cleaned


def employee_band(team_size: object) -> str:
    try:
        size = int(team_size)
    except (TypeError, ValueError):
        return UNKNOWN
    if size < 1:
        return UNKNOWN
    if size <= 10:
        return "1-10"
    if size <= 50:
        return "11-50"
    if size <= 200:
        return "51-200"
    if size <= 1_000:
        return "201-1,000"
    return "1,001+"


class CatalogCompany(BaseModel):
    source: Literal["CompaniesMarketCap", "YC community API", "Global Capital Atlas"]
    source_key: str = Field(min_length=1, max_length=200)
    source_url: str
    name: str = Field(min_length=1, max_length=200)
    company_type: str = UNKNOWN
    website: str | None = None
    logo_url: str | None = None
    country: str | None = None
    locations: str | None = None
    industry: str | None = None
    funding_stage: str = UNKNOWN
    employee_band: str = UNKNOWN
    hiring: bool | None = None
    ticker: str | None = None
    rank: int | None = None
    market_cap: str | None = None
    yc_batch: str | None = None
    summary: str | None = None

    @field_validator("source_url")
    @classmethod
    def source_must_be_https(cls, value: str) -> str:
        cleaned = _optional_https(value)
        if not cleaned:
            raise ValueError("Source URL must be public HTTPS")
        return cleaned

    @field_validator("website", "logo_url", mode="before")
    @classmethod
    def clean_optional_url(cls, value: object) -> str | None:
        return _optional_https(value)


class _CompanyTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, object]] = []
        self.row: dict[str, object] | None = None
        self.field: str | None = None
        self.cell_index = -1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "tr":
            self.row = {"country_parts": []}
            self.cell_index = -1
        elif tag == "td" and self.row is not None:
            self.cell_index += 1
            if "rank-td" in classes and values.get("data-sort", "").isdigit():
                self.row["rank"] = int(values["data-sort"] or 0)
            elif self.cell_index == 3:
                self.row["market_cap"] = ""
        elif tag == "a" and self.row is not None and "/marketcap/" in (values.get("href") or ""):
            self.row["href"] = values.get("href")
        elif tag == "div" and self.row is not None:
            if "company-name" in classes:
                self.field = "name"
            elif "company-code" in classes:
                self.field = "ticker"
        elif tag == "span" and self.row is not None and self.cell_index >= 7:
            self.field = "country"

    def handle_data(self, data: str) -> None:
        if self.row is None:
            return
        text = data.strip()
        if not text:
            return
        if self.field in {"name", "ticker"}:
            self.row[self.field] = str(self.row.get(self.field, "")) + text
        elif self.field == "country":
            self.row["country_parts"].append(text)
        elif self.cell_index == 3:
            self.row["market_cap"] = (str(self.row.get("market_cap", "")) + " " + text).strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.field in {"name", "ticker"}:
            self.field = None
        elif tag == "span" and self.field == "country":
            self.field = None
        elif tag == "tr":
            if self.row and self.row.get("rank") and self.row.get("name") and self.row.get("href"):
                self.rows.append(self.row)
            self.row = None
            self.field = None


def parse_companies_marketcap(html: str, *, limit: int = 25) -> list[CatalogCompany]:
    if not 1 <= limit <= 100:
        raise ValueError("Import limit must be between 1 and 100")
    parser = _CompanyTableParser()
    parser.feed(html[:MAX_RESPONSE_BYTES])
    imported: list[CatalogCompany] = []
    for row in parser.rows[:limit]:
        href = str(row["href"])
        key = href.strip("/").split("/")[0]
        imported.append(CatalogCompany(
            source="CompaniesMarketCap", source_key=key,
            source_url=urljoin(CMC_URL, href), name=str(row["name"]).strip(),
            company_type="Public", funding_stage="Not applicable",
            country=" ".join(row.get("country_parts", [])).strip() or None,
            ticker=str(row.get("ticker") or "").strip() or None,
            rank=int(row["rank"]), market_cap=str(row.get("market_cap") or "").strip() or None,
        ))
    return imported


def parse_yc_hiring(payload: object, *, limit: int = 25, query: str = "") -> list[CatalogCompany]:
    if not 1 <= limit <= 100:
        raise ValueError("Import limit must be between 1 and 100")
    if not isinstance(payload, list):
        raise ValueError("YC company response was not a list")
    needle = query.strip().casefold()
    results: list[CatalogCompany] = []
    for item in payload:
        if not isinstance(item, dict) or not item.get("name") or not item.get("slug"):
            continue
        searchable = " ".join(str(item.get(key) or "") for key in ("name", "one_liner", "industry", "subindustry", "tags")).casefold()
        if needle and needle not in searchable:
            continue
        results.append(CatalogCompany(
            source="YC community API", source_key=str(item["slug"]),
            source_url=_optional_https(item.get("url")) or f"https://www.ycombinator.com/companies/{item['slug']}",
            name=str(item["name"]), company_type="Startup",
            website=_optional_https(item.get("website")), logo_url=_optional_https(item.get("small_logo_thumb_url")),
            locations=str(item.get("all_locations") or "").strip() or None,
            industry=str(item.get("subindustry") or item.get("industry") or "").strip() or None,
            funding_stage=str(item.get("stage") or UNKNOWN), employee_band=employee_band(item.get("team_size")),
            hiring=bool(item.get("isHiring")), yc_batch=str(item.get("batch") or "").strip() or None,
            summary=str(item.get("one_liner") or "").strip()[:500] or None,
        ))
        if len(results) >= limit:
            break
    return results


def _fetch(url: str, *, expected_host: str, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise ValueError("Only the configured HTTPS catalogue endpoint can be fetched")
    for record in socket.getaddrinfo(expected_host, 443, type=socket.SOCK_STREAM):
        address = ip_address(record[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValueError("Catalogue source resolved to a non-public address")
    request = Request(url, headers={"Accept": "text/html,application/json", "User-Agent": CATALOG_USER_AGENT})
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed, allow-listed endpoints only
            if urlparse(response.geturl()).hostname != expected_host:
                raise ValueError("Catalogue source redirected to an unexpected host")
            data = response.read(max_bytes + 1)
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not refresh {expected_host}: {exc}") from exc
    if len(data) > max_bytes:
        raise RuntimeError(f"Catalogue response exceeded the {max_bytes // 1_000_000} MB safety limit")
    return data


def fetch_companies_marketcap(*, limit: int = 25, fetcher: Callable[..., bytes] = _fetch) -> list[CatalogCompany]:
    data = fetcher(CMC_URL, expected_host="companiesmarketcap.com")
    return parse_companies_marketcap(data.decode("utf-8", errors="replace"), limit=limit)


def fetch_yc_hiring(*, limit: int = 25, query: str = "", fetcher: Callable[..., bytes] = _fetch) -> list[CatalogCompany]:
    data = fetcher(YC_HIRING_URL, expected_host="yc-oss.github.io")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("YC catalogue returned invalid JSON") from exc
    return parse_yc_hiring(payload, limit=limit, query=query)


class CompanyCatalogStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS company_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL, source_key TEXT NOT NULL, name TEXT NOT NULL,
                    payload_json TEXT NOT NULL, imported_at TEXT NOT NULL,
                    UNIQUE(source, source_key)
                );
                CREATE TABLE IF NOT EXISTS company_job_boards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL REFERENCES company_catalog(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL, identifier TEXT NOT NULL, board_url TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL, UNIQUE(company_id, provider, identifier)
                );
                CREATE TABLE IF NOT EXISTS company_catalog_imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                    imported_at TEXT NOT NULL, record_count INTEGER NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def import_companies(self, companies: list[CatalogCompany]) -> int:
        if not companies or len(companies) > 100:
            raise ValueError("Each import must contain between 1 and 100 companies")
        now = self._now()
        with self._connect() as db:
            for company in companies:
                record = CatalogCompany.model_validate(company)
                db.execute("""INSERT INTO company_catalog(source,source_key,name,payload_json,imported_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(source,source_key) DO UPDATE SET
                    name=excluded.name,payload_json=excluded.payload_json,imported_at=excluded.imported_at""",
                    (record.source, record.source_key, record.name, record.model_dump_json(), now))
            db.execute("INSERT INTO company_catalog_imports(source,imported_at,record_count) VALUES(?,?,?)",
                       (companies[0].source, now, len(companies)))
        return len(companies)

    def list_companies(self, *, query: str = "", source: str | None = None, hiring_only: bool = False, limit: int = 200) -> list[dict[str, object]]:
        if not 1 <= limit <= 500:
            raise ValueError("List limit must be between 1 and 500")
        clauses, values = [], []
        if source:
            clauses.append("source=?")
            values.append(source)
        rows_query = "SELECT id,payload_json,imported_at FROM company_catalog"
        if clauses:
            rows_query += " WHERE " + " AND ".join(clauses)
        # Text and hiring filters run before the limit: limiting first would
        # hide matching records that sort beyond the first page alphabetically.
        # The hard scan cap keeps a huge local catalogue bounded in memory.
        rows_query += " ORDER BY name COLLATE NOCASE LIMIT 10000"
        needle = query.strip().casefold()
        with self._connect() as db:
            rows = db.execute(rows_query, values).fetchall()
            board_counts = {row[0]: row[1] for row in db.execute("SELECT company_id,COUNT(*) FROM company_job_boards GROUP BY company_id")}
        result = []
        for row in rows:
            company = CatalogCompany.model_validate_json(row["payload_json"])
            searchable = " ".join(filter(None, [company.name, company.industry, company.country, company.locations, company.ticker])).casefold()
            if (needle and needle not in searchable) or (hiring_only and company.hiring is not True):
                continue
            result.append({"id": row["id"], "company": company, "imported_at": row["imported_at"], "board_count": board_counts.get(row["id"], 0)})
            if len(result) >= limit:
                break
        return result

    def register_board(self, company_id: int, provider: str, identifier: str) -> VettedCompanyBoard:
        if provider not in SUPPORTED_BOARDS:
            raise ValueError("Choose Greenhouse, Lever, or Ashby")
        identifier = _required(identifier, "Board identifier", 100)
        if not identifier.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise ValueError("Board identifier contains unsupported characters")
        with self._connect() as db:
            row = db.execute("SELECT payload_json FROM company_catalog WHERE id=?", (company_id,)).fetchone()
            if not row:
                raise ValueError("Company not found")
            company = CatalogCompany.model_validate_json(row[0])
            board_url = SUPPORTED_BOARDS[provider][0].format(identifier=identifier)
            db.execute("""INSERT INTO company_job_boards(company_id,provider,identifier,board_url,reviewed_at)
                VALUES(?,?,?,?,?) ON CONFLICT(company_id,provider,identifier) DO UPDATE SET
                board_url=excluded.board_url,reviewed_at=excluded.reviewed_at""",
                (company_id, provider, identifier, board_url, self._now()))
        return self._as_board(company, provider, identifier, board_url)

    def boards(self) -> tuple[VettedCompanyBoard, ...]:
        with self._connect() as db:
            rows = db.execute("""SELECT c.payload_json,b.provider,b.identifier,b.board_url
                FROM company_job_boards b JOIN company_catalog c ON c.id=b.company_id
                ORDER BY c.name COLLATE NOCASE,b.provider""").fetchall()
        return tuple(self._as_board(CatalogCompany.model_validate_json(row[0]), row[1], row[2], row[3]) for row in rows)

    @staticmethod
    def _as_board(company: CatalogCompany, provider: str, identifier: str, board_url: str) -> VettedCompanyBoard:
        return VettedCompanyBoard(company=CompanyFacts(
            name=company.name, company_type=company.company_type,
            employee_band=company.employee_band, funding_stage=company.funding_stage,
            facts_source_url=company.source_url, verified_at=datetime.now(UTC).date().isoformat(),
        ), source=provider, board_identifier=identifier, board_url=board_url)
