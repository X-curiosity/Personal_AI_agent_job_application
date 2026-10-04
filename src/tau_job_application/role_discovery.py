"""Source-agnostic, role-first discovery records and deterministic matching.

This module deliberately knows nothing about network access or a specific job
board.  Adapters can turn their public, permitted responses into
``DiscoveredOpening`` values, then this module deduplicates, ranks, filters,
and persists the local result of an explicitly requested discovery run.

``JobPosting`` remains the stricter downstream assessment contract.  A raw
opening is not discarded merely because its description does not contain a
known skill; it is converted to an assessment record only when the user opens
it for that purpose.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator, model_validator


UNKNOWN = "Unknown"


# A small, inspectable baseline for role-family expansion.  This intentionally
# avoids pretending that an opaque model has verified relevance: users see and
# can edit the generated aliases before a public board is queried.
ROLE_FAMILY_ALIASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("backend",), ("Backend Developer", "Platform Engineer", "Software Engineer")),
    (("frontend",), ("Front End Engineer", "Frontend Developer", "UI Engineer")),
    (("full stack", "fullstack"), ("Full Stack Engineer", "Software Engineer")),
    (("machine learning", "ml engineer"), ("Machine Learning Engineer", "Applied Scientist", "AI Engineer")),
    (("data engineer",), ("Analytics Engineer", "Data Platform Engineer", "ETL Engineer")),
    (("product designer",), ("UX Designer", "Product Design", "Experience Designer")),
    (("ux designer", "ui ux"), ("Product Designer", "Experience Designer", "UX Researcher")),
    (("gpu", "cuda"), ("GPU Engineer", "CUDA Engineer", "Performance Engineer", "Systems Engineer")),
    (("embedded", "firmware"), ("Embedded Software Engineer", "Firmware Engineer", "Systems Engineer")),
)


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not (cleaned := value.strip()):
        raise ValueError(f"{field_name} is required")
    return cleaned


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Text fields must be strings")
    return value.strip() or None


def _category(value: str | None) -> str:
    """Keep unknown company facts explicit rather than inventing a category."""
    cleaned = _optional_text(value)
    return UNKNOWN if cleaned is None or cleaned.casefold() == UNKNOWN.casefold() else cleaned


def _unique_text(values: Iterable[str], *, include_empty: bool = False) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Text collections must contain strings")
        cleaned = value.strip()
        if not cleaned and not include_empty:
            continue
        key = cleaned.casefold()
        if key not in seen:
            result.append(cleaned)
            seen.add(key)
    return tuple(result)


def _choice_key(value: str | None) -> str:
    # UI typography uses en dashes for ranges while source/imported company
    # facts often use a plain hyphen.  Treat those equivalent so an employee
    # band filter never silently misses a matching company.
    return _category(value).replace("–", "-").replace("—", "-").casefold()


def _match_text(value: str) -> str:
    """Normalize punctuation without losing technical tokens such as C++ or C#."""
    return re.sub(r"[^a-z0-9+#.]+", " ", value.casefold()).strip()


def canonicalize_url(url: str | None) -> str | None:
    """Return a stable HTTP(S) URL identity while retaining meaningful query data.

    Fragments and conventional UTM parameters do not identify a role, so they
    are removed.  Other query parameters are retained: some career platforms
    use them as a job identifier.
    """
    value = _optional_text(url)
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    parameters = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path,
            urlencode(sorted(parameters)),
            "",
        )
    )


def suggest_role_aliases(title: str) -> tuple[str, ...]:
    """Return a small, editable set of transparent role-family alternatives."""
    title = _required_text(title, "Role title")
    normalized = _match_text(title)
    alternatives: list[str] = []
    for triggers, aliases in ROLE_FAMILY_ALIASES:
        if any(_match_text(trigger) in normalized for trigger in triggers):
            alternatives.extend(aliases)
    return tuple(alias for alias in _unique_text(alternatives) if alias.casefold() != title.casefold())


