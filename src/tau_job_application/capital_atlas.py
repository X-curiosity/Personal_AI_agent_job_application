"""Global Capital Atlas import: large public and private companies ($10B+).

capital.theojaffee.net is a single-page atlas whose company records ship
inside its JavaScript bundle. The importer fetches only the fixed homepage
and the referenced page asset on the same host (redirects rejected, 8 MB
bound), tolerantly parses the embedded record array, and converts a bounded
subset into reviewed catalogue leads. A valuation entry is never proof of an
open vacancy.
"""
from __future__ import annotations

import re

from tau_job_application.company_catalog import CatalogCompany, _fetch, _optional_https

ATLAS_HOME_URL = "https://capital.theojaffee.net/"
ATLAS_HOST = "capital.theojaffee.net"
MAX_ATLAS_RECORDS = 3_000
MAX_ASSET_BYTES = 8_000_000

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


def parse_capital_atlas(js_text: str, *, min_value_billions: int = 10, limit: int = 100) -> list[CatalogCompany]:
    """Convert the embedded atlas records into bounded catalogue leads."""

    if not 1 <= limit <= 500:
        raise ValueError("Import limit must be between 1 and 500")
    if min_value_billions not in {10, 25, 50, 100, 250, 500, 1000}:
        raise ValueError("Minimum value must be one of 10, 25, 50, 100, 250, 500, 1000 (billions USD)")
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

    records = sorted(
        (record for record in records if isinstance(record, dict)),
        key=lambda record: record.get("value") if isinstance(record.get("value"), (int, float)) else 0,
        reverse=True,
    )
    imported: list[CatalogCompany] = []
    for record in records:
        if len(imported) >= limit:
            break
        if not record.get("name"):
            continue
        value = record.get("value")
        if not isinstance(value, (int, float)) or value < min_value_billions:
            continue
        name = str(record["name"]).strip()[:200]
        slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or f"rank-{record.get('rank', len(imported))}"
        industry = str(record.get("subIndustry") or record.get("industry") or "").strip()[:200] or None
        ownership = str(record.get("ownership") or "").strip() or "Unknown"
        source_url = _optional_https(record.get("source")) or ATLAS_HOME_URL
        imported.append(CatalogCompany(
            source="Global Capital Atlas", source_key=slug[:200],
            source_url=source_url, name=name,
            company_type=ownership if ownership in {"Public", "Private"} else "Other",
            website=_optional_https(record.get("website")),
            country=str(record.get("country") or "").strip()[:100] or None,
            locations=str(record.get("address") or "").strip()[:300] or None,
            industry=industry, funding_stage="Not applicable",
            ticker=str(record.get("ticker") or "").strip()[:40] or None,
            rank=int(record["rank"]) if isinstance(record.get("rank"), int) else None,
            market_cap=_format_value(value),
            summary=str(record.get("description") or "").strip()[:500] or None,
        ))
    if not imported:
        raise ValueError("No atlas companies matched the selected value threshold")
    return imported


def fetch_capital_atlas(*, min_value_billions: int = 10, limit: int = 100, fetcher=_fetch) -> list[CatalogCompany]:
    """Explicitly fetch the atlas homepage and its page asset, then parse."""

    html = fetcher(ATLAS_HOME_URL, expected_host=ATLAS_HOST).decode("utf-8", errors="replace")
    asset = _PAGE_ASSET_RE.search(html)
    if not asset:
        raise RuntimeError("The atlas homepage did not reference its page asset")
    js_text = fetcher(f"{ATLAS_HOME_URL.rstrip('/')}{asset.group(1)}", expected_host=ATLAS_HOST).decode("utf-8", errors="replace")
    return parse_capital_atlas(js_text, min_value_billions=min_value_billions, limit=limit)
