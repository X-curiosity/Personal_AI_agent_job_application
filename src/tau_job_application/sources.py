"""Opt-in, permitted public sources. No LinkedIn/X scraping or application submission."""

from __future__ import annotations

import json
from ipaddress import ip_address
import socket
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from tau_job_application.models import CandidateProfile, EvidenceItem, JobPosting
from tau_job_application.parsing import parse_job_text

USER_AGENT = "job-readiness-assistant/0.2 (personal local tool)"


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


def _get_json(url: str) -> dict | list:
    _assert_public_https_url(url)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=12) as response:  # noqa: S310 - URL is generated by allow-listed functions above
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Could not fetch permitted public source: {exc}") from exc


def _assert_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    allowed = {"api.github.com", "boards-api.greenhouse.io", "api.lever.co"}
    if parsed.scheme != "https" or (hostname not in allowed and not hostname.endswith(".recruitee.com")):
        raise ValueError("Only allow-listed HTTPS APIs can be fetched")
    for record in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        address = ip_address(record[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValueError("Source resolved to a non-public address")


def _strip_html(value: str) -> str:
    import re
    return re.sub(r"<[^>]+>", " ", value).replace("&nbsp;", " ")