class CompanyFacts(BaseModel):
    """Source-linked company filters, with all unverified values kept unknown."""

    name: str = Field(min_length=1)
    company_type: str = UNKNOWN
    employee_band: str = UNKNOWN
    funding_stage: str = UNKNOWN
    facts_source_url: str | None = None
    verified_at: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _required_text(value, "Company name")

    @field_validator("company_type", "employee_band", "funding_stage", mode="before")
    @classmethod
    def _validate_category(cls, value: str | None) -> str:
        return _category(value)

    @field_validator("facts_source_url", "verified_at", mode="before")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _require_provenance_for_known_facts(self) -> "CompanyFacts":
        known = any(
            value.casefold() != UNKNOWN.casefold()
            for value in (self.company_type, self.employee_band, self.funding_stage)
        )
        if known and not self.facts_source_url:
            raise ValueError("Known company metadata needs a facts_source_url; otherwise use Unknown")
        return self


class VettedCompanyBoard(BaseModel):
    """A manually approved public board target; it never implies company facts."""

    company: CompanyFacts
    source: str = Field(min_length=1)
    board_identifier: str = Field(min_length=1)
    board_url: str = Field(min_length=1)

    @field_validator("source", "board_identifier", "board_url")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _required_text(value, "Board field")


# These board handles already appear as direct public career-board links in the
# local company catalogue.  Only the fields supported by a dated primary source
# are populated; employee bands remain Unknown until an appropriate company-data
# source is connected.
DEFAULT_VETTED_COMPANY_BOARDS: tuple[VettedCompanyBoard, ...] = (
    VettedCompanyBoard(
        company=CompanyFacts(
            name="Figma",
            company_type="Public",
            funding_stage="Not applicable",
            facts_source_url="https://investor.figma.com/news-events/news/news-details/2026/Figma-Announces-Fourth-Quarter-and-Fiscal-Year-2025-Financial-Results/default.aspx",
            verified_at="2026-02-18",
        ),
        source="Greenhouse",
        board_identifier="figma",
        board_url="https://boards.greenhouse.io/figma",
    ),
    VettedCompanyBoard(
        company=CompanyFacts(
            name="Mistral AI",
            company_type="Startup",
            funding_stage="Series C+",
            facts_source_url="https://mistral.ai/news/mistral-makes-sovereign-open-weight-ai-to-frontier/",
            verified_at="2026-10-04",
        ),
        source="Ashby",
        board_identifier="mistral.ai",
        board_url="https://jobs.ashbyhq.com/mistral.ai",
    ),
    VettedCompanyBoard(
        company=CompanyFacts(
            name="Cloudflare",
            company_type="Public",
            funding_stage="Not applicable",
            facts_source_url="https://www.cloudflare.com/press/press-releases/2026/cloudflare-announces-fourth-quarter-and-fiscal-year-2025-financial-results/",
            verified_at="2026-02-10",
        ),
        source="Greenhouse",
        board_identifier="cloudflare",
        board_url="https://boards.greenhouse.io/cloudflare",
    ),
)


