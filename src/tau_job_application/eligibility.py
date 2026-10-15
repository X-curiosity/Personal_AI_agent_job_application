"""Rule-based work-eligibility checklists for cross-border applications.

This module never gives legal advice and never decides whether a user is
allowed to work somewhere. It compares the user's self-declared residency
profile with the country of a target role and produces a preparation
checklist: which pathway likely applies, which documents to gather, and which
official source to verify with. Rules are deliberately coarse and must be
confirmed against the linked official immigration authority before acting.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

EU_EEA = frozenset({
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark",
    "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Iceland",
    "Ireland", "Italy", "Latvia", "Liechtenstein", "Lithuania", "Luxembourg",
    "Malta", "Netherlands", "Norway", "Poland", "Portugal", "Romania",
    "Slovakia", "Slovenia", "Spain", "Sweden",
})
# Switzerland is not EU/EEA but participates in the EU free-movement acquis
# through bilateral agreements (AFMP); treated as one practical bloc here.
FREE_MOVEMENT_BLOC = EU_EEA | {"Switzerland"}

COUNTRY_ALIASES = {
    "uk": "United Kingdom", "great britain": "United Kingdom", "britain": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom", "wales": "United Kingdom",
    "us": "United States", "usa": "United States", "united states of america": "United States",
    "u.s.": "United States", "u.s.a.": "United States", "america": "United States",
    "holland": "Netherlands", "czech republic": "Czechia", "swiss": "Switzerland",
    "korea": "South Korea", "south korea": "South Korea",
}

KNOWN_COUNTRIES = tuple(sorted(
    FREE_MOVEMENT_BLOC
    | {"United Kingdom", "United States", "Canada", "Australia", "New Zealand",
       "Singapore", "Japan", "South Korea", "United Arab Emirates", "India",
       "Brazil", "Nigeria", "Kenya", "South Africa", "Morocco", "China",
       "Israel", "Mexico", "Turkey"},
    key=str.casefold,
))

OFFICIAL_SOURCES = {
    "United States": "https://www.uscis.gov/working-in-the-united-states",
    "United Kingdom": "https://www.gov.uk/browse/visas-immigration/work-visas",
    "Canada": "https://www.canada.ca/en/immigration-refugees-citizenship/services/work-in-canada.html",
    "Switzerland": "https://www.sem.admin.ch/sem/en/home/themen/arbeit.html",
    "Australia": "https://immi.homeaffairs.gov.au/visas/working-in-australia",
    "Singapore": "https://www.mom.gov.sg/passes-and-permits",
    "Japan": "https://www.moj.go.jp/isa/eng/",
    "United Arab Emirates": "https://u.ae/en/information-and-services/jobs/working-in-the-uae",
}
EU_IMMIGRATION_PORTAL = "https://immigration-portal.ec.europa.eu/index_en"

DISCLAIMER = (
    "This checklist is a preparation aid generated from coarse public rules, "
    "not legal advice. Immigration rules change and depend on your exact "
    "situation; always verify requirements with the linked official authority "
    "and, for high-stakes decisions, a qualified immigration professional."
)

COMMON_VISA_DOCUMENTS = (
    "Passport valid at least 6 months beyond the planned start date",
    "Signed employment contract or formal offer letter naming role, salary, and start date",
    "Degree certificates and transcripts, with certified translations if not in the local language",
    "Up-to-date CV tailored to the role",
    "Proof of funds or financial means where the visa route requires it",
    "Clean criminal-record certificate from your country of residence",
    "Passport-style photographs meeting the destination country's specification",
)

MAX_COUNTRIES_PER_PROFILE = 10
Pathway = Literal["domestic", "free_movement", "existing_permit", "sponsorship"]


def normalize_country(name: str) -> str | None:
    """Resolve a free-text country name to a known spelling, else None."""

    cleaned = " ".join(str(name).strip().split())
    if not cleaned or len(cleaned) > 100:
        return None
    alias = COUNTRY_ALIASES.get(cleaned.casefold())
    if alias:
        return alias
    for country in KNOWN_COUNTRIES:
        if country.casefold() == cleaned.casefold():
            return country
    return None


class ResidencyProfile(BaseModel):
    """Self-declared residency facts; user-provided, never inferred from a CV."""

    citizenships: tuple[str, ...] = Field(min_length=1, max_length=MAX_COUNTRIES_PER_PROFILE)
    residence_country: str = Field(min_length=1, max_length=100)
    work_permits: tuple[str, ...] = Field(default=(), max_length=MAX_COUNTRIES_PER_PROFILE)

    @field_validator("citizenships", "work_permits", mode="before")
    @classmethod
    def normalize_list(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",")]
        if not isinstance(value, (list, tuple)):
            raise ValueError("Provide a list of countries")
        cleaned: list[str] = []
        for entry in value:
            country = normalize_country(str(entry))
            if country is None:
                raise ValueError(f"Unrecognized country: {entry!r}. Use the full English country name.")
            if country not in cleaned:
                cleaned.append(country)
        return tuple(cleaned)

    @field_validator("residence_country", mode="before")
    @classmethod
    def normalize_residence(cls, value: object) -> str:
        country = normalize_country(str(value))
        if country is None:
            raise ValueError(f"Unrecognized country: {value!r}. Use the full English country name.")
        return country


class EligibilityItem(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=1_000)
    documents: tuple[str, ...] = ()
    official_source: str | None = None


class EligibilityResult(BaseModel):
    pathway: Pathway
    job_country: str
    residence_country: str
    summary: str
    items: tuple[EligibilityItem, ...]
    disclaimer: str = DISCLAIMER


def _source_for(country: str) -> str:
    if country in OFFICIAL_SOURCES:
        return OFFICIAL_SOURCES[country]
    if country in FREE_MOVEMENT_BLOC:
        return EU_IMMIGRATION_PORTAL
    return "https://www.iom.int/"  # generic fallback: international migration reference


def eligibility_checklist(profile: ResidencyProfile, job_country: str) -> EligibilityResult:
    """Build the preparation checklist for applying in ``job_country``."""

    destination = normalize_country(job_country)
    if destination is None:
        raise ValueError(f"Unrecognized country: {job_country!r}. Use the full English country name.")
    home = profile.residence_country

    if destination == home:
        if destination in profile.citizenships:
            return EligibilityResult(
                pathway="domestic", job_country=destination, residence_country=home,
                summary=f"{destination} is both your residence and citizenship country: no work authorization step is expected.",
                items=(EligibilityItem(
                    title="Standard local application",
                    detail="Employers may still ask you to confirm identity and right to work during onboarding.",
                    documents=("Passport or national ID card", "Tax / social-security number used locally"),
                    official_source=_source_for(destination),
                ),),
            )
        return EligibilityResult(
            pathway="domestic", job_country=destination, residence_country=home,
            summary=(
                f"You live in {destination} without its citizenship: be ready to prove that your "
                "residence status includes the right to work for this employer."
            ),
            items=(
                EligibilityItem(
                    title="Prove right to work as a resident",
                    detail="Check whether your residence permit is tied to one employer or job category, and when it expires. Renew early if the new role would outlast it.",
                    documents=("Current residence permit card or certificate", "Passport", "Any work-authorization annex attached to your permit"),
                    official_source=_source_for(destination),
                ),
            ),
        )

    if destination in profile.work_permits:
        return EligibilityResult(
            pathway="existing_permit", job_country=destination, residence_country=home,
            summary=f"You declared an existing work permit for {destination}: confirm it covers this new employer and role.",
            items=(
                EligibilityItem(
                    title="Verify permit scope and validity",
                    detail="Many permits are employer- or occupation-specific. Confirm the permit is still valid, transferable, and covers the new role before accepting an offer.",
                    documents=("Existing work permit or visa", "Passport", "New employment contract for the permit file"),
                    official_source=_source_for(destination),
                ),
                EligibilityItem(
                    title="Prepare supporting civil documents",
                    detail="Keep the documents used for the original application accessible; transfers and renewals often ask for them again.",
                    documents=COMMON_VISA_DOCUMENTS,
                    official_source=_source_for(destination),
                ),
            ),
        )

    if destination in FREE_MOVEMENT_BLOC and any(c in FREE_MOVEMENT_BLOC for c in profile.citizenships):
        citizenship = next(c for c in profile.citizenships if c in FREE_MOVEMENT_BLOC)
        return EligibilityResult(
            pathway="free_movement", job_country=destination, residence_country=home,
            summary=(
                f"As a {citizenship} citizen you can generally live and work in {destination} "
                "without a work visa under free-movement rules; expect registration formalities after arrival."
            ),
            items=(
                EligibilityItem(
                    title="Travel and identity",
                    detail="No work visa is expected, but border and registration offices still require valid identity documents.",
                    documents=("Valid passport or, where accepted, national ID card",),
                    official_source=_source_for(destination),
                ),
                EligibilityItem(
                    title="Register after arrival",
                    detail="Most countries require registering your residence (often within 90 days) and obtaining a tax and social-security number before or shortly after starting work.",
                    documents=(
                        "Employment contract",
                        "Proof of address in the destination country",
                        "Health-insurance coverage (e.g. European Health Insurance Card for the transition)",
                    ),
                    official_source=_source_for(destination),
                ),
                EligibilityItem(
                    title="Check regulated professions",
                    detail="Roles in medicine, law, engineering sign-off, teaching, and similar fields may require formal recognition of your qualifications before you can practise.",
                    documents=("Degree certificates and transcripts", "Certified translations where required"),
                    official_source=EU_IMMIGRATION_PORTAL,
                ),
            ),
        )

    # Sponsorship path: country-specific notes where we have them, generic otherwise.
    notes = {
        "United States": (
            "Most routes require employer sponsorship (for example the H-1B, which is lottery-based and "
            "capped). Confirm the employer sponsors visas before investing in the process."
        ),
        "United Kingdom": (
            "The common route is the Skilled Worker visa: the employer must hold a sponsor licence and "
            "issue a Certificate of Sponsorship. Check the role meets the salary and skill thresholds."
        ),
        "Canada": (
            "Many hires need an employer-supported work permit, sometimes preceded by a labour-market "
            "assessment (LMIA). Express Entry is the main permanent-residence route for skilled workers."
        ),
    }
    detail = notes.get(
        destination,
        f"{destination} generally requires a work visa or permit sponsored by the employer before you "
        "start. Confirm early whether the employer sponsors international candidates.",
    )
    return EligibilityResult(
        pathway="sponsorship", job_country=destination, residence_country=home,
        summary=(
            f"Applying from {home} to {destination} means a work-visa step: plan for employer "
            "sponsorship and start gathering documents before the interview process ends."
        ),
        items=(
            EligibilityItem(
                title="Confirm sponsorship with the employer",
                detail=detail,
                documents=("Written confirmation that the employer sponsors work visas for this role",),
                official_source=_source_for(destination),
            ),
            EligibilityItem(
                title="Gather the standard visa document set",
                detail="These are requested by most work-visa routes; the official checklist for your exact route decides.",
                documents=COMMON_VISA_DOCUMENTS,
                official_source=_source_for(destination),
            ),
            EligibilityItem(
                title="Plan the timeline",
                detail="Work-visa processing often takes weeks to months and may require applying from your country of residence. Ask the employer who files the application and who pays the fees.",
                documents=("Realistic start date agreed with the employer", "Budget for visa fees, translations, and travel"),
                official_source=_source_for(destination),
            ),
        ),
    )


class ResidencyStore:
    """One self-declared residency profile per career track."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS residency_profiles (
                    workspace_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def save(self, workspace_id: str, profile: ResidencyProfile) -> None:
        record = ResidencyProfile.model_validate(profile)
        with self._connect() as db:
            db.execute(
                """INSERT INTO residency_profiles(workspace_id,payload_json,updated_at) VALUES(?,?,?)
                   ON CONFLICT(workspace_id) DO UPDATE SET
                   payload_json=excluded.payload_json,updated_at=excluded.updated_at""",
                (workspace_id, record.model_dump_json(), datetime.now(UTC).isoformat()),
            )

    def get(self, workspace_id: str) -> ResidencyProfile | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM residency_profiles WHERE workspace_id=?", (workspace_id,)
            ).fetchone()
        return ResidencyProfile.model_validate_json(row["payload_json"]) if row else None
