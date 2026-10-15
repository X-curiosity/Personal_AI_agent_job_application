"""Local, user-managed company marks for role-market presentation.

The app never fetches or infers a logo server-side.  A candidate can associate
one public HTTPS image URL with a company, and the Streamlit view can render
that URL in the candidate's browser with a monogram fallback.  Keeping the
mapping local makes its provenance visible and lets a candidate replace or
remove a mark at any time.
"""

from __future__ import annotations

from datetime import UTC, datetime
import ipaddress
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
import unicodedata

from pydantic import BaseModel, Field, field_validator


def normalize_company_name(value: str) -> str:
    """Return a stable, display-independent key for a company name."""

    if not isinstance(value, str):
        raise ValueError("Company name must be text")
    cleaned = " ".join(unicodedata.normalize("NFKC", value).split())
    if not cleaned or len(cleaned) > 160:
        raise ValueError("Company name must be between 1 and 160 characters")
    return cleaned.casefold()


def clean_company_name(value: str) -> str:
    """Normalize whitespace while retaining a candidate-friendly display name."""

    # Run the shared validation before preserving the display spelling.
    normalize_company_name(value)
    return " ".join(unicodedata.normalize("NFKC", value).split())


def validate_public_https_logo_url(value: str | None) -> str | None:
    """Accept an optional public HTTPS image URL without contacting the URL.

    This rejects schemes that could run code, credentials embedded in a URL,
    and obvious local/private destinations.  It deliberately does not fetch or
    DNS-resolve the image: rendering is a browser concern, never a server-side
    request made by this application.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Logo URL must be a public HTTPS URL")
    cleaned = value.strip()
    if not cleaned:
        return None
    if any(character.isspace() for character in cleaned):
        raise ValueError("Logo URL must be a public HTTPS URL")
    try:
        parsed = urlsplit(cleaned)
        # Accessing .port validates malformed ports such as ``:not-a-port``.
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Logo URL must be a public HTTPS URL") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Logo URL must be a public HTTPS URL")

    host = parsed.hostname.casefold().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local")):
        raise ValueError("Logo URL must be a public HTTPS URL")
    try:
        # Literal IP addresses must be globally routable.  Domain names are
        # never resolved here, avoiding an implicit network request.
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("Logo URL must be a public HTTPS URL")
    except ValueError as exc:
        # A normal host name is fine.  Preserve deliberate validation errors
        # raised for a private IP address above.
        if str(exc) == "Logo URL must be a public HTTPS URL":
            raise

    return cleaned


class CompanyBrand(BaseModel):
    """One locally managed company mark and its transparent provenance."""

    company_name: str = Field(min_length=1, max_length=160)
    normalized_name: str = Field(min_length=1, max_length=160)
    logo_url: str | None = None
    source: str = Field(min_length=1, max_length=80)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)

    @field_validator("company_name")
    @classmethod
    def _company_name(cls, value: str) -> str:
        return clean_company_name(value)

    @field_validator("normalized_name")
    @classmethod
    def _normalized_name(cls, value: str) -> str:
        return normalize_company_name(value)

    @field_validator("logo_url")
    @classmethod
    def _logo_url(cls, value: str | None) -> str | None:
        return validate_public_https_logo_url(value)

    @field_validator("source")
    @classmethod
    def _source(cls, value: str) -> str:
        if not isinstance(value, str) or not (cleaned := " ".join(value.split())):
            raise ValueError("Brand source is required")
        if len(cleaned) > 80:
            raise ValueError("Brand source must be 80 characters or fewer")
        return cleaned

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamp(cls, value: str) -> str:
        if not isinstance(value, str) or not (cleaned := value.strip()):
            raise ValueError("Brand timestamps are required")
        return cleaned


# A deliberately small visual catalog for the three companies in the inspected
# default board registry.  These monochrome marks are served by Simple Icons'
# public CDN, whose project publishes brand icons under CC0.  They are display
# aids—not proof of affiliation—and the UI names the catalog, explains the
# browser request, and lets a candidate replace or suppress each one locally.
# We do not derive a domain from a company name or ask a logo API to guess one.
CURATED_LOGO_URLS: dict[str, str] = {
    "figma": "https://cdn.simpleicons.org/figma/000000",
    "mistral ai": "https://cdn.simpleicons.org/mistralai/000000",
    "cloudflare": "https://cdn.simpleicons.org/cloudflare/F38020",
}
CURATED_LOGO_SOURCE = "Simple Icons visual catalog"


def curated_logo_url(company_name: str) -> str | None:
    """Return an explicitly curated browser-delivered fallback URL, if available."""

    return CURATED_LOGO_URLS.get(normalize_company_name(company_name))


class CompanyBrandStore:
    """Persist candidate-managed brand mappings in the local SQLite database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS company_brand_assets (
                    normalized_name TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    logo_url TEXT,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS company_brand_assets_updated_idx
                    ON company_brand_assets(updated_at DESC, normalized_name);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _decode(row: sqlite3.Row) -> CompanyBrand:
        return CompanyBrand(
            company_name=row["company_name"],
            normalized_name=row["normalized_name"],
            logo_url=row["logo_url"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get(self, company_name: str) -> CompanyBrand | None:
        """Return the exact locally saved mapping for a company, if present."""

        key = normalize_company_name(company_name)
        with self._connect() as db:
            row = db.execute(
                """
                SELECT normalized_name, company_name, logo_url, source, created_at, updated_at
                FROM company_brand_assets
                WHERE normalized_name=?
                """,
                (key,),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def list_brands(self) -> list[CompanyBrand]:
        """List every candidate-managed mapping, most recently changed first."""

        with self._connect() as db:
            rows = db.execute(
                """
                SELECT normalized_name, company_name, logo_url, source, created_at, updated_at
                FROM company_brand_assets
                ORDER BY updated_at DESC, normalized_name
                """
            ).fetchall()
        return [self._decode(row) for row in rows]

    def upsert(
        self,
        company_name: str,
        logo_url: str | None,
        *,
        source: str = "candidate-provided",
    ) -> CompanyBrand:
        """Create or replace a company mapping while preserving its first-save time.

        ``logo_url=None`` is intentional: it records a local choice to use the
        monogram fallback, rather than silently falling through to a curated
        mapping that may be added later.
        """

        display_name = clean_company_name(company_name)
        key = normalize_company_name(display_name)
        checked_url = validate_public_https_logo_url(logo_url)
        checked_source = CompanyBrand.model_validate(
            {
                "company_name": display_name,
                "normalized_name": key,
                "logo_url": checked_url,
                "source": source,
                "created_at": "validation",
                "updated_at": "validation",
            }
        ).source
        now = self._now()
        with self._connect() as db:
            existing = db.execute(
                "SELECT created_at FROM company_brand_assets WHERE normalized_name=?",
                (key,),
            ).fetchone()
            if existing is None:
                db.execute(
                    """
                    INSERT INTO company_brand_assets
                        (normalized_name, company_name, logo_url, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (key, display_name, checked_url, checked_source, now, now),
                )
                created_at = now
            else:
                db.execute(
                    """
                    UPDATE company_brand_assets
                    SET company_name=?, logo_url=?, source=?, updated_at=?
                    WHERE normalized_name=?
                    """,
                    (display_name, checked_url, checked_source, now, key),
                )
                created_at = existing["created_at"]
        return CompanyBrand(
            company_name=display_name,
            normalized_name=key,
            logo_url=checked_url,
            source=checked_source,
            created_at=created_at,
            updated_at=now,
        )

    def delete(self, company_name: str) -> bool:
        """Delete a local mapping and return whether a record was removed."""

        key = normalize_company_name(company_name)
        with self._connect() as db:
            deleted = db.execute(
                "DELETE FROM company_brand_assets WHERE normalized_name=?", (key,)
            ).rowcount
        return bool(deleted)

    def logo_for(self, company_name: str) -> str | None:
        """Resolve the local choice first, then an explicitly verified fallback."""

        saved = self.get(company_name)
        if saved is not None:
            return saved.logo_url
        return curated_logo_url(company_name)
