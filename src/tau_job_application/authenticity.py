"""CV authenticity review: evidence-linked, human-owned, detector-neutral.

This module never tries to evade an AI detector or optimize a fake "human score."
Instead it flags wording the candidate probably did not personally write, claims
without evidence, and claims without observable outcomes, then asks the candidate
to review and rewrite in their own words.
"""

from __future__ import annotations

import re
from typing import Literal

from tau_job_application.models import (
    AuthenticityReport,
    CandidateProfile,
    GenericPhraseHit,
    RewriteSection,
    UnsupportedClaim,
    WeakMetric,
)


GENERIC_PHRASES = (
    "results-oriented", "self-starter", "team player", "passionate about",
    "synergistic", "think outside the box", "go-getter", "hardworking",
    "detail-oriented", "proven track record", "dynamic", "motivated",
    "excellent communication skills", "strong work ethic", "fast learner",
    "highly motivated", "strategic thinker", "innovative", "driven",
    "results driven", "goal-oriented", "multitasker", "problem solver",
    "performed various", "responsible for", "assisted with",
)

ACTION_VERBS = (
    "built", "developed", "led", "managed", "created", "designed",
    "implemented", "improved", "increased", "reduced", "launched",
    "delivered", "optimized", "engineered", "automated", "analyzed",
    "deployed", "maintained", "refactored", "architected", "tested",
    "mentored", "coordinated", "negotiated", "secured", "won",
)


def check_authenticity(candidate: CandidateProfile) -> AuthenticityReport:
    """Review a CV for candidate-owned, evidence-backed, specific wording."""
    raw = candidate.raw_cv or ""
    sections = _split_sections(raw)

    generic_hits = _find_generic_phrases(sections)
    unsupported = _find_unsupported_claims(sections, candidate)
    weak_metrics = _find_weak_metrics(sections)

    rewrite_sections = _build_rewrite_sections(generic_hits, unsupported, weak_metrics)

    if unsupported:
        status = "blocked"
    elif generic_hits or weak_metrics:
        status = "needs_review"
    else:
        status = "ready"

    disclosure = (
        "This CV was drafted with AI assistance and then reviewed and confirmed by me. "
        "All facts, metrics, and projects are true and can be evidenced on request."
    ) if _looks_ai_polished(raw, generic_hits) else None

    guidance = _guidance(status, len(generic_hits), len(unsupported), len(weak_metrics))

    return AuthenticityReport(
        status=status,
        generic_phrases=generic_hits,
        unsupported_claims=unsupported,
        weak_metrics=weak_metrics,
        rewrite_sections=rewrite_sections,
        ai_disclosure_note=disclosure,
        overall_guidance=guidance,
    )


def _split_sections(text: str) -> dict[str, str]:
    """Very light section split based on common CV headers."""
    header_pattern = re.compile(r"\n([A-Z][A-Za-z\s/&-]{2,35})\s*[\n:]", re.I)
    parts = header_pattern.split(text)
    if len(parts) < 3:
        return {"CV": text}
    sections = {"Header": parts[0]}
    for index in range(1, len(parts), 2):
        title = parts[index].strip().title()
        body = parts[index + 1] if index + 1 < len(parts) else ""
        sections[title] = body
    return sections


def _find_generic_phrases(sections: dict[str, str]) -> list[GenericPhraseHit]:
    hits = []
    for title, body in sections.items():
        lower = body.casefold()
        for phrase in GENERIC_PHRASES:
            if phrase in lower:
                hits.append(GenericPhraseHit(
                    phrase=phrase,
                    location=title,
                    suggestion=f"Replace '{phrase}' with a specific example or metric from your own experience.",
                ))
    return hits


