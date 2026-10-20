#!/usr/bin/env python3
"""Export the public company catalogue as a static map data file."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tau_job_application.city_coordinates import (  # noqa: E402
    CITY_COORDINATES,
    COUNTRY_CENTROIDS,
    GeocodeResult,
    geocode_location,
)

STAGES = {"early", "growth", "scaleup", "big", "unknown"}
COMPANY_FIELDS = {
    "id", "name", "summary", "industry", "stage", "stageBasis", "location",
    "latitude", "longitude", "precision", "locationLabel", "source",
    "sourceUrl", "website", "hiringSignal", "observedAt",
    "country", "countryCode", "region", "logo",
}

# Country names arrive in many spellings across the three directories; the map
# groups on this normalized form. ISO codes drive flag emoji on country cards.
COUNTRY_ALIASES = {
    "usa": "United States", "united states": "United States", "united states of america": "United States",
    "u.s.a.": "United States", "u.s.": "United States", "us": "United States",
    "uk": "United Kingdom", "united kingdom": "United Kingdom", "great britain": "United Kingdom",
    "england": "United Kingdom", "uae": "United Arab Emirates",
    "korea": "South Korea", "the netherlands": "Netherlands",
}
COUNTRY_ISO = {
    "United States": "US", "United Kingdom": "GB", "China": "CN", "India": "IN", "Japan": "JP",
    "Switzerland": "CH", "Canada": "CA", "France": "FR", "Germany": "DE", "Spain": "ES",
    "Netherlands": "NL", "Taiwan": "TW", "Singapore": "SG", "Hong Kong": "HK", "Israel": "IL",
    "Sweden": "SE", "Denmark": "DK", "Finland": "FI", "Norway": "NO", "Italy": "IT",
    "Portugal": "PT", "Austria": "AT", "Czech Republic": "CZ", "Poland": "PL", "Ireland": "IE",
    "Belgium": "BE", "Luxembourg": "LU", "Australia": "AU", "New Zealand": "NZ",
    "South Korea": "KR", "United Arab Emirates": "AE", "Saudi Arabia": "SA", "Qatar": "QA",
    "Brazil": "BR", "Mexico": "MX", "Colombia": "CO", "Chile": "CL", "Argentina": "AR",
    "Peru": "PE", "Uruguay": "UY", "South Africa": "ZA", "Nigeria": "NG", "Kenya": "KE",
    "Ghana": "GH", "Morocco": "MA", "Egypt": "EG", "Indonesia": "ID", "Malaysia": "MY",
    "Thailand": "TH", "Vietnam": "VN", "Philippines": "PH", "Estonia": "EE", "Lithuania": "LT",
    "Latvia": "LV", "Romania": "RO", "Greece": "GR", "Turkey": "TR", "Iceland": "IS",
}
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}
US_STATE_NAMES = {name.casefold(): name for name in US_STATES.values()}
# Common region abbreviations seen in directory data outside the US.
REGION_ALIASES = {
    "ka": "Karnataka", "mh": "Maharashtra", "tn": "Tamil Nadu", "dl": "Delhi", "gj": "Gujarat",
    "on": "Ontario", "qc": "Quebec", "bc": "British Columbia", "ab": "Alberta",
    "nsw": "New South Wales", "vic": "Victoria", "qld": "Queensland", "wa": "Western Australia",
}
MAX_LOGO_BYTES = 262_144
LOGO_TYPES = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
    "image/vnd.microsoft.icon": ".ico", "image/x-icon": ".ico",
}


def safe_https(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    try:
        parsed = urlparse(text)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.port not in (None, 443) or re.search(r"[\x00-\x20\x7f]", text):
            return None
        # Public catalogue links need a DNS name, never an IP literal or local
        # service. No DNS resolution is performed while exporting.
        host = parsed.hostname.lower()
        if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host):
            return None
        if host.endswith((".local", ".internal", ".localhost", ".test", ".invalid")):
            return None
    except (TypeError, ValueError):
        return None
    return text


def public_id(source: str, source_key: str) -> str:
    material = f"{source}\0{source_key}".encode("utf-8")
    return "company_" + hashlib.sha256(material).hexdigest()[:20]


def classify_stage(payload: dict[str, Any]) -> tuple[str, str]:
    company_type = str(payload.get("company_type") or "").strip()
    raw = str(payload.get("funding_stage") or "").strip()
    normalized = raw.casefold()
    if company_type.casefold() == "public" or normalized == "public":
        return "big", "public company catalogue classification"
    if normalized in {"early", "pre-seed", "seed", "series a"}:
        return "early", f"catalogue funding stage: {raw}"
    if normalized in {"growth", "series b", "series c"}:
        return "growth", f"catalogue funding stage: {raw}"
    if normalized in {"scaleup", "late stage", "series d", "series e"}:
        return "scaleup", f"catalogue funding stage: {raw}"
    return "unknown", "catalogue stage unavailable or not recognized"


def _safe_geocode(location: str | None) -> GeocodeResult | None:
    """Use the first resolvable listed place; never mix city/country segments.

    Multiple offices are separated by semicolons, bullets or pipes. One pin
    cannot describe all offices, so the UI discloses this selection policy.
    """
    if location and re.search(r"[;•|]", location):
        for part in re.split(r"[;•|]", location):
            result = _safe_geocode(part.strip())
            if result:
                return result
        return None
    try:
        result = geocode_location(location)
    except Exception:
        return None
    if not result or result.precision != "city" or not location or "," not in location:
        return result
    segments = [part.strip().casefold() for part in location.replace(";", ",").split(",") if part.strip()]
    declared_country = segments[-1] if segments else ""
    if declared_country not in COUNTRY_CENTROIDS:
        return result
    # Guard the resolved city, not the first text segment: a street-address
    # first segment is never the city, while an alias like "London, Canada"
    # still downgrades because "london, canada" is not a known pair.
    exact_city_country = f"{result.label.casefold()}, {declared_country}"
    if exact_city_country not in CITY_COORDINATES:
        latitude, longitude = COUNTRY_CENTROIDS[declared_country]
        return GeocodeResult(latitude=latitude, longitude=longitude, precision="country", label=segments[-1].title())
    return result


def normalize_country(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(str(value).strip().strip(".").split())
    if not cleaned:
        return None
    return COUNTRY_ALIASES.get(cleaned.casefold(), cleaned[:1].upper() + cleaned[1:])


def split_location(location: str | None) -> tuple[str | None, str | None]:
    """Return (country, region). Region is a US state when determinable;
    elsewhere the administrative segment before the country, if there is one
    that is not itself the city. Unknown stays None rather than guessed."""

    if not location:
        return None, None
    first = re.split(r"[;\u2022|]", location)[0]
    segments = [part.strip() for part in first.split(",") if part.strip()]
    if not segments:
        return None, None
    country = normalize_country(segments[-1])
    if len(segments) < 2:
        return country, None
    region: str | None = None
    if country == "United States":
        for segment in reversed(segments[:-1]):
            token = segment.strip().upper()
            if token in US_STATES:
                region = US_STATES[token]
                break
            if segment.casefold() in US_STATE_NAMES:
                region = US_STATE_NAMES[segment.casefold()]
                break
    elif len(segments) >= 3:
        # "Lyon, Auvergne-Rhone-Alpes, France": the segment before the country
        # is regional only when it differs from the resolved city.
        candidate = segments[-2]
        if candidate and f"{candidate.casefold()}, {country.casefold()}" not in CITY_COORDINATES:
            region = REGION_ALIASES.get(candidate.casefold(), candidate)
    return country, region


def _logo_source(payload: dict[str, Any]) -> list[str]:
    """Candidate logo URLs in trust order: the directory's own logo URL, then
    the company's own site assets, then DuckDuckGo's favicon proxy as a final
    fallback. All fetches happen once at export time; visitors load the
    self-hosted copy only."""

    candidates: list[str] = []
    direct = safe_https(payload.get("logo_url"))
    if direct:
        candidates.append(direct)
    website = safe_https(payload.get("website"))
    if website:
        host = urlparse(website).hostname or ""
        bare = host[4:] if host.startswith("www.") else host
        if re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", bare):
            candidates.extend([
                f"https://{host}/apple-touch-icon.png",
                f"https://{host}/favicon.ico",
                f"https://icons.duckduckgo.com/ip3/{bare}.ico",
            ])
    return candidates


def download_logo(company_id: str, urls: list[str], logos_dir: Path) -> str | None:
    """One bounded fetch chain per company at export time; visitors then load
    the logo from this site, never from the third-party hosts."""

    for url in urls:
        request = Request(url, headers={"User-Agent": "CoApplyGPT-PublicMap/1.0 (logo snapshot)", "Accept": "image/*"})
        try:
            with urlopen(request, timeout=12) as response:  # noqa: S310 - allowlisted catalogue URLs only
                if urlparse(response.geturl()).scheme != "https":
                    continue
                content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                extension = LOGO_TYPES.get(content_type)
                if not extension:
                    continue
                data = response.read(MAX_LOGO_BYTES + 1)
        except Exception:
            continue
        if not data or len(data) > MAX_LOGO_BYTES:
            continue
        filename = f"{company_id}{extension}"
        logos_dir.mkdir(parents=True, exist_ok=True)
        (logos_dir / filename).write_bytes(data)
        return f"data/logos/{filename}"
    return None


def attach_logos(companies: list[dict[str, Any]], logos_dir: Path, *, workers: int = 8) -> int:
    jobs: list[tuple[int, str, list[str]]] = []
    for index, company in enumerate(companies):
        candidates = _logo_source(company.pop("_logo_payload", {}))
        if candidates:
            jobs.append((index, company["id"], candidates))
    count = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(download_logo, company_id, urls, logos_dir) for _, company_id, urls in jobs]
        for (index, _, _), future in zip(jobs, futures):
            path = future.result()
            if path:
                companies[index]["logo"] = path
                count += 1
    return count


def company_record(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    location = str(payload.get("locations") or payload.get("country") or "").strip() or None
    geocode = _safe_geocode(location)
    stage, stage_basis = classify_stage(payload)
    source_url = safe_https(payload.get("source_url"))
    country, region = split_location(location)
    return {
        "id": public_id(row["source"], row["source_key"]),
        "name": str(row["name"]).strip(),
        "summary": str(payload.get("summary") or "").strip() or None,
        "industry": str(payload.get("industry") or "").strip() or None,
        "stage": stage,
        "stageBasis": stage_basis,
        "location": location,
        "latitude": geocode.latitude if geocode else None,
        "longitude": geocode.longitude if geocode else None,
        "precision": geocode.precision if geocode else "unmapped",
        "locationLabel": geocode.label if geocode else (location or "Unmapped"),
        "source": row["source"],
        "sourceUrl": source_url,
        "website": safe_https(payload.get("website")),
        "hiringSignal": "directory_flag" if payload.get("hiring") is True else "unknown",
        "observedAt": row["imported_at"],
        "country": country,
        "countryCode": COUNTRY_ISO.get(country or ""),
        "region": region,
        "logo": None,  # filled by attach_logos() after all records are built
        "_logo_payload": payload,
    }


def export_catalog(db_path: Path, output_path: Path, *, exported_at: str | None = None, logos: bool = True) -> dict[str, Any]:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        rows = db.execute(
            "SELECT source, source_key, name, payload_json, imported_at "
            "FROM company_catalog ORDER BY source, source_key"
        ).fetchall()
        data = {
            "schemaVersion": 1,
            "exportedAt": exported_at or datetime.now(UTC).isoformat(),
            "companies": [company_record(row) for row in rows],
        }
        db.rollback()
    if logos:
        count = attach_logos(data["companies"], output_path.parent / "logos")
        print(f"Downloaded {count} company logos")
    for company in data["companies"]:
        company.pop("_logo_payload", None)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / ".job_assistant/assistant.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "vercel-site/data/companies.json")
    parser.add_argument("--no-logos", action="store_true", help="Skip logo downloads (offline/tests)")
    args = parser.parse_args()
    data = export_catalog(args.database, args.output, logos=not args.no_logos)
    print(f"Exported {len(data['companies'])} public companies to {args.output}")


if __name__ == "__main__":
    main()
