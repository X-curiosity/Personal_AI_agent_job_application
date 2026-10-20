"""Guided match onboarding: role areas → experience → work style → stage → industry.

The flow follows the seeker-join pattern reverse-engineered from startupmap.one
(see docs/STARTUPMAP_RE_NOTES.md), generalized from startups-only to every
company type in the local data: early startups, growth and scale-ups, and big
established companies. Everything is deterministic and local — no profile fact
leaves the machine, and a match is an honest filter over stored public facts,
never a prediction of hiring likelihood.
"""
from __future__ import annotations

from datetime import UTC, datetime
import re
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

STEPS: tuple[str, ...] = ("roles", "experience", "work", "stage", "industry")

ROLE_AREAS: dict[str, str] = {
    "Engineering": "Building the product: code, hardware and infrastructure.",
    "Data & AI": "Machine learning, data engineering and analysis.",
    "Product": "Deciding what gets built and why.",
    "Design": "How the product looks, feels and works.",
    "Sales": "Finding and closing customers.",
    "Marketing": "Getting the right people to notice the product.",
    "Customer Success": "Keeping customers happy after they buy.",
    "Operations": "Making the company run: process, strategy, special projects.",
    "Finance": "Money in, money out, and the numbers behind it.",
    "People & HR": "Hiring and looking after the team.",
    "Legal": "Contracts, compliance and privacy.",
    "Research": "Advancing the science behind the product.",
    "Founding / Generalist": "Early hires who wear many hats, in any function.",
    "Internship": "Internships and working-student roles.",
}

EXPERIENCE_LEVELS: tuple[tuple[str, str, str], ...] = (
    ("lt1", "Just getting started", "under 1 year"),
    ("1_3", "Early career", "1–3 years"),
    ("3_5", "Experienced", "3–5 years"),
    ("5_10", "Senior", "5–10 years"),
    ("10_plus", "Seasoned", "10+ years"),
)
EXPERIENCE_IDS = {level for level, _, _ in EXPERIENCE_LEVELS}

WORK_STYLES: tuple[str, ...] = ("remote", "hybrid", "onsite")

LOCATION_MODES: tuple[tuple[str, str], ...] = (
    ("anywhere", "Anywhere"),
    ("country", "My country only"),
    ("cities", "Specific cities"),
)
LOCATION_MODE_IDS = {mode for mode, _ in LOCATION_MODES}

STAGE_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("early", "Early startup", "Small teams; you shape everything"),
    ("growth", "Growth startup", "The product works; now it scales"),
    ("scaleup", "Scale-up", "Bigger teams, clearer roles"),
    ("big", "Big company", "Public or large established companies"),
)
STAGE_GROUP_IDS = {group for group, _, _ in STAGE_GROUPS}

# Role areas that map onto the career portal's interest fields, so finishing
# the flow can pre-fill role pages instead of asking the same question twice.
ROLE_AREA_TO_FIELD: dict[str, str] = {
    "Engineering": "Engineering",
    "Data & AI": "Data & AI",
    "Product": "Business",
    "Design": "Design",
    "Sales": "Business",
    "Marketing": "Marketing",
    "Customer Success": "Business",
    "Operations": "Business",
    "Finance": "Finance",
    "People & HR": "Business",
    "Legal": "Law & policy",
    "Research": "Science & research",
    "Founding / Generalist": "Business",
    "Internship": "Other",
}

StageGroup = Literal["early", "growth", "scaleup", "big"]


class MatchPreferences(BaseModel):
    """One candidate's match answers; every field is candidate-entered."""

    career_track_id: str = Field(min_length=1, max_length=64)
    role_areas: tuple[str, ...] = ()
    experience: str = ""
    work_styles: tuple[str, ...] = ()
    location_mode: str = "anywhere"
    country: str = ""
    target_cities: tuple[str, ...] = ()
    stage_groups: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()
    steps_done: tuple[str, ...] = ()
    updated_at: str = ""

    def for_step(self, step: str) -> "MatchPreferences":
        """Answers as they stood at a step: later filters do not apply yet."""
        order = {name: index for index, name in enumerate(STEPS)}
        if step not in order:
            raise ValueError("Unknown onboarding step")
        keep = set(STEPS[: order[step] + 1])
        return self.model_copy(update={
            "stage_groups": self.stage_groups if "stage" in keep else (),
            "industries": self.industries if "industry" in keep else (),
            "location_mode": self.location_mode if "work" in keep else "anywhere",
            "country": self.country if "work" in keep else "",
            "target_cities": self.target_cities if "work" in keep else (),
        })


class MatchCompanyFacts(BaseModel):
    """One deduplicated company reduced to the public facts matching uses."""

    name: str
    stage_group: StageGroup
    industry: str | None = None
    locations: str | None = None
    hiring_signal: str = "directory_flag"
    source_label: str
    stage_basis: str


def _band_midpoint(band: str) -> int | None:
    cleaned = band.strip()
    if not cleaned or cleaned == "Unknown":
        return None
    numbers = [int(value) for value in re.findall(r"\d+", cleaned.replace(",", ""))]
    if not numbers:
        return None
    if "+" in cleaned and len(numbers) == 1:
        return numbers[0]
    return sum(numbers) // len(numbers)