def _find_unsupported_claims(sections: dict[str, str], candidate: CandidateProfile) -> list[UnsupportedClaim]:
    """Flag claim-like sentences that do not map to specific confirmed evidence.

    The catch-all "candidate-cv-source" entry is ignored here: it only proves the
    text existed in the uploaded document, not that the claim is independently
    verifiable.
    """
    supported_quotes = {
        item.quote.lower()
        for item in candidate.evidence
        if item.confirmed and item.id != "candidate-cv-source"
    }
    supported_keywords = set()
    for quote in supported_quotes:
        supported_keywords.update(_keyword_tokens(quote))
    for skill in candidate.skills:
        supported_keywords.update(_keyword_tokens(skill))

    unsupported = []
    for title, body in sections.items():
        for sentence in _sentences(body):
            if not _is_claim_sentence(sentence):
                continue
            tokens = _keyword_tokens(sentence)
            if not tokens:
                continue
            # A claim is supported if it shares a meaningful keyword with confirmed evidence.
            if tokens & supported_keywords:
                continue
            # Skip if it contains a number/metric (likely a specific, verifiable fact).
            if re.search(r"\b\d+(?:[.,]\d+)?[%+x]?\b", sentence):
                continue
            unsupported.append(UnsupportedClaim(
                claim=sentence,
                section=title,
                reason="No confirmed evidence item or extracted skill matches this statement.",
                suggested_fix="Either remove it, add the supporting evidence to your source CV, or rewrite it as a verifiable fact you can explain.",
            ))
    return unsupported


def _find_weak_metrics(sections: dict[str, str]) -> list[WeakMetric]:
    """Flag claim-like sentences that lack a measurable outcome or test."""
    weak = []
    for title, body in sections.items():
        for sentence in _sentences(body):
            if not _is_claim_sentence(sentence):
                continue
            if _has_metric(sentence):
                continue
            weak.append(WeakMetric(
                text=sentence,
                section=title,
                issue="The statement describes activity but gives no observable result, scale, test, or comparison.",
            ))
    return weak


def _build_rewrite_sections(
    generic_hits: list[GenericPhraseHit],
    unsupported: list[UnsupportedClaim],
    weak_metrics: list[WeakMetric],
) -> list[RewriteSection]:
    sections: dict[str, list[str]] = {}
    for hit in generic_hits:
        sections.setdefault(hit.location, []).append("generic/boilerplate wording")
    for claim in unsupported:
        sections.setdefault(claim.section, []).append("unsupported claim")
    for metric in weak_metrics:
        sections.setdefault(metric.section, []).append("missing observable outcome")

    return [
        RewriteSection(
            section=title,
            reason="; ".join(sorted(set(reasons))),
            candidate_action="Rewrite this section in your own words, keeping only facts you can evidence and adding a metric or test where possible.",
        )
        for title, reasons in sections.items()
    ]


def _looks_ai_polished(text: str, generic_hits: list[GenericPhraseHit]) -> bool:
    """Heuristic hint that the user may want to disclose AI assistance."""
    word_count = len(text.split())
    return len(generic_hits) >= 2 or (word_count > 50 and len(generic_hits) >= 1)


def _guidance(status: str, generic: int, unsupported: int, weak: int) -> str:
    if status == "ready":
        return "The CV appears candidate-owned and evidence-backed. Still review every claim before submitting."
    if status == "blocked":
        return f"Blocked: {unsupported} unsupported claim(s) must be removed or evidenced before this CV can be used safely."
    parts = []
    if generic:
        parts.append(f"{generic} generic phrase(s)")
    if weak:
        parts.append(f"{weak} claim(s) without observable outcomes")
    return f"Needs review: {', '.join(parts)}. Rewrite flagged sections in your own words and add evidence or metrics."


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"[.!?\n]", text) if len(sentence.strip()) > 15]


def _is_claim_sentence(sentence: str) -> bool:
    lower = sentence.casefold()
    return any(verb in lower for verb in ACTION_VERBS) and len(sentence.split()) >= 4


def _has_metric(sentence: str) -> bool:
    return bool(re.search(r"\b\d+(?:[.,]\d+)?\s*[%+x]?\b|\b\d+\s*(users?|customers?|requests?|tests?|months?|years?|days?|hours?|gb|ms|seconds?|minutes?)\b", sentence, re.I))


def _keyword_tokens(text: str) -> set[str]:
    return {
        re.sub(r"[^a-z0-9+]", "", token.casefold())
        for token in text.split()
        if len(token) > 2
    }
