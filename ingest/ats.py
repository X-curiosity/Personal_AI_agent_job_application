"""ATS detection and feed fetchers — mirrors startupmap.one's `scrape_method` taxonomy.

Each company is classified into a `scrape_method`:
  ats:<vendor>  -> structured public feed (no scraping)
  httpx          -> generic HTML fetch + parse (requests/httpx)
  playwright     -> headless-browser for JS-heavy pages (optional)
  manual         -> hand-entered

This module implements the `ats:*` fetchers with clean public JSON APIs, and a
polite `httpx` fallback for career pages without a known feed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

USER_AGENT = "HiredJobs/1.0 (+https://co-apply-gpt-magbixavier-gmailcoms-projects.vercel.app; public job directory)"

# --- Detection -------------------------------------------------------------

# (vendor, regex) pairs. Order matters: more specific first.
ATS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"https://boards\.greenhouse\.io/[a-z0-9_-]+")),
    ("greenhouse", re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/[a-z0-9_-]+")),
    ("ashby", re.compile(r"https://jobs\.ashbyhq\.com/[a-z0-9_-]+")),
    ("ashby", re.compile(r"https://api\.ashbyhq\.com/posting-api/job-board/[a-z0-9_-]+")),
    ("lever", re.compile(r"https://jobs\.lever\.co/[a-z0-9_-]+")),
    ("lever", re.compile(r"https://api\.lever\.co/v0/postings/[a-z0-9_-]+")),
    ("workable", re.compile(r"https://apply\.workable\.com/[a-z0-9_-]+")),
    ("workable", re.compile(r"https://[a-z0-9_-]+\.workable\.com")),
    ("recruitee", re.compile(r"https://[a-z0-9_-]+\.recruitee\.com")),
    ("recruitee", re.compile(r"https://[a-z0-9_-]+\.recruitee\.com/api/offers")),
    ("teamtailor", re.compile(r"https://[a-z0-9_-]+\.teamtailor\.com")),
    ("personio", re.compile(r"https://[a-z0-9_-]+\.jobs\.personio\.(com|de)")),
    ("breezy", re.compile(r"https://[a-z0-9_-]+\.breezy\.hr")),
    ("smartrecruiters", re.compile(r"https://jobs\.smartrecruiters\.com/[a-zA-Z0-9-]+")),
    ("smartrecruiters", re.compile(r"https://api\.smartrecruiters\.com/v1/companies/[a-z0-9_-]+")),
    ("wttj", re.compile(r"https://www\.welcometothejungle\.com/[a-z]{2}/companies/[a-z0-9_-]+")),
    ("hibob", re.compile(r"https://[a-z0-9_-]+\.careers\.hibob\.com")),
    ("join", re.compile(r"https://join\.com/companies/[a-z0-9_-]+")),
    ("dover", re.compile(r"https://app\.dover\.com/[a-z0-9_-]+")),
    ("kula", re.compile(r"https://[a-z0-9_-]+\.kula\.ai")),
]


def detect_ats_from_text(text: str) -> list[dict]:
    """Return the ATS boards referenced in an HTML page, deduplicated."""
    found: dict[tuple[str, str], dict] = {}
    for vendor, pattern in ATS_PATTERNS:
        for match in pattern.finditer(text):
            url = match.group(0)
            identifier = _identifier(vendor, url)
            key = (vendor, identifier.casefold())
            if key not in found:
                found[key] = {"vendor": vendor, "identifier": identifier, "board_url": url}
    return list(found.values())


def _identifier(vendor: str, url: str) -> str:
    """Extract the board identifier from a detected ATS URL."""
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if vendor in ("greenhouse", "ashby", "lever", "smartrecruiters"):
        # boards.greenhouse.io/{id}, jobs.ashbyhq.com/{org}, jobs.lever.co/{id}
        return parts[-1] if parts else ""
    if vendor == "workable":
        host = urlparse(url).netloc
        if host.startswith("apply."):
            return parts[-1] if parts else ""
        return host.split(".")[0]
    if vendor in ("recruitee", "teamtailor", "breezy", "personio", "hibob", "kula"):
        return urlparse(url).netloc.split(".")[0]
    if vendor in ("wttj", "join", "dover"):
        return parts[-1] if parts else ""
    return path


# --- Fetchers --------------------------------------------------------------

@dataclass
class Opening:
    title: str
    url: str
    location: str
    description: str = ""
    company: str = ""
    scrape_method: str = ""
    posted_at: str | None = None
    workplace: str | None = None
    employment: str | None = None
    extra: dict = field(default_factory=dict)


def _get(url: str, *, params: dict | None = None, timeout: float = 12) -> str:
    if httpx is None:
        raise RuntimeError("httpx is required for ingestion")
    response = httpx.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.text


def _parse_json(text: str):
    return json.loads(text)


def fetch_greenhouse(board: str) -> list[Opening]:
    data = _parse_json(_get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", params={"content": "true"}))
    out = []
    for job in data.get("jobs", []):
        loc = (job.get("location") or {}).get("name", "") if isinstance(job.get("location"), dict) else (job.get("location") or "")
        out.append(Opening(
            title=job.get("title", "").strip(),
            url=job.get("absolute_url", ""),
            location=loc,
            description=_html_to_text(job.get("content", "")),
            scrape_method="ats:greenhouse",
            posted_at=job.get("updated_at"),
            employment=job.get("metadata")[0].get("value") if job.get("metadata") else None,
        ))
    return [o for o in out if o.title and o.url]


def fetch_lever(board: str) -> list[Opening]:
    data = _parse_json(_get(f"https://api.lever.co/v0/postings/{board}", params={"mode": "json"}))
    out = []
    for job in data:
        cats = job.get("categories") or {}
        loc = cats.get("location") or cats.get("allLocations") or ""
        if isinstance(loc, list):
            loc = ", ".join(loc)
        out.append(Opening(
            title=job.get("text", "").strip(),
            url=job.get("hostedUrl", ""),
            location=loc,
            description=(job.get("descriptionPlain") or "").strip(),
            scrape_method="ats:lever",
            posted_at=job.get("createdAt"),
            employment=cats.get("commitment"),
        ))
    return [o for o in out if o.title and o.url]


def fetch_ashby(org: str) -> list[Opening]:
    data = _parse_json(_get(f"https://api.ashbyhq.com/posting-api/job-board/{org}"))
    out = []
    for job in data.get("jobs", []):
        out.append(Opening(
            title=job.get("title", "").strip(),
            url=job.get("applyUrl", ""),
            location=(job.get("location") or "").strip(),
            description=_html_to_text(job.get("descriptionHtml", "") or job.get("descriptionPlain", "")),
            scrape_method="ats:ashby",
            posted_at=job.get("publishedAt"),
            employment=job.get("employmentType"),
        ))
    return [o for o in out if o.title and o.url]


def fetch_workable(shortcode: str) -> list[Opening]:
    data = _parse_json(_get(f"https://apply.workable.com/api/v1/widget/accounts/{shortcode}", params={"details": "true"}))
    out = []
    for job in data.get("jobs", []):
        city = job.get("city") or ""
        country = job.get("country") or ""
        out.append(Opening(
            title=job.get("title", "").strip(),
            url=job.get("application_url") or job.get("url") or "",
            location=", ".join(filter(None, [city, country])),
            description=_html_to_text(job.get("description", "")),
            scrape_method="ats:workable",
            posted_at=job.get("published_on") or job.get("created_at"),
            workplace="remote" if job.get("telecommuting") else None,
            employment=job.get("employment_type"),
        ))
    return [o for o in out if o.title and o.url]


def fetch_recruitee(board: str) -> list[Opening]:
    data = _parse_json(_get(f"https://{board}.recruitee.com/api/offers"))
    out = []
    for job in data.get("offers", []):
        out.append(Opening(
            title=job.get("title", "").strip(),
            url=job.get("careers_url", ""),
            location=(job.get("location") or "").strip(),
            description=_html_to_text(job.get("description", "")),
            scrape_method="ats:recruitee",
            posted_at=job.get("created_at"),
            employment=job.get("employment_type"),
        ))
    return [o for o in out if o.title and o.url]


def fetch_breezy(board: str) -> list[Opening]:
    data = _parse_json(_get(f"https://{board}.breezy.hr/json"))
    out = []
    for job in data:
        out.append(Opening(
            title=job.get("name", "").strip(),
            url=job.get("url", ""),
            location=(job.get("location") or {}).get("name", "") if isinstance(job.get("location"), dict) else (job.get("location") or ""),
            description=_html_to_text(job.get("description", "")),
            scrape_method="ats:breezy",
            posted_at=job.get("published_date"),
        ))
    return [o for o in out if o.title and o.url]


def fetch_smartrecruiters(company: str) -> list[Opening]:
    data = _parse_json(_get(f"https://api.smartrecruiters.com/v1/companies/{company}/postings", params={"limit": "100"}))
    out = []
    for job in data.get("content", []):
        loc = job.get("location") or {}
        locstr = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
        out.append(Opening(
            title=job.get("name", "").strip(),
            url=f"https://jobs.smartrecruiters.com/{job.get('company', {}).get('identifier', company)}/{job.get('id')}" if not job.get("ref") else "https://jobs.smartrecruiters.com/" + company + "/" + job.get("id"),
            location=locstr,
            description="",
            scrape_method="ats:smartrecruiters",
            posted_at=job.get("releasedDate"),
        ))
    return [o for o in out if o.title and o.url]


# Vendors with a clean public JSON/feed API.
FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workable": fetch_workable,
    "recruitee": fetch_recruitee,
    "breezy": fetch_breezy,
    "smartrecruiters": fetch_smartrecruiters,
}

# Vendors we can detect but whose feed requires HTML scraping (tagged `httpx`),
# mirroring startupmap's own split.
HTTPX_VENDORS = {"teamtailor", "personio", "wttj", "hibob", "join", "dover", "kula"}


def fetch_board(vendor: str, identifier: str) -> list[Opening]:
    if vendor in FETCHERS:
        return FETCHERS[vendor](identifier)
    raise ValueError(f"no structured fetcher for {vendor}")


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</(p|div|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def detect_company_ats(website: str, *, careers_paths: tuple[str, ...] = ("/careers", "/jobs", "/about/careers", "/company/careers", "/careers/", "/jobs/")) -> list[dict]:
    """Best-effort ATS detection from a company site + common careers paths."""
    website = website.rstrip("/")
    candidates = [website]
    candidates += [urljoin(website + "/", p.lstrip("/")) for p in careers_paths]
    results: dict[tuple[str, str], dict] = {}
    for url in dict.fromkeys(candidates):
        try:
            text = _get(url)
        except Exception:
            continue
        for found in detect_ats_from_text(text):
            results[(found["vendor"], found["identifier"].casefold())] = found
    return list(results.values())
