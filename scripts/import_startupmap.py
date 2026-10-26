#!/usr/bin/env python3
"""Import StartupMap's public sitemap, city pages, and company JSON-LD."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

BASE = "https://startupmap.one"
SITEMAP = f"{BASE}/sitemap.xml"
USER_AGENT = "CoApplyGPT-PublicMap/1.0 (public StartupMap snapshot)"
MAX_SITEMAP_BYTES = 2_000_000
MAX_PAGE_BYTES = 1_000_000


@dataclass(frozen=True)
class CityCompany:
    slug: str
    name: str
    source_url: str
    city: str
    stage: str | None = None
    country: str | None = None
    hiring: bool = False


class CityPageParser(HTMLParser):
    def __init__(self, city: str):
        super().__init__()
        self.city = city
        self.items: list[CityCompany] = []
        self._href: str | None = None
        self._name: list[str] = []
        self._stage: list[str] = []
        self._in_stage = False
        self._in_hiring = False
        self._hiring = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and re.fullmatch(r"/startup/[A-Za-z0-9_.%-]+", values.get("href") or ""):
            self._href = values["href"]
            self._name = []
            self._stage = []
        elif self._href and tag == "span" and "stage" in (values.get("class") or "").split():
            self._in_stage = True
        elif self._href and tag == "span" and "hiring" in (values.get("class") or "").split():
            self._in_hiring = True
            self._hiring = True

    def handle_data(self, data: str) -> None:
        if self._href and not self._in_hiring:
            (self._stage if self._in_stage else self._name).append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            self._in_stage = False
            self._in_hiring = False
        if tag == "a" and self._href:
            slug = self._href.rsplit("/", 1)[-1]
            name = " ".join("".join(self._name).split())
            stage = re.sub(r"^[^A-Za-z0-9]+", "", " ".join("".join(self._stage).split())) or None
            if name:
                self.items.append(CityCompany(slug, name, urljoin(BASE, self._href), self.city, stage, hiring=self._hiring))
            self._href = None
            self._hiring = False


def fetch_public(url: str, *, max_bytes: int = MAX_PAGE_BYTES, timeout: float = 15) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "startupmap.one" or parsed.path.startswith("/api"):
        raise ValueError(f"refusing non-public StartupMap URL: {url}")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - host/path restricted above
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != "startupmap.one" or final.path.startswith("/api"):
            raise ValueError(f"refusing redirect: {response.geturl()}")
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response exceeds {max_bytes} bytes: {url}")
    return data


def parse_sitemap(data: bytes) -> list[str]:
    root = ET.fromstring(data)
    urls = []
    for node in root.findall("{*}url/{*}loc"):
        url = (node.text or "").strip()
        parsed = urlparse(url)
        if parsed.scheme == "https" and parsed.hostname == "startupmap.one" and re.fullmatch(r"/map/[^/]+", parsed.path):
            urls.append(url)
    return sorted(set(urls))


def _json_ld(html: str) -> list[dict]:
    results = []
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            results.append(value)
    return results


def parse_city_page(url: str, data: bytes) -> list[CityCompany]:
    html = data.decode("utf-8", "replace")
    city = urlparse(url).path.rsplit("/", 1)[-1].replace("-", " ").title()
    for document in _json_ld(html):
        for item in document.get("@graph", []):
            if isinstance(item, dict) and item.get("@type") == "ItemList":
                name = str(item.get("name") or "")
                if name.lower().startswith("startups in "):
                    city = name[12:].strip() or city
    parser = CityPageParser(city)
    parser.feed(html)
    country_match = re.search(r"See all startups in ([^<]+)", html)
    country = unescape(country_match.group(1)).strip().rstrip('→›» ').strip() if country_match else None
    # Country pages overlap city pages; later city records win during merge.
    return [CityCompany(item.slug, item.name, item.source_url, item.city, item.stage, country, item.hiring) for item in parser.items]


def parse_company_page(company: CityCompany, data: bytes) -> dict:
    html = data.decode("utf-8", "replace")
    organization: dict = {}
    for document in _json_ld(html):
        for item in document.get("@graph", [document]):
            if isinstance(item, dict) and item.get("@type") in {"Organization", "Corporation"} and item.get("name"):
                organization = item
                break
    if not organization:
        raise ValueError(f"company JSON-LD missing: {company.source_url}")
    address = ((organization.get("location") or {}).get("address") or {}) if isinstance(organization.get("location"), dict) else {}
    city = str(address.get("addressLocality") or company.city).strip()
    country = str(address.get("addressCountry") or company.country or "").strip() or None
    return {
        "slug": company.slug,
        "name": str(organization.get("name") or company.name).strip(),
        "city": city,
        "country": country,
        "stage": company.stage,
        "website": organization.get("url"),
        "description": organization.get("description"),
        "logo_url": organization.get("logo"),
        "source_url": company.source_url,
        "hiring": company.hiring,
    }


def import_startupmap(db_path: Path, *, fetcher: Callable[..., bytes] = fetch_public, workers: int = 2) -> tuple[int, list[str]]:
    sitemap = fetcher(SITEMAP, max_bytes=MAX_SITEMAP_BYTES)
    map_urls = parse_sitemap(sitemap)
    if not map_urls:
        raise RuntimeError("StartupMap sitemap contained no public map pages")
    errors: list[str] = []
    city_records: dict[str, CityCompany] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as pool:
        futures = {pool.submit(fetcher, url): url for url in map_urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                for item in parse_city_page(url, future.result()):
                    current = city_records.get(item.slug)
                    if current is None or (bool(item.country), item.city, item.source_url) > (bool(current.country), current.city, current.source_url):
                        city_records[item.slug] = item
            except Exception as exc:
                errors.append(f"{url}: {exc}")
    if not city_records:
        raise RuntimeError("no companies found; existing snapshot preserved")

    records: list[dict] = []
    try:
        with sqlite3.connect(db_path) as db:
            previous_details = {row[0]: json.loads(row[1]) for row in db.execute("SELECT slug, payload_json FROM startupmap_companies").fetchall()}
    except (sqlite3.OperationalError, json.JSONDecodeError):
        previous_details = {}
    for item in city_records.values():
        if item.slug in previous_details:
            cached = previous_details[item.slug]
            cached["stage"] = item.stage or cached.get("stage")
            cached["city"] = cached.get("city") or item.city
            cached["country"] = str(cached.get("country") or item.country or '').rstrip('→›» ').strip() or None
            cached["hiring"] = item.hiring
            records.append(cached)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as pool:
        futures = {pool.submit(fetcher, item.source_url): item for item in city_records.values() if item.slug not in previous_details}
        for future in as_completed(futures):
            item = futures[future]
            try:
                records.append(parse_company_page(item, future.result()))
            except Exception as exc:
                errors.append(f"{item.source_url}: {exc}")
    if not records and not city_records:
        raise RuntimeError("no company details found; existing snapshot preserved")
    # Rate limits or missing detail pages must not erase public city records.
    detailed = {record["slug"] for record in records}
    for item in city_records.values():
        if item.slug not in detailed:
            records.append({
                "slug": item.slug, "name": item.name, "city": item.city,
                "country": item.country, "stage": item.stage, "website": None,
                "description": None, "logo_url": None, "source_url": item.source_url, "hiring": item.hiring,
            })

    imported_at = datetime.now(UTC).isoformat()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            previous = db.execute("SELECT slug, name, payload_json, imported_at FROM startupmap_companies").fetchall()
        except sqlite3.OperationalError:
            previous = []
        retained = {record["slug"] for record in records}
        db.execute("DROP TABLE IF EXISTS startupmap_companies_new")
        db.execute("CREATE TABLE startupmap_companies_new (slug TEXT PRIMARY KEY, name TEXT NOT NULL, payload_json TEXT NOT NULL, imported_at TEXT NOT NULL)")
        db.executemany(
            "INSERT INTO startupmap_companies_new VALUES (?, ?, ?, ?)",
            [(r["slug"], r["name"], json.dumps(r, ensure_ascii=False, sort_keys=True), imported_at) for r in records]
            + [(slug, name, payload, imported) for slug, name, payload, imported in previous if slug not in retained],
        )
        db.execute("DROP TABLE IF EXISTS startupmap_companies_old")
        try:
            db.execute("ALTER TABLE startupmap_companies RENAME TO startupmap_companies_old")
        except sqlite3.OperationalError:
            pass
        db.execute("ALTER TABLE startupmap_companies_new RENAME TO startupmap_companies")
        db.execute("DROP TABLE IF EXISTS startupmap_companies_old")
        db.commit()
    return len(records), errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parents[1] / ".job_assistant/assistant.sqlite")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    count, errors = import_startupmap(args.database, workers=args.workers)
    print(f"Imported {count} StartupMap companies ({len(errors)} page errors)")
    for error in errors[:20]:
        print(f"warning: {error}")


if __name__ == "__main__":
    main()