class OpeningProvenance(BaseModel):
    """One source observation retained when equivalent openings are merged."""

    source: str = Field(min_length=1)
    source_identifier: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        return _required_text(value, "Source")

    @field_validator("source_identifier", "external_id", "source_url", "retrieved_at", mode="before")
    @classmethod
    def _validate_optional(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @property
    def canonical_url(self) -> str | None:
        return canonicalize_url(self.source_url)

    @property
    def external_identity(self) -> tuple[str, str, str] | None:
        if not self.external_id:
            return None
        return (
            self.source.casefold(),
            (self.source_identifier or "").casefold(),
            self.external_id.casefold(),
        )


class DiscoveredOpening(BaseModel):
    """A raw public opening before evidence-oriented job assessment.

    ``location`` is intentionally the *opening's stated location only*.  The
    company record has no headquarters field, so callers cannot silently turn
    company-footprint data into a role location.
    """

    title: str = Field(min_length=1)
    company: CompanyFacts
    source: str = Field(min_length=1)
    source_identifier: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    description: str | None = None
    location: str | None = None
    retrieved_at: str | None = None
    provenance: tuple[OpeningProvenance, ...] = Field(default_factory=tuple)

    @field_validator("title", "source")
    @classmethod
    def _validate_required(cls, value: str) -> str:
        return _required_text(value, "Opening field")

    @field_validator(
        "source_identifier",
        "external_id",
        "source_url",
        "description",
        "location",
        "retrieved_at",
        mode="before",
    )
    @classmethod
    def _validate_optional(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _include_primary_provenance(self) -> "DiscoveredOpening":
        primary = OpeningProvenance(
            source=self.source,
            source_identifier=self.source_identifier,
            external_id=self.external_id,
            source_url=self.source_url,
            retrieved_at=self.retrieved_at,
        )
        combined = _unique_provenance([*self.provenance, primary])
        self.provenance = combined
        return self

    @property
    def canonical_url(self) -> str | None:
        return canonicalize_url(self.source_url)

    @property
    def external_identity(self) -> tuple[str, str, str] | None:
        if not self.external_id:
            return None
        return (
            self.source.casefold(),
            (self.source_identifier or "").casefold(),
            self.external_id.casefold(),
        )


class RoleQuery(BaseModel):
    """A user-owned role page configuration and its display filters."""

    title: str = Field(min_length=1)
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    profile_skills: tuple[str, ...] = Field(default_factory=tuple)
    company_types: tuple[str, ...] = Field(default_factory=tuple)
    employee_bands: tuple[str, ...] = Field(default_factory=tuple)
    funding_stages: tuple[str, ...] = Field(default_factory=tuple)
    sources: tuple[str, ...] = Field(default_factory=tuple)
    minimum_title_score: int = Field(default=60, ge=0, le=100)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        return _required_text(value, "Role title")

    @field_validator("aliases", "profile_skills", "sources", mode="before")
    @classmethod
    def _deduplicate_text_values(cls, values: Iterable[str] | None) -> tuple[str, ...]:
        return _unique_text(values or ())

    @field_validator("company_types", "employee_bands", "funding_stages", mode="before")
    @classmethod
    def _deduplicate_filter_values(cls, values: Iterable[str] | None) -> tuple[str, ...]:
        return _unique_text((_category(value) for value in (values or ())))

    @property
    def title_terms(self) -> tuple[str, ...]:
        return _unique_text((self.title, *self.aliases))


class RoleMatch(BaseModel):
    """A transparent result: title relevance, profile evidence, and role location."""

    opening: DiscoveredOpening
    score: int = Field(ge=0, le=100)
    title_score: int = Field(ge=0, le=100)
    profile_skill_score: int = Field(ge=0, le=100)
    matched_title_terms: tuple[str, ...] = Field(default_factory=tuple)
    matched_profile_skills: tuple[str, ...] = Field(default_factory=tuple)
    role_locations: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _use_only_the_opening_location(self) -> "RoleMatch":
        expected = opening_role_locations(self.opening)
        if self.role_locations and self.role_locations != expected:
            raise ValueError("Role locations must come only from the opening location")
        self.role_locations = expected
        return self


class SourceSnapshot(BaseModel):
    """A local audit record for one source attempted in a discovery run."""

    source: str = Field(min_length=1)
    identifier: str | None = None
    opening_count: int = Field(default=0, ge=0)
    error: str | None = None

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        return _required_text(value, "Source")

    @field_validator("identifier", "error", mode="before")
    @classmethod
    def _validate_optional(cls, value: str | None) -> str | None:
        return _optional_text(value)


class RoleDiscoveryRun(BaseModel):
    """The latest local discovery result for one career-track/workspace pair."""

    career_track_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    query: RoleQuery
    matches: tuple[RoleMatch, ...] = Field(default_factory=tuple)
    sources: tuple[SourceSnapshot, ...] = Field(default_factory=tuple)
    errors: tuple[str, ...] = Field(default_factory=tuple)
    created_at: str = Field(min_length=1)

    @field_validator("career_track_id", "workspace_id", "created_at")
    @classmethod
    def _validate_scope_text(cls, value: str) -> str:
        return _required_text(value, "Run field")

    @field_validator("errors", mode="before")
    @classmethod
    def _validate_errors(cls, values: Iterable[str] | None) -> tuple[str, ...]:
        return _unique_text(values or ())


def opening_role_locations(opening: DiscoveredOpening) -> tuple[str, ...]:
    """Return only the location stated by this opening; never a company HQ."""
    return (opening.location,) if opening.location else ()


def _title_term_score(title: str, term: str) -> int:
    normalized_title = _match_text(title)
    normalized_term = _match_text(term)
    if not normalized_title or not normalized_term:
        return 0
    if normalized_title == normalized_term:
        return 100
    title_tokens = tuple(normalized_title.split())
    term_tokens = tuple(normalized_term.split())
    if normalized_term in normalized_title:
        # The requested title appears intact inside a seniority/team-qualified title.
        return 95
    shared = set(title_tokens).intersection(term_tokens)
    if not shared:
        return 0
    coverage = len(shared) / len(set(term_tokens))
    precision = len(shared) / len(set(title_tokens))
    return round(100 * ((coverage * 0.8) + (precision * 0.2)))


def _contains_skill(text: str, skill: str) -> bool:
    normalized_skill = _match_text(skill)
    if not normalized_skill:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_skill)}(?![a-z0-9])", _match_text(text)))


