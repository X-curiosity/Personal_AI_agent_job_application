"""Internal index of companies that are actively hiring.

Two deliberate, always-visible signal levels:

- ``live_openings`` — current openings fetched from an official, reviewed ATS
  board (Greenhouse, Lever, or Ashby). These are the same postings LinkedIn
  mirrors, read through the employers' own feeds.
- ``directory_flag`` — the local YC directory snapshot (yc-oss, the dataset
  behind vclense-style YC globe views) marks the company Active + hiring.
  This is a directory claim, not verified against a live board.

LinkedIn is intentionally **not** a source: automated access to
linkedin.com/jobs violates LinkedIn's User Agreement, and the official Jobs
API is partner-only. The index never scrapes or automates LinkedIn; live
verification uses only reviewed board mappings and the built-in vetted
registry, capped per build.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable, Literal

from pydantic import BaseModel, Field

from tau_job_application.company_catalog import CompanyCatalogStore
from tau_job_application.role_discovery import DEFAULT_VETTED_COMPANY_BOARDS
from tau_job_application.yc_directory import YCDirectoryStore, YCFilters

MAX_INDEX_ENTRIES = 500
MAX_LIVE_CHECKS_PER_BUILD = 25
MAX_SAMPLES = 5

Signal = Literal["live_openings", "directory_flag"]


class HiringEntry(BaseModel):
    """One company in the hiring index; shared public facts, not personal data."""

    company_key: str = Field(min_length=1, max_length=240)
    name: str = Field(min_length=1, max_length=200)
    signal: Signal
    openings_count: int | None = Field(default=None, ge=0)
    sample_titles: tuple[str, ...] = ()
    sample_locations: tuple[str, ...] = ()
    industry: str | None = None
    locations: str | None = None
    website: str | None = None
    logo_url: str | None = None
    yc_batch: str | None = None
    team_size: int | None = Field(default=None, ge=0)
    board_provider: str | None = None
    board_url: str | None = None
    source_label: str = Field(min_length=1, max_length=120)
    source_url: str


class IndexBuild(BaseModel):
    """Result of one index build: entries plus the audit facts callers need."""

    entries: list["HiringEntry"]
    errors: list[str]
    live_checks: int = 0
    failed_board_keys: list[str] = Field(default_factory=list)


def _unique_boards(boards: Iterable) -> list:
    """One live check per normalized (provider, identifier); first record wins.

    The built-in registry and the user-reviewed catalogue can name the same
    board. Checking it twice would duplicate ``company_key`` values and crash
    persistence with a primary-key violation.
    """
    seen: set[tuple[str, str]] = set()
    result: list = []
    for board in boards:
        key = (board.source.casefold(), board.board_identifier.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(board)
    return result


def _samples(openings: list) -> tuple[tuple[str, ...], tuple[str, ...]]:
    titles = tuple(
        str(opening.get("title") or "").strip()[:120]
        for opening in openings[:MAX_SAMPLES]
        if isinstance(opening, dict) and opening.get("title")
    )
    locations = tuple(dict.fromkeys(
        str(opening.get("location") or "").strip()[:120]
        for opening in openings
        if isinstance(opening, dict) and opening.get("location")
    ))[:MAX_SAMPLES]
    return titles, locations


def build_hiring_index(
    *,
    yc_store: YCDirectoryStore,
    catalog_store: CompanyCatalogStore,
    fetch_openings: Callable[..., list],
    max_live_checks: int = MAX_LIVE_CHECKS_PER_BUILD,
) -> IndexBuild:
    """Rebuild the index: boards-first live checks, then YC directory flags.

    Live rows come from the built-in vetted registry and user-reviewed board
    mappings (these include big companies, whose ATS postings are the ones
    LinkedIn mirrors). A failed board check never fabricates an opening count:
    the board is skipped and reported in the returned error list. A board that
    responds successfully with zero openings is a checked board with no live
    roles, not an "actively hiring" row, so it produces no live entry. YC
    Active+hiring companies without a verified board stay directory-flagged.

    ``fetch_openings`` matches ``sources.fetch_public_board_openings`` and is
    injected so tests never touch the network.
    """

    entries: list[HiringEntry] = []
    errors: list[str] = []
    failed_board_keys: list[str] = []
    live_names: set[str] = set()
    checks = 0
    live_checks = 0
    for board in _unique_boards((*DEFAULT_VETTED_COMPANY_BOARDS, *catalog_store.boards())):
        if checks >= max_live_checks:
            break
        checks += 1
        board_key = f"board:{board.source}:{board.board_identifier}"
        try:
            openings = fetch_openings(board.source, board.board_identifier, company=board.company.name)
        except (RuntimeError, ValueError) as exc:
            errors.append(f"{board.company.name} ({board.source}): {type(exc).__name__}")
            failed_board_keys.append(board_key)
            continue
        live_checks += 1
        if not openings:
            continue
        titles, locations = _samples(openings)
        live_names.add(board.company.name.casefold())
        entries.append(HiringEntry(
            company_key=board_key,
            name=board.company.name, signal="live_openings",
            openings_count=len(openings), sample_titles=titles, sample_locations=locations,
            board_provider=board.source, board_url=board.board_url,
            source_label=f"Live {board.source} board", source_url=board.board_url,
        ))

    remaining = MAX_INDEX_ENTRIES - len(entries)
    candidates = yc_store.search(
        YCFilters(statuses=("Active",), hiring_only=True, limit=max(1, remaining))
    ) if remaining > 0 else []
    for company in candidates:
        if company.name.casefold() in live_names:
            # Enrich the existing live row with directory facts instead of duplicating.
            live_entry = next(entry for entry in entries if entry.name.casefold() == company.name.casefold())
            entries[entries.index(live_entry)] = live_entry.model_copy(update={
                "logo_url": company.logo_url or live_entry.logo_url,
                "website": company.website or live_entry.website,
                "yc_batch": company.batch,
                "team_size": company.team_size,
                "industry": company.industries[0] if company.industries else live_entry.industry,
            })
            continue
        entries.append(HiringEntry(
            company_key=f"yc:{company.slug}", name=company.name, signal="directory_flag",
            industry=company.industries[0] if company.industries else None,
            locations=company.locations, website=company.website, logo_url=company.logo_url,
            yc_batch=company.batch, team_size=company.team_size,
            source_label="YC directory flag (unverified)", source_url=company.directory_url,
        ))
    return IndexBuild(entries=entries, errors=errors, live_checks=live_checks, failed_board_keys=failed_board_keys)


def refresh_all_data(
    db_path: Path,
    *,
    yc_fetcher: Callable[[], list] | None = None,
    atlas_fetcher: Callable[[], list] | None = None,
    openings_fetcher: Callable[..., list],
) -> dict[str, object]:
    """One scheduled refresh: both snapshots, then a rebuilt hiring index.

    Snapshot sources are injected for testability; failures never destroy the
    previous snapshot or index and are reported in the summary.
    """

    from tau_job_application.capital_atlas import AtlasStore
    from tau_job_application.role_discovery import RoleDiscoveryStore, refresh_saved_role_markets

    summary: dict[str, object] = {"errors": []}
    yc_store = YCDirectoryStore(db_path)
    if yc_fetcher is not None:
        try:
            summary["yc_records"] = yc_store.refresh(yc_fetcher())
        except (RuntimeError, ValueError) as exc:
            summary["errors"].append(f"YC snapshot kept previous data: {type(exc).__name__}")
    atlas_store = AtlasStore(db_path)
    if atlas_fetcher is not None:
        try:
            summary["atlas_records"] = atlas_store.refresh(atlas_fetcher())
        except (RuntimeError, ValueError) as exc:
            summary["errors"].append(f"Atlas snapshot kept previous data: {type(exc).__name__}")
    catalog_store = CompanyCatalogStore(db_path)
    if yc_store.snapshot() is None:
        # Only the YC-dependent index build is skipped. Saved role markets use
        # official boards alone and still refresh below.
        summary["errors"].append("No YC snapshot available; hiring index not rebuilt")
        summary["indexed"] = 0
    else:
        build = build_hiring_index(
            yc_store=yc_store,
            catalog_store=catalog_store,
            fetch_openings=openings_fetcher,
        )
        indexed, outcome = persist_index_build(HiringIndexStore(db_path), build)
        summary["indexed"] = indexed
        if outcome == "kept_all_failed":
            summary["errors"].append("All official board checks failed; previous hiring index kept")
            summary["index_kept"] = True
        elif outcome == "kept_empty":
            summary["errors"].append("Hiring index build produced no entries; previous index kept")
            summary["index_kept"] = True
        else:
            summary["live"] = sum(1 for entry in build.entries if entry.signal == "live_openings")
        summary["errors"].extend(build.errors)

    # Saved role boards (the openings on role pages) refresh on the same schedule.
    boards = _unique_boards((*DEFAULT_VETTED_COMPANY_BOARDS, *catalog_store.boards()))
    role_summary = refresh_saved_role_markets(
        RoleDiscoveryStore(db_path), boards=boards, fetch_openings=openings_fetcher,
    )
    summary["role_markets"] = role_summary
    summary["errors"].extend(role_summary["errors"])
    return summary


def persist_index_build(store: "HiringIndexStore", build: IndexBuild) -> tuple[int, str]:
    """Save a build unless saving it would destroy verified information.

    Returns ``(entry_count, outcome)``:

    - ``saved`` — the build replaced the index. When some boards failed, the
      previous live rows for exactly those boards are retained first, because
      an unreachable feed is never evidence that roles closed.
    - ``kept_all_failed`` — every board check failed; the complete previous
      index stays untouched.
    - ``kept_empty`` — the build produced no entries at all; the previous
      index stays untouched.
    """
    if build.errors and build.live_checks == 0:
        return 0, "kept_all_failed"
    entries = list(build.entries)
    if build.failed_board_keys:
        previous = {entry.company_key: entry for entry in store.entries(limit=MAX_INDEX_ENTRIES)}
        present = {entry.company_key for entry in entries}
        for key in build.failed_board_keys:
            if key not in present and key in previous:
                entries.append(previous[key])
        entries = entries[:MAX_INDEX_ENTRIES]
    if not entries:
        return 0, "kept_empty"
    return store.save_run(entries), "saved"


class HiringIndexStore:
    """Local persistence for the index; rebuilt only on explicit action."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS hiring_index_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    built_at TEXT NOT NULL,
                    entry_count INTEGER NOT NULL,
                    live_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hiring_entries (
                    company_key TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    run_id INTEGER NOT NULL REFERENCES hiring_index_runs(id) ON DELETE CASCADE
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def save_run(self, entries: list[HiringEntry]) -> int:
        if not 1 <= len(entries) <= MAX_INDEX_ENTRIES:
            raise ValueError(f"A hiring index build must contain between 1 and {MAX_INDEX_ENTRIES} entries")
        live = sum(1 for entry in entries if entry.signal == "live_openings")
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO hiring_index_runs(built_at,entry_count,live_count) VALUES(?,?,?)",
                (datetime.now(UTC).isoformat(), len(entries), live),
            )
            run_id = cursor.lastrowid
            db.execute("DELETE FROM hiring_entries")
            for entry in entries:
                record = HiringEntry.model_validate(entry)
                db.execute(
                    "INSERT INTO hiring_entries(company_key,name,payload_json,run_id) VALUES(?,?,?,?)",
                    (record.company_key, record.name, record.model_dump_json(), run_id),
                )
        return len(entries)

    def run(self) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT id,built_at,entry_count,live_count FROM hiring_index_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def entries(
        self,
        *,
        signal: str = "",
        industry: str = "",
        region: str = "",
        query: str = "",
        limit: int = 200,
    ) -> list[HiringEntry]:
        if not 1 <= limit <= MAX_INDEX_ENTRIES:
            raise ValueError(f"List limit must be between 1 and {MAX_INDEX_ENTRIES}")
        with self._connect() as db:
            rows = db.execute("SELECT payload_json FROM hiring_entries ORDER BY name COLLATE NOCASE").fetchall()
        needle, industry_n, region_n = query.strip().casefold(), industry.strip().casefold(), region.strip().casefold()
        result: list[HiringEntry] = []
        for row in rows:
            entry = HiringEntry.model_validate_json(row["payload_json"])
            if signal and entry.signal != signal:
                continue
            if industry_n and industry_n not in (entry.industry or "").casefold():
                continue
            if region_n and region_n not in (entry.locations or "").casefold():
                continue
            if needle:
                searchable = " ".join([entry.name, entry.industry or "", *entry.sample_titles]).casefold()
                if needle not in searchable:
                    continue
            result.append(entry)
            if len(result) >= limit:
                break
        return result

    def facets(self) -> dict[str, list[str]]:
        industries = sorted(
            {entry.industry for entry in self.entries(limit=MAX_INDEX_ENTRIES) if entry.industry},
            key=str.casefold,
        )
        return {"industries": industries, "signals": ["live_openings", "directory_flag"]}
