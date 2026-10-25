"""Opt-in, permitted public sources. No LinkedIn/X scraping or application submission."""

from __future__ import annotations

import json
from html import unescape
from ipaddress import ip_address
import socket
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tau_job_application.models import CandidateProfile, EvidenceItem, JobPosting
from tau_job_application.parsing import parse_job_text

USER_AGENT = "job-readiness-assistant/0.2 (personal local tool)"
# Bounded, but tolerant of large real boards: Cloudflare's Greenhouse feed
# with full advert content is ~8 MB today.
MAX_SOURCE_BYTES = 25_000_000


class _CheckedRedirect(HTTPRedirectHandler):
    """Validate every redirect hop against the same public-API policy.

    urllib follows redirects silently; without this hook an allow-listed board
    could redirect the fetch to a local or otherwise non-public address.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = build_opener(_CheckedRedirect())


def fetch_public_board_openings(source: str, identifier: str, *, company: str) -> list[dict[str, str | None]]:
    """Fetch raw, published openings for a registered employer board.

    This is intentionally narrower than a web search: callers must supply a
    vetted employer board and the provider is restricted to a documented public
    listing API.  Raw openings are kept separate from :class:`JobPosting` so a
    valid vacancy is not discarded merely because this app cannot infer a known
    skill from its description.  A user can later choose one opening for the
    evidence-based Job Workspace flow.
    """
    label = source.strip()
    if label == "Greenhouse":
        token = _board_identifier(identifier, "Greenhouse board token")
        payload = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{quote(token)}/jobs?content=true")
        items = payload.get("jobs", []) if isinstance(payload, dict) else []
        return [_greenhouse_opening(item, token, company) for item in items if isinstance(item, dict)]
    if label == "Lever":
        site = _board_identifier(identifier, "Lever site handle")
        payload = _get_json(f"https://api.lever.co/v0/postings/{quote(site)}?mode=json")
        return [_lever_opening(item, site, company) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    if label == "Ashby":
        board = _board_identifier(identifier, "Ashby job-board name")
        payload = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{quote(board)}?includeCompensation=false")
        items = payload.get("jobs", []) if isinstance(payload, dict) else []
        return [_ashby_opening(item, board, company) for item in items if isinstance(item, dict)]
    raise ValueError("Role discovery supports registered Greenhouse, Lever, and Ashby public boards only")


def fetch_greenhouse_jobs(board_token: str) -> list[JobPosting]:
    token = board_token.strip()
    if not token.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Greenhouse board token contains unsupported characters")
    payload = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{quote(token)}/jobs?content=true")
    return _parse_many(payload.get("jobs", []), _greenhouse_job)


def fetch_lever_jobs(site: str) -> list[JobPosting]:
    site = site.strip()
    if not site.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Lever site contains unsupported characters")
    payload = _get_json(f"https://api.lever.co/v0/postings/{quote(site)}?mode=json")
    return _parse_many(payload, _lever_job)


def fetch_recruitee_jobs(company_slug: str) -> list[JobPosting]:
    """Fetch published roles from Recruitee's documented unauthenticated Careers Site API."""
    slug = company_slug.strip().casefold()
    if not slug.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Recruitee company slug contains unsupported characters")
    payload = _get_json(f"https://{slug}.recruitee.com/api/offers/")
    return _parse_many(payload.get("offers", []), _recruitee_job)


def enrich_github_profile(candidate: CandidateProfile) -> CandidateProfile:
    """Opt-in GitHub API enrichment; only public profile facts/repos are added as unconfirmed evidence."""
    url = candidate.links.github
    if not url:
        raise ValueError("Add a GitHub profile URL before enrichment")
    parsed = urlparse(url)
    if parsed.netloc.casefold() not in {"github.com", "www.github.com"}:
        raise ValueError("Only a github.com profile URL is supported")
    username = parsed.path.strip("/").split("/")[0]
    if not username:
        raise ValueError("GitHub profile URL must include a username")
    profile = _get_json(f"https://api.github.com/users/{quote(username)}")
    repos = _get_json(f"https://api.github.com/users/{quote(username)}/repos?per_page=100&sort=updated")
    languages = sorted({repo.get("language") for repo in repos if repo.get("language")})
    skill_keys = {skill.casefold() for skill in candidate.skills}
    new_skills = [language for language in languages if language.casefold() not in skill_keys]
    evidence = list(candidate.evidence)
    for language in new_skills:
        evidence.append(EvidenceItem(
            id=f"github-language-{language.casefold().replace(' ', '-')}", source="github",
            quote=f"Public GitHub repositories list primary language: {language}", location=f"github.com/{username}",
            confirmed=False, url=url,
        ))
    evidence.append(EvidenceItem(
        id="github-profile-source", source="github", quote=f"Public GitHub profile: {profile.get('public_repos', 0)} repositories.",
        location=f"github.com/{username}", confirmed=False, url=url,
    ))
    # GitHub languages are signals, not evidence of proficiency. The user must explicitly confirm them.
    return candidate.model_copy(update={"skills": candidate.skills + new_skills, "evidence": evidence})


