"""Evidence-bounded career artifacts: CV diagnostics, tailoring, contacts, and signals."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from tau_job_application.matching import normalize_skill
from tau_job_application.models import (
    CVScore, CandidateProfile, ContactLead, ContactResearchPlan, JobPosting,
    MatchResult, ResumeSuggestion, ScoreComponent, TailoredResume,
)


def score_cv(candidate: CandidateProfile, job: JobPosting, match: MatchResult) -> CVScore:
    """Score the quality/readiness of the supplied material, never the person."""
    raw = candidate.raw_cv or ""
    has_contact = bool(re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://|linkedin\.com", raw, re.I))
    has_experience = bool(candidate.experience_summary or re.search(r"\b(experience|education|project|worked|built|developed)\b", raw, re.I))
    has_impact = bool(re.search(r"\b\d+(?:[.,]\d+)?[%+x]?\b|reduced|increased|improved|saved", raw, re.I))
    components = [
        ScoreComponent(name="Target-role evidence", score=match.score, weight=55,
            explanation="Coverage of explicitly confirmed skills in this job description."),
        ScoreComponent(name="CV structure", score=100 if candidate.headline and candidate.skills and has_experience else 45, weight=20,
            explanation="Headline, relevant skills, and experience/project evidence are present."),
        ScoreComponent(name="Contact and portfolio", score=100 if has_contact or candidate.links.github or candidate.links.portfolio else 35, weight=10,
            explanation="A recruiter can verify a way to contact you or review work."),
        ScoreComponent(name="Outcome evidence", score=100 if has_impact else 35, weight=15,
            explanation="Quantified outcomes or observable project results make claims reviewable."),
    ]
    score = round(sum(component.score * component.weight for component in components) / 100)
    missing = []
    if not has_contact and not (candidate.links.github or candidate.links.portfolio):
        missing.append("contact details or a verified portfolio link")
    if not has_experience:
        missing.append("experience or project section")
    if not has_impact:
        missing.append("observable outcomes (metrics, tests, demo, users, or before/after result)")
    actions = [
        "Confirm extracted skills and remove any that you cannot evidence.",
        "Place the most relevant confirmed skills near the top of the CV.",
    ]
    if missing:
        actions.append("Add: " + "; ".join(missing) + ".")
    if match.score < 90:
        actions.append("Use the skill/project plan to close gaps; do not claim planned work as completed.")
    return CVScore(score=score, components=components, missing_sections=missing, next_actions=actions)


def tailor_resume(candidate: CandidateProfile, job: JobPosting, match: MatchResult) -> TailoredResume:
    matched = [item.skill for item in match.requirements if item.status == "matched"]
    evidence_ids = [item.id for item in candidate.evidence if item.confirmed]
    suggestions = [
        ResumeSuggestion(
            section="Headline / summary",
            recommendation="Name the target direction and only skills evidenced in your CV.",
            evidence_ids=evidence_ids,
            safe_draft=_summary(candidate, job, matched),
        ),
        ResumeSuggestion(
            section="Skills",
            recommendation="Group role-relevant, confirmed skills first; preserve the rest only if useful.",
            evidence_ids=[f"candidate-skill-{_slug(skill)}" for skill in matched],
            safe_draft="Relevant confirmed skills: " + (", ".join(matched) if matched else "[confirm relevant skills]"),
        ),
        ResumeSuggestion(
            section="Experience and projects",
            recommendation="Rewrite existing bullets with action, context, and observable outcome. Add no new projects, employers, metrics, or technologies.",
            evidence_ids=evidence_ids,
            safe_draft="For each existing bullet: [action] + [system/problem] + [verified outcome or test].",
        ),
    ]
    return TailoredResume(
        target_title=job.title,
        summary=_summary(candidate, job, matched),
        relevant_skills=matched,
        suggestions=suggestions,
        safety_note="These are editing suggestions, not a finished CV. Keep only statements supported by your supplied evidence; planned learning is not work experience.",
    )


def contact_research_plan(company: str, title: str, leads: list[ContactLead] | None = None, observed_email_pattern: str | None = None) -> ContactResearchPlan:
    """Plan human-reviewed, public research; never scrape social networks or invent mail."""
    safe_company = company.strip() or "target company"
    return ContactResearchPlan(
        company=safe_company,
        target_roles=["Hiring manager", "Team lead", "Recruiter", "Founder/CEO (small company)"],
        search_queries=[
            f'site:linkedin.com/in "{safe_company}" "{title}"',
            f'site:{_company_domain_hint(safe_company)} careers team "{title}"',
            f'"{safe_company}" "{title}" hiring manager',
        ],
        leads=leads or [],
        email_pattern=observed_email_pattern or None,
        safety_note=(
            "Use this as a manual research checklist. LinkedIn and X profiles are not scraped or automated. "
            "Only store public, user-reviewed contacts. An observed company email pattern is not proof of an individual's address: do not generate, guess, or send email."
        ),
    )


def parse_contact_leads(text: str) -> list[ContactLead]:
    """Parse user-reviewed lines: Name | Role | Public profile URL | Public email (optional)."""
    leads = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        url = parts[2] if len(parts) > 2 and _is_web_url(parts[2]) else None
        email = parts[3] if len(parts) > 3 and _is_email(parts[3]) else None
        leads.append(ContactLead(name=parts[0], role=parts[1], profile_url=url, public_email=email,
            evidence="User-entered public contact; review before outreach.", confidence="verified" if url or email else "needs_review"))
    return leads


def _summary(candidate: CandidateProfile, job: JobPosting, skills: list[str]) -> str:
    direction = candidate.headline or "Candidate"
    if skills:
        return f"{direction}. Applying for {job.title}; confirmed relevant skills: {', '.join(skills)}."
    return f"{direction}. Applying for {job.title}; confirm role-relevant evidence before adding skills."


def _company_domain_hint(company: str) -> str:
    return re.sub(r"[^a-z0-9]", "", company.casefold()) + ".com"


def _is_web_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


def _is_email(value: str) -> bool:
    return bool(re.fullmatch(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