def match_opening(query: RoleQuery, opening: DiscoveredOpening) -> RoleMatch:
    """Score one opening using only transparent title aliases and supplied skills."""
    scored_terms = [(term, _title_term_score(opening.title, term)) for term in query.title_terms]
    title_score = max((score for _, score in scored_terms), default=0)
    # Explain the strongest matching role term(s), rather than confusing the
    # user with a weaker overlap on a generic word such as "Engineer".
    matched_terms = tuple(term for term, score in scored_terms if score == title_score and score > 0)

    search_text = "\n".join(part for part in (opening.title, opening.description or "") if part)
    matched_skills = tuple(skill for skill in query.profile_skills if _contains_skill(search_text, skill))
    skill_score = round(100 * len(matched_skills) / len(query.profile_skills)) if query.profile_skills else 0
    score = title_score if not query.profile_skills else round((title_score * 0.7) + (skill_score * 0.3))

    return RoleMatch(
        opening=opening,
        score=score,
        title_score=title_score,
        profile_skill_score=skill_score,
        matched_title_terms=matched_terms,
        matched_profile_skills=matched_skills,
    )


def _values_match(value: str, selected: Sequence[str]) -> bool:
    return not selected or _choice_key(value) in {_choice_key(item) for item in selected}


def opening_sources(opening: DiscoveredOpening) -> tuple[str, ...]:
    """All source names that remain after a cross-board opening merge."""
    return _unique_text(provenance.source for provenance in opening.provenance)


def opening_matches_filters(opening: DiscoveredOpening, query: RoleQuery) -> bool:
    """Apply only selected filters; selecting ``Unknown`` includes unknown facts."""
    facts = opening.company
    if not _values_match(facts.company_type, query.company_types):
        return False
    if not _values_match(facts.employee_band, query.employee_bands):
        return False
    if not _values_match(facts.funding_stage, query.funding_stages):
        return False
    if query.sources:
        selected_sources = {source.casefold() for source in query.sources}
        if not any(source.casefold() in selected_sources for source in opening_sources(opening)):
            return False
    return True


