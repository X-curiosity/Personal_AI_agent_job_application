"""Surface publicly-listed people (recruiters/employees) at a company.

This does NOT scrape LinkedIn. It verifies contacts from public search results
(name + role + a ``linkedin.com/in/`` profile URL + the company), which is the
same signal a candidate would see in a normal web search. Callers are expected
to supply their own search function; the public site consumes the pre-seeded
``vercel-site/data/people.json`` and can be refreshed with a provider key.
"""
from __future__ import annotations

import re

RECRUITER_KEYWORDS = (
    "recruiter", "recruiting", "talent acquisition", "talent partner", "talent",
    "sourcer", "people", "hiring", "acquisition",
)
_LINKEDIN_URL = re.compile(r"https?://(?:[a-z0-9-]+\.)*linkedin\.com/in/[A-Za-z0-9_-]+")


def is_recruiting_role(role: str) -> bool:
    value = (role or "").casefold()
    return any(keyword in value for keyword in RECRUITER_KEYWORDS)


def linkedin_url(text: str) -> str | None:
    match = _LINKEDIN_URL.search(text or "")
    return match.group(0) if match else None


def normalize_person(data: dict, company: str, *, require_recruiting: bool = True) -> dict | None:
    """Validate one search hit into a clean contact record, or None to reject.

    ``data`` is a search hit with at least ``name`` and a LinkedIn ``url``
    (or ``title``/``snippet`` text containing one). The company must appear in
    the hit's text, and (by default) the role must be a recruiting role.
    """
    name = str(data.get("name") or "").strip()
    role = str(data.get("role") or data.get("title") or "").strip()
    url = str(data.get("url") or "").strip()
    text = " ".join(str(data.get(key) or "") for key in ("title", "snippet", "note", "url"))
    if not name or len(name) > 120:
        return None
    profile = url if _LINKEDIN_URL.fullmatch(url) else linkedin_url(text)
    if not profile:
        return None
    if company.casefold() not in text.casefold():
        return None
    if require_recruiting and not is_recruiting_role(role):
        return None
    return {
        "name": name, "role": role[:160], "company": company,
        "linkedin": profile, "location": str(data.get("location") or "")[:120],
    }


def filter_people(hits: list[dict], company: str, *, require_recruiting: bool = True) -> list[dict]:
    seen: set[str] = set()
    people: list[dict] = []
    for hit in hits:
        person = normalize_person(hit, company, require_recruiting=require_recruiting)
        if not person or person["linkedin"] in seen:
            continue
        seen.add(person["linkedin"])
        people.append(person)
    return people
