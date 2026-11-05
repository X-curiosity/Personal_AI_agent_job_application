"""SQLite storage matching startupmap.one's data model (startups + jobs)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "hired.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS startups (
    startup_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    website TEXT NOT NULL DEFAULT '',
    logo_url TEXT NOT NULL DEFAULT '',
    latitude REAL,
    longitude REAL,
    office_city TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    domain_primary TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT '',
    hiring_status TEXT NOT NULL DEFAULT '',
    team_size_min INTEGER,
    team_size_max INTEGER,
    year_founded INTEGER,
    accelerators TEXT NOT NULL DEFAULT '[]',
    last_funding_amount TEXT NOT NULL DEFAULT '',
    claimed INTEGER NOT NULL DEFAULT 0,
    why_interesting TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS jobs (
    jobs_id TEXT PRIMARY KEY,
    startup_id TEXT NOT NULL,
    job_title TEXT NOT NULL,
    job_country TEXT NOT NULL DEFAULT '',
    location_display TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT '[]',
    apply_url TEXT NOT NULL,
    scrape_method TEXT NOT NULL DEFAULT '',
    is_remote INTEGER NOT NULL DEFAULT 0,
    workplace_type TEXT,
    exp_min INTEGER,
    exp_max INTEGER,
    posted_at TEXT,
    first_seen_at TEXT NOT NULL DEFAULT '',
    visible INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(startup_id) REFERENCES startups(startup_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_startup ON jobs(startup_id);
CREATE INDEX IF NOT EXISTS idx_jobs_visible ON jobs(visible);
"""


class Store:
    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(SCHEMA)
            # lightweight migration for columns added after initial creation
            cols = {r[1] for r in con.execute("PRAGMA table_info(startups)").fetchall()}
            if "address" not in cols:
                con.execute("ALTER TABLE startups ADD COLUMN address TEXT NOT NULL DEFAULT ''")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def upsert_startup(self, row: dict) -> None:
        with self._connect() as con:
            con.execute(
                """INSERT INTO startups (startup_id, name, website, logo_url, latitude, longitude, office_city, address,
                   country, domain_primary, stage, hiring_status, team_size_min, team_size_max, year_founded,
                   accelerators, last_funding_amount, claimed, why_interesting)
                   VALUES (:startup_id, :name, :website, :logo_url, :latitude, :longitude, :office_city, :address, :country,
                   :domain_primary, :stage, :hiring_status, :team_size_min, :team_size_max, :year_founded,
                   :accelerators, :last_funding_amount, :claimed, :why_interesting)
                   ON CONFLICT(startup_id) DO UPDATE SET
                   name=excluded.name, website=excluded.website, logo_url=excluded.logo_url,
                   latitude=excluded.latitude, longitude=excluded.longitude, office_city=excluded.office_city,
                   address=excluded.address,
                   country=excluded.country, domain_primary=excluded.domain_primary, stage=excluded.stage,
                   hiring_status=excluded.hiring_status, team_size_min=excluded.team_size_min,
                   team_size_max=excluded.team_size_max, year_founded=excluded.year_founded,
                   accelerators=excluded.accelerators, last_funding_amount=excluded.last_funding_amount,
                   claimed=excluded.claimed, why_interesting=excluded.why_interesting""",
                row,
            )

    def upsert_job(self, row: dict) -> None:
        with self._connect() as con:
            con.execute(
                """INSERT INTO jobs (jobs_id, startup_id, job_title, job_country, location_display, type,
                   apply_url, scrape_method, is_remote, workplace_type, exp_min, exp_max, posted_at,
                   first_seen_at, visible, description)
                   VALUES (:jobs_id, :startup_id, :job_title, :job_country, :location_display, :type,
                   :apply_url, :scrape_method, :is_remote, :workplace_type, :exp_min, :exp_max, :posted_at,
                   :first_seen_at, :visible, :description)
                   ON CONFLICT(jobs_id) DO UPDATE SET
                   job_title=excluded.job_title, job_country=excluded.job_country,
                   location_display=excluded.location_display, type=excluded.type, apply_url=excluded.apply_url,
                   scrape_method=excluded.scrape_method, is_remote=excluded.is_remote,
                   workplace_type=excluded.workplace_type, exp_min=excluded.exp_min, exp_max=excluded.exp_max,
                   posted_at=excluded.posted_at, visible=excluded.visible, description=excluded.description""",
                row,
            )

    def mark_jobs_visible(self, startup_id: str, visible: bool) -> None:
        with self._connect() as con:
            con.execute("UPDATE jobs SET visible = ? WHERE startup_id = ?", (int(visible), startup_id))

    def all_startups(self) -> list[dict]:
        with self._connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM startups ORDER BY name").fetchall()]

    def all_jobs(self, visible_only: bool = True) -> list[dict]:
        query = "SELECT * FROM jobs" + (" WHERE visible = 1" if visible_only else "")
        with self._connect() as con:
            return [dict(r) for r in con.execute(query + " ORDER BY posted_at DESC").fetchall()]

    def counts(self) -> dict:
        with self._connect() as con:
            return {
                "startups": con.execute("SELECT COUNT(*) FROM startups").fetchone()[0],
                "jobs": con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                "jobs_visible": con.execute("SELECT COUNT(*) FROM jobs WHERE visible = 1").fetchone()[0],
            }