def _parse_many(items: list[dict], parser) -> list[JobPosting]:
    """Skip postings whose text cannot support an evidence-linked skill requirement."""
    jobs = []
    for item in items:
        try:
            jobs.append(parser(item))
        except ValueError:
            continue
    return jobs


def _greenhouse_job(item: dict) -> JobPosting:
    content = _strip_html(item.get("content", ""))
    title = item.get("title") or "Untitled role"
    company = item.get("company_name") or "Company (confirm)"
    return parse_job_text(content, title=title, company=company, url=item.get("absolute_url"))


def _lever_job(item: dict) -> JobPosting:
    lists = item.get("lists", [])
    sections = [f"{section.get('text', '')}: {section.get('content', '')}" for section in lists]
    text = "\n".join([item.get("descriptionPlain", ""), *sections])
    return parse_job_text(text, title=item.get("text") or "Untitled role", company="Company (confirm)", url=item.get("hostedUrl"))


def _recruitee_job(item: dict) -> JobPosting:
    details = item.get("details", {}) or {}
    requirements = details.get("requirements", "")
    description = details.get("description", "")
    text = f"{description}\nRequired skills: {requirements}" if requirements else str(description)
    company = item.get("company_name") or "Company (confirm)"
    return parse_job_text(text, title=item.get("title") or "Untitled role", company=company, url=item.get("careers_url") or item.get("url"))


def _board_identifier(value: str, label: str) -> str:
    value = value.strip()
    # Ashby's documented job-board names may contain dots (for example,
    # ``mistral.ai``).  These remain a narrow, URL-path-safe identifier set.
    if not value.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ValueError(f"{label} contains unsupported characters")
    return value


def _greenhouse_opening(item: dict, board_token: str, company: str) -> dict[str, str | None]:
    location = item.get("location") or {}
    source_timestamp = _text_or_none(item.get("updated_at"))
    return {
        "source": "Greenhouse",
        "source_id": str(item.get("id") or item.get("absolute_url") or item.get("title") or ""),
        "board_identifier": board_token,
        "company": company.strip() or str(item.get("company_name") or "Company (confirm)"),
        "title": str(item.get("title") or "Untitled role"),
        "location": _location_name(location),
        "url": _text_or_none(item.get("absolute_url")),
        "description": _strip_html(str(item.get("content") or "")) or None,
        # Greenhouse calls this ``updated_at``.  Keep that semantics explicit
        # rather than presenting it as a publication time.
        "source_timestamp": source_timestamp,
        "source_timestamp_kind": "updated" if source_timestamp else None,
        "workplace_type": _text_or_none(item.get("workplace_type")),
        "employment_type": None,
    }


def _lever_opening(item: dict, site: str, company: str) -> dict[str, str | None]:
    categories = item.get("categories") or {}
    lists = item.get("lists") or []
    sections = [f"{section.get('text', '')}: {section.get('content', '')}" for section in lists if isinstance(section, dict)]
    description = "\n".join([str(item.get("descriptionPlain") or ""), *sections]).strip()
    source_timestamp = _text_or_none(item.get("createdAt"))
    return {
        "source": "Lever",
        "source_id": str(item.get("id") or item.get("hostedUrl") or item.get("text") or ""),
        "board_identifier": site,
        "company": company.strip() or "Company (confirm)",
        "title": str(item.get("text") or "Untitled role"),
        "location": _listing_locations(
            categories.get("location") if isinstance(categories, dict) else None,
            categories.get("allLocations") if isinstance(categories, dict) else None,
        ),
        "url": _text_or_none(item.get("hostedUrl")),
        "description": _strip_html(description) or None,
        # Lever's ``createdAt`` is a creation time, and ``commitment`` (for
        # example, Full-time) is an employment type—not a work arrangement.
        "source_timestamp": source_timestamp,
        "source_timestamp_kind": "created" if source_timestamp else None,
        "workplace_type": None,
        "employment_type": _text_or_none(categories.get("commitment") if isinstance(categories, dict) else None),
    }