def classify_stage(
    *,
    source: str = "",
    company_type: str = "",
    funding_stage: str = "",
    employee_band: str = "",
    team_size: int | None = None,
    market_cap: str | None = None,
) -> tuple[StageGroup, str]:
    """Bucket a company as early/growth/scaleup/big from the facts we actually hold.

    The returned basis string says exactly which fact decided it, so the UI can
    stay honest: this is an estimate from team size, funding labels or listing
    type — never verified funding-round data.
    """

    if source == "CompaniesMarketCap" or market_cap or "public" in company_type.casefold():
        return "big", "public listing"
    size = team_size if team_size is not None else _band_midpoint(employee_band)
    if size is not None:
        if size >= 1000:
            return "big", f"team ~{size}"
        if size >= 250:
            return "scaleup", f"team ~{size}"
        if size >= 50:
            return "growth", f"team ~{size}"
        return "early", f"team ~{size}"
    stage = funding_stage.casefold()
    if any(token in stage for token in ("pre-seed", "pre seed", "seed", "early")):
        return "early", f"stage label “{funding_stage}”"
    if any(token in stage for token in ("series a", "series b", "growth")):
        return "growth", f"stage label “{funding_stage}”"
    if "series" in stage or "late" in stage:
        return "scaleup", f"stage label “{funding_stage}”"
    if "ipo" in stage or "public" in stage:
        return "big", f"stage label “{funding_stage}”"
    return "early", "directory profile (no size or stage facts)"


def _mentions(locations: str | None, needle: str) -> bool:
    if not locations or not needle.strip():
        return False
    return needle.strip().casefold() in locations.casefold()


def company_matches(facts: MatchCompanyFacts, prefs: MatchPreferences) -> bool:
    """Deterministic filter: stage, industry, then location. Role area and
    experience never exclude a company — they shape role pages, not company
    eligibility, because companies hire across functions."""

    if prefs.stage_groups and facts.stage_group not in prefs.stage_groups:
        return False
    if prefs.industries and facts.industry:
        if not any(
            picked.casefold() in facts.industry.casefold() or facts.industry.casefold() in picked.casefold()
            for picked in prefs.industries
        ):
            return False
    elif prefs.industries and not facts.industry:
        return False
    if prefs.location_mode == "country" and prefs.country:
        return _mentions(facts.locations, prefs.country)
    if prefs.location_mode == "cities" and prefs.target_cities:
        return any(_mentions(facts.locations, city) for city in prefs.target_cities)
    return True


def gather_match_candidates(hiring_store, catalog_store) -> list[MatchCompanyFacts]:
    """Deduplicated hiring companies from the index and the catalogue, most
    verified signal first. Companies without a hiring signal never appear."""

    by_name: dict[str, MatchCompanyFacts] = {}
    for entry in hiring_store.entries(limit=500):
        group, basis = classify_stage(source="YC community API", team_size=entry.team_size)
        if entry.board_provider is None and entry.signal == "live_openings":
            basis = "live board check"
        facts = MatchCompanyFacts(
            name=entry.name, stage_group=group, industry=entry.industry,
            locations=entry.locations, hiring_signal=entry.signal,
            source_label=entry.source_label, stage_basis=basis,
        )
        by_name.setdefault(entry.name.casefold(), facts)
    for row in catalog_store.list_companies(hiring_only=True, limit=500):
        company = row["company"]
        key = company.name.casefold()
        if key in by_name:
            continue
        group, basis = classify_stage(
            source=company.source, company_type=company.company_type,
            funding_stage=company.funding_stage, employee_band=company.employee_band,
            market_cap=company.market_cap,
        )
        by_name[key] = MatchCompanyFacts(
            name=company.name, stage_group=group, industry=company.industry,
            locations=company.locations or company.country,
            hiring_signal="directory_flag",
            source_label=f"{company.source} (unverified)", stage_basis=basis,
        )
    return sorted(by_name.values(), key=lambda facts: (facts.hiring_signal != "live_openings", facts.name.casefold()))


def match_summary(candidates: list[MatchCompanyFacts], prefs: MatchPreferences) -> dict[str, int]:
    matched = [facts for facts in candidates if company_matches(facts, prefs)]
    return {
        "companies": len(matched),
        "live": sum(1 for facts in matched if facts.hiring_signal == "live_openings"),
    }


class MatchPreferenceStore:
    """One match-preference row per career track in the local database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS match_preferences (
                    career_track_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def load(self, career_track_id: str) -> MatchPreferences | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM match_preferences WHERE career_track_id=?", (career_track_id,)
            ).fetchone()
        return MatchPreferences.model_validate_json(row["payload_json"]) if row else None

    def save(self, prefs: MatchPreferences) -> MatchPreferences:
        record = prefs.model_copy(update={"updated_at": datetime.now(UTC).isoformat()})
        if record.location_mode not in LOCATION_MODE_IDS:
            raise ValueError("Choose a valid location mode")
        unknown_steps = set(record.steps_done) - set(STEPS)
        if unknown_steps:
            raise ValueError(f"Unknown onboarding steps: {', '.join(sorted(unknown_steps))}")
        with self._connect() as db:
            db.execute(
                """INSERT INTO match_preferences(career_track_id, payload_json, updated_at) VALUES(?,?,?)
                   ON CONFLICT(career_track_id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at""",
                (record.career_track_id, record.model_dump_json(), record.updated_at),
            )
        return record
