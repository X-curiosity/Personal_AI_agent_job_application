#!/usr/bin/env python3
"""Recover missing company logos from declared official public sources only."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
import io
import ipaddress
import json
from pathlib import Path
import socket
import sqlite3
import time
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError, URLError
from urllib.robotparser import RobotFileParser

from PIL import Image, UnidentifiedImageError

try:
    from scripts.export_public_map import MAX_LOGO_BYTES, public_id, safe_https
except ModuleNotFoundError:  # direct `python scripts/recover_official_logos.py`
    from export_public_map import MAX_LOGO_BYTES, public_id, safe_https

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "CoApplyGPT-OfficialLogoRecovery/1.0"
MAX_HTML_BYTES = 1_048_576
IMAGE_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif", "ICO": ".ico"}


class RateLimited(RuntimeError):
    pass


class UnsafeRedirect(RuntimeError):
    pass


def is_public_destination(url: str, resolver=socket.getaddrinfo) -> bool:
    checked = safe_https(url)
    if not checked:
        return False
    host = urlparse(checked).hostname or ""
    try:
        addresses = {item[4][0] for item in resolver(host, 443, type=socket.SOCK_STREAM)}
    except OSError:
        return False
    if not addresses:
        return False
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            return False
    return True


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        target = urljoin(req.full_url, newurl)
        if not is_public_destination(target):
            raise UnsafeRedirect(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


class AssetParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.assets: list[tuple[str, str]] = []
        self._json_ld = False
        self.json_ld: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "link":
            rel = values.get("rel", "").casefold()
            href = values.get("href")
            if href and any(token in rel for token in ("icon", "apple-touch-icon")):
                self.assets.append(("declared_icon", urljoin(self.base_url, href)))
        if tag.casefold() == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            content = values.get("content")
            if content and key in {"og:logo", "twitter:image"}:
                self.assets.append((key, urljoin(self.base_url, content)))
        if tag.casefold() == "script" and "ld+json" in values.get("type", "").casefold():
            self._json_ld = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script":
            self._json_ld = False

    def handle_data(self, data: str) -> None:
        if self._json_ld:
            self.json_ld.append(data)


def structured_logo_candidates(parser: AssetParser) -> list[tuple[str, str]]:
    candidates = list(parser.assets)
    for raw in parser.json_ld:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                logo = item.get("logo")
                if isinstance(logo, str):
                    candidates.insert(0, ("jsonld_logo", urljoin(parser.base_url, logo)))
                elif isinstance(logo, dict) and isinstance(logo.get("url"), str):
                    candidates.insert(0, ("jsonld_logo", urljoin(parser.base_url, logo["url"])))
                graph = item.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
    seen: set[str] = set()
    return [(kind, url) for kind, url in candidates if not (url in seen or seen.add(url))]


def validate_image(data: bytes) -> tuple[str, int, int] | None:
    if not data or len(data) > MAX_LOGO_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            extension = IMAGE_EXTENSIONS.get(image.format or "")
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    if not extension or width < 16 or height < 16 or width * height > 16_000_000:
        return None
    return extension, width, height


def load_sources(database: Path) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        specs = [
            ("company_catalog", "source, source_key, payload_json", None),
            ("yc_directory", "slug, payload_json", "YC directory"),
            ("atlas_companies", "slug, payload_json", "Global Capital Atlas"),
            ("startupmap_companies", "slug, payload_json", "StartupMap"),
        ]
        for table, columns, fixed_source in specs:
            try:
                rows = db.execute(f"SELECT {columns} FROM {table}").fetchall()
            except sqlite3.OperationalError:
                continue
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                source = fixed_source or row["source"]
                key = row["slug"] if "slug" in row.keys() else row["source_key"]
                sources[public_id(source, key)] = payload if isinstance(payload, dict) else {}
    return sources


class Fetcher:
    def __init__(self, delay: float = 0.35) -> None:
        self.opener = build_opener(SafeRedirectHandler())
        self.delay = delay
        self.last_fetch: dict[str, float] = {}
        self.robots: dict[str, RobotFileParser] = {}

    def _wait(self, host: str) -> None:
        wait = self.delay - (time.monotonic() - self.last_fetch.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self.last_fetch[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"https://{parsed.netloc}"
        if origin not in self.robots:
            robot = RobotFileParser()
            robot.set_url(origin + "/robots.txt")
            try:
                self._wait(parsed.hostname or "")
                robot.read()
            except Exception:
                robot = RobotFileParser()
                robot.parse([])
            self.robots[origin] = robot
        return self.robots[origin].can_fetch(USER_AGENT, url)

    def get(self, url: str, limit: int, accept: str) -> tuple[bytes, str]:
        if not is_public_destination(url) or not self.allowed(url):
            raise ValueError("unsafe_or_disallowed")
        host = urlparse(url).hostname or ""
        self._wait(host)
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        try:
            with self.opener.open(request, timeout=10) as response:
                final_url = response.geturl()
                if not is_public_destination(final_url):
                    raise UnsafeRedirect(final_url)
                data = response.read(limit + 1)
        except HTTPError as error:
            if error.code == 429:
                raise RateLimited(url) from error
            raise
        if len(data) > limit:
            raise ValueError("too_large")
        return data, final_url


def recover(database: Path, catalogue: Path, logos_dir: Path, report_path: Path, *, limit: int | None = None, delay: float = 0.35, directory_only: bool = False) -> dict[str, Any]:
    data = json.loads(catalogue.read_text(encoding="utf-8"))
    companies = data["companies"]
    sources = load_sources(database)
    fetcher = Fetcher(delay)
    before = sum(bool(company.get("logo")) for company in companies)
    recovered: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    stopped_on_429 = False

    missing = [company for company in companies if not company.get("logo")]
    if limit is not None:
        missing = missing[:limit]
    for company in missing:
        payload = sources.get(company["id"], {})
        website = safe_https(payload.get("website")) or safe_https(company.get("website"))
        directory_logo = safe_https(payload.get("logo_url") or payload.get("small_logo_thumb_url"))
        candidates: list[tuple[str, str]] = []
        if directory_logo:
            candidates.append(("public_directory_logo", directory_logo))
        if website and not directory_only:
            try:
                html, final = fetcher.get(website, MAX_HTML_BYTES, "text/html,application/xhtml+xml")
                parser = AssetParser(final)
                parser.feed(html.decode("utf-8", errors="replace"))
                candidates.extend(structured_logo_candidates(parser))
            except RateLimited:
                stopped_on_429 = True
                unresolved.append({"id": company["id"], "name": company["name"], "category": "rate_limited", "website": website})
                break
            except Exception:
                pass
        result = None
        for kind, url in candidates:
            try:
                image, final = fetcher.get(url, MAX_LOGO_BYTES, "image/*")
                valid = validate_image(image)
            except RateLimited:
                stopped_on_429 = True
                break
            except Exception:
                continue
            if not valid:
                continue
            extension, width, height = valid
            filename = f"{company['id']}{extension}"
            logos_dir.mkdir(parents=True, exist_ok=True)
            (logos_dir / filename).write_bytes(image)
            company["logo"] = f"data/logos/{filename}"
            result = {"id": company["id"], "name": company["name"], "source": kind, "assetUrl": final, "website": website, "file": company["logo"], "bytes": len(image), "width": width, "height": height}
            recovered.append(result)
            break
        if stopped_on_429:
            if not result and not any(item["id"] == company["id"] for item in unresolved):
                unresolved.append({"id": company["id"], "name": company["name"], "category": "rate_limited", "website": website})
            break
        if not result:
            category = "no_official_website" if not website else ("no_declared_logo_asset" if not candidates else "declared_assets_failed_validation")
            unresolved.append({"id": company["id"], "name": company["name"], "category": category, "website": website})

    catalogue.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after = sum(bool(company.get("logo")) for company in companies)
    report = {
        "generatedAt": datetime.now(UTC).isoformat(), "before": before, "after": after,
        "recoveredCount": len(recovered), "unresolvedCount": len(companies) - after,
        "stoppedOn429": stopped_on_429, "recovered": recovered,
        "unresolvedCategories": dict(Counter(item["category"] for item in unresolved)),
        "unresolved": unresolved,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / ".job_assistant/assistant.sqlite")
    parser.add_argument("--catalogue", type=Path, default=ROOT / "vercel-site/data/companies.json")
    parser.add_argument("--logos-dir", type=Path, default=ROOT / "vercel-site/data/logos")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/official-logo-recovery-report.json")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--directory-only", action="store_true", help="Use only logo URLs already published by public directories")
    args = parser.parse_args()
    report = recover(args.database, args.catalogue, args.logos_dir, args.report, limit=args.limit, delay=args.delay, directory_only=args.directory_only)
    print(f"Official logos: {report['before']} -> {report['after']} (+{report['recoveredCount']}); unresolved {report['unresolvedCount']}")
    print(f"Unresolved categories: {report['unresolvedCategories']}")
    if report["stoppedOn429"]:
        print("Stopped on HTTP 429")


if __name__ == "__main__":
    main()