def _ashby_opening(item: dict, board: str, company: str) -> dict[str, str | None]:
    """Normalize Ashby's documented public Job Postings API response."""
    address = item.get("address")
    primary_location = _address_location(address)
    listing_location = _location_name(item.get("location"))
    # Ashby can supply a locality in ``location`` while its structured address
    # contains only a country. Combine them rather than discarding the city.
    postal = address.get("postalAddress") if isinstance(address, dict) and isinstance(address.get("postalAddress"), dict) else address
    if primary_location and listing_location and isinstance(postal, dict):
        country = _text_or_none(postal.get("addressCountry"))
        locality = _text_or_none(postal.get("addressLocality"))
        region = _text_or_none(postal.get("addressRegion"))
        if country and not locality and not region:
            primary_location = f"{listing_location}, {country}"
    primary_location = primary_location or listing_location
    secondary_locations = [
        _address_location(location.get("address")) or _location_name(location)
        for location in item.get("secondaryLocations", [])
        if isinstance(location, dict)
    ]
    source_timestamp = _text_or_none(item.get("publishedAt"))
    return {
        "source": "Ashby",
        "source_id": str(item.get("id") or item.get("jobUrl") or item.get("applyUrl") or item.get("title") or ""),
        "board_identifier": board,
        "company": company.strip() or "Company (confirm)",
        "title": str(item.get("title") or "Untitled role"),
        "location": _listing_locations(primary_location, secondary_locations),
        "url": _text_or_none(item.get("jobUrl") or item.get("applyUrl")),
        "description": _strip_html(str(item.get("descriptionPlain") or item.get("descriptionHtml") or "")) or None,
        "source_timestamp": source_timestamp,
        "source_timestamp_kind": "published" if source_timestamp else None,
        "workplace_type": _text_or_none(item.get("workplaceType")),
        "employment_type": _text_or_none(item.get("employmentType")),
    }


def _location_name(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("name") or value.get("location")
    return _text_or_none(value)


def _address_location(value: object) -> str | None:
    """Format a public listing's locality and country without guessing geography."""
    if not isinstance(value, dict):
        return None
    address = value.get("postalAddress") if isinstance(value.get("postalAddress"), dict) else value
    locality = _text_or_none(address.get("addressLocality"))
    country = _text_or_none(address.get("addressCountry"))
    region = _text_or_none(address.get("addressRegion"))
    # A country makes a city unambiguous for the map.  If absent, retain a
    # source-supplied regional label rather than inventing one.
    if locality and country:
        return f"{locality}, {country}"
    if locality and region:
        return f"{locality}, {region}"
    return locality or region or country


def _listing_locations(primary: object, secondary: object = None) -> str | None:
    """Join only provider-supplied primary/secondary listing locations."""
    locations: list[str] = []
    for value in (primary, *(secondary if isinstance(secondary, list) else ())):
        if location := _location_name(value):
            if location.casefold() not in {item.casefold() for item in locations}:
                locations.append(location)
    return " • ".join(locations) or None


def _text_or_none(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _get_json(url: str) -> dict | list:
    _assert_public_https_url(url)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with _opener.open(request, timeout=12) as response:  # noqa: S310 - URL is generated by allow-listed functions above
            _assert_public_https_url(response.geturl())
            body = response.read(MAX_SOURCE_BYTES + 1)
    except Exception as exc:
        raise RuntimeError(f"Could not fetch permitted public source: {exc}") from exc
    if len(body) > MAX_SOURCE_BYTES:
        raise RuntimeError(f"Permitted public source response exceeded the {MAX_SOURCE_BYTES // 1_000_000} MB safety limit")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not fetch permitted public source: {exc}") from exc


def _assert_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    allowed = {"api.github.com", "boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com"}
    if parsed.scheme != "https" or (hostname not in allowed and not hostname.endswith(".recruitee.com")):
        raise ValueError("Only allow-listed HTTPS APIs can be fetched")
    for record in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        address = ip_address(record[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValueError("Source resolved to a non-public address")


def _strip_html(value: str) -> str:
    import re
    # Providers may entity-encode their HTML once or twice.  Decode a bounded
    # number of times before stripping tags so a selected opening never carries
    # literal ``&lt;p&gt;`` markup into a Job Workspace.
    decoded = value
    for _ in range(3):
        next_value = unescape(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return unescape(re.sub(r"<[^>]+>", " ", decoded)).replace("\xa0", " ")