def rank_openings(query: RoleQuery, openings: Iterable[DiscoveredOpening]) -> list[RoleMatch]:
    """Deduplicate, filter, and deterministically rank role-like openings."""
    matches = [
        match_opening(query, opening)
        for opening in deduplicate_openings(openings)
        if opening_matches_filters(opening, query)
    ]
    matches = [match for match in matches if match.title_score >= query.minimum_title_score]
    matches.sort(
        key=lambda match: (
            -match.score,
            -match.title_score,
            -match.profile_skill_score,
            match.opening.company.name.casefold(),
            match.opening.title.casefold(),
            match.opening.canonical_url or "",
            match.opening.external_id or "",
        )
    )
    return matches


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self._parents = list(range(size))

    def find(self, value: int) -> int:
        while self._parents[value] != value:
            self._parents[value] = self._parents[self._parents[value]]
            value = self._parents[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self._parents[max(left_root, right_root)] = min(left_root, right_root)


def _identity_keys(opening: DiscoveredOpening) -> tuple[tuple[str, ...], ...]:
    keys: list[tuple[str, ...]] = []
    for provenance in opening.provenance:
        if canonical_url := provenance.canonical_url:
            keys.append(("url", canonical_url))
        if identity := provenance.external_identity:
            keys.append(("external", *identity))
    return tuple(dict.fromkeys(keys))


def _provenance_key(item: OpeningProvenance) -> tuple[str, str, str, str, str]:
    return (
        item.source.casefold(),
        (item.source_identifier or "").casefold(),
        (item.external_id or "").casefold(),
        item.source_url or "",
        item.retrieved_at or "",
    )


def _unique_provenance(items: Iterable[OpeningProvenance]) -> tuple[OpeningProvenance, ...]:
    by_key: dict[tuple[str, str, str, str, str], OpeningProvenance] = {}
    for item in items:
        by_key[_provenance_key(item)] = item
    return tuple(by_key[key] for key in sorted(by_key))


def _company_completeness(company: CompanyFacts) -> tuple[int, str, str, str, str]:
    known_count = sum(
        value.casefold() != UNKNOWN.casefold()
        for value in (company.company_type, company.employee_band, company.funding_stage)
    )
    return (
        known_count,
        company.name.casefold(),
        company.company_type.casefold(),
        company.employee_band.casefold(),
        company.funding_stage.casefold(),
    )


def _representative_key(opening: DiscoveredOpening) -> tuple[str, str, str, str, str]:
    return (
        opening.canonical_url or "~",
        "|".join(opening.external_identity or ("~",)),
        opening.source.casefold(),
        opening.title.casefold(),
        opening.company.name.casefold(),
    )


def _merge_openings(openings: Sequence[DiscoveredOpening]) -> DiscoveredOpening:
    representative = min(openings, key=_representative_key)
    company = max((opening.company for opening in openings), key=_company_completeness)
    descriptions = [opening.description for opening in openings if opening.description]
    locations = [opening.location for opening in openings if opening.location]
    provenance = _unique_provenance(
        provenance for opening in openings for provenance in opening.provenance
    )
    return DiscoveredOpening(
        title=representative.title,
        company=company,
        source=representative.source,
        source_identifier=representative.source_identifier,
        external_id=representative.external_id,
        source_url=representative.source_url,
        description=max(descriptions, key=lambda value: (len(value), value.casefold())) if descriptions else None,
        # A merged listing may have conflicting source locations.  Select one
        # stated role location deterministically; never fill this from company data.
        location=min(locations, key=str.casefold) if locations else None,
        retrieved_at=representative.retrieved_at,
        provenance=provenance,
    )


def deduplicate_openings(openings: Iterable[DiscoveredOpening]) -> list[DiscoveredOpening]:
    """Merge equivalent jobs by canonical URL or source/board/external identity.

    The returned record carries all ``OpeningProvenance`` entries, so filtering
    by source and auditing the presentation remain possible after a merge.
    """
    values = list(openings)
    groups = _DisjointSet(len(values))
    seen: dict[tuple[str, ...], int] = {}
    for index, opening in enumerate(values):
        for key in _identity_keys(opening):
            if key in seen:
                groups.union(index, seen[key])
            else:
                seen[key] = index
    components: dict[int, list[DiscoveredOpening]] = defaultdict(list)
    for index, opening in enumerate(values):
        components[groups.find(index)].append(opening)
    merged = [_merge_openings(component) for _, component in sorted(components.items())]
    merged.sort(key=_representative_key)
    return merged


class RoleDiscoveryStore:
    """Local latest-run storage, scoped to a career track and Job Workspace."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS role_discovery_runs (
                    career_track_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    query_json TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    errors_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (career_track_id, workspace_id)
                );
                CREATE TABLE IF NOT EXISTS role_discovery_results (
                    career_track_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    match_json TEXT NOT NULL,
                    PRIMARY KEY (career_track_id, workspace_id, rank),
                    FOREIGN KEY (career_track_id, workspace_id)
                        REFERENCES role_discovery_runs(career_track_id, workspace_id)
                        ON DELETE CASCADE
                );
                """
            )

    def save_latest_run(
        self,
        *,
        career_track_id: str,
        workspace_id: str,
        query: RoleQuery,
        matches: Sequence[RoleMatch],
        sources: Sequence[SourceSnapshot] = (),
        errors: Sequence[str] = (),
    ) -> RoleDiscoveryRun:
        """Atomically replace this scope's latest result without storing credentials."""
        career_track_id = _required_text(career_track_id, "Career track ID")
        workspace_id = _required_text(workspace_id, "Workspace ID")
        normalized_matches = tuple(matches)
        normalized_sources = tuple(sources)
        normalized_errors = _unique_text(errors)
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM role_discovery_results WHERE career_track_id = ? AND workspace_id = ?",
                (career_track_id, workspace_id),
            )
            connection.execute(
                """
                INSERT INTO role_discovery_runs
                    (career_track_id, workspace_id, query_json, sources_json, errors_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(career_track_id, workspace_id) DO UPDATE SET
                    query_json=excluded.query_json,
                    sources_json=excluded.sources_json,
                    errors_json=excluded.errors_json,
                    created_at=excluded.created_at
                """,
                (
                    career_track_id,
                    workspace_id,
                    query.model_dump_json(),
                    json.dumps([source.model_dump(mode="json") for source in normalized_sources]),
                    json.dumps(list(normalized_errors)),
                    created_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO role_discovery_results (career_track_id, workspace_id, rank, match_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (career_track_id, workspace_id, rank, match.model_dump_json())
                    for rank, match in enumerate(normalized_matches)
                ],
            )
        return RoleDiscoveryRun(
            career_track_id=career_track_id,
            workspace_id=workspace_id,
            query=query,
            matches=normalized_matches,
            sources=normalized_sources,
            errors=normalized_errors,
            created_at=created_at,
        )

    def latest_run(self, *, career_track_id: str, workspace_id: str) -> RoleDiscoveryRun | None:
        career_track_id = _required_text(career_track_id, "Career track ID")
        workspace_id = _required_text(workspace_id, "Workspace ID")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT query_json, sources_json, errors_json, created_at
                FROM role_discovery_runs
                WHERE career_track_id = ? AND workspace_id = ?
                """,
                (career_track_id, workspace_id),
            ).fetchone()
            if row is None:
                return None
            result_rows = connection.execute(
                """
                SELECT match_json FROM role_discovery_results
                WHERE career_track_id = ? AND workspace_id = ?
                ORDER BY rank
                """,
                (career_track_id, workspace_id),
            ).fetchall()
        return RoleDiscoveryRun(
            career_track_id=career_track_id,
            workspace_id=workspace_id,
            query=RoleQuery.model_validate_json(row["query_json"]),
            matches=tuple(RoleMatch.model_validate_json(result["match_json"]) for result in result_rows),
            sources=tuple(SourceSnapshot.model_validate(item) for item in json.loads(row["sources_json"])),
            errors=tuple(json.loads(row["errors_json"])),
            created_at=row["created_at"],
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
