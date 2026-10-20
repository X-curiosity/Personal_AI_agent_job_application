#!/usr/bin/env python3
"""Export the public company catalogue as a static map data file."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any
from urllib.parse import urlparse

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
    }


def export_catalog(db_path: Path, output_path: Path, *, exported_at: str | None = None) -> dict[str, Any]:
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / ".job_assistant/assistant.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "vercel-site/data/companies.json")
    args = parser.parse_args()
    data = export_catalog(args.database, args.output)
    print(f"Exported {len(data['companies'])} public companies to {args.output}")


if __name__ == "__main__":
    main()
