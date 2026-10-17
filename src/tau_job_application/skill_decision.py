"""Typed decision model for skill equivalence ("does A mean the same skill as B?").

This is a *decision model* in the Jev sense rather than a chat model: it returns a
typed, branchable answer — a probability plus a three-way verdict — instead of free
text. Two resolutions are available:

- **local** (default, always available): a deterministic, explainable scorer built
  from alias groups, token canonicalisation and sequence similarity. No network,
  no dependency, no candidate data leaving the machine.
- **jev** (opt-in, only for ambiguous pairs): TypeSafe AI's hosted decision model,
  called through :mod:`tau_job_application.jev_client` with a strict deterministic
  fallback when it is unavailable.

Both are **advisory**. The canonical evidence-coverage score in
:func:`tau_job_application.matching.calculate_match` stays deterministic and remains
the number shown as "your match"; refinements here are presented alongside it and
never replace it.
"""
from __future__ import annotations

import difflib
import re
from typing import Callable, Literal

from pydantic import BaseModel, Field

Verdict = Literal["match", "no_match", "ambiguous"]
Method = Literal["exact", "alias", "token", "fuzzy", "jev"]

# Curated equivalences that a strict normaliser cannot know. Each group is a set
# of labels that describe one capability; matching is case- and punctuation-
# insensitive because every label is canonicalised before comparison.
EQUIVALENCE_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"kubernetes", "k8s", "kube"}),
    frozenset({"javascript", "js", "ecmascript"}),
    frozenset({"typescript", "ts"}),
    frozenset({"postgresql", "postgres", "psql"}),
    frozenset({"amazon web services", "aws"}),
    frozenset({"google cloud platform", "gcp", "google cloud"}),
    frozenset({"microsoft azure", "azure"}),
    frozenset({"machine learning", "ml"}),
    frozenset({"deep learning", "dl"}),
    frozenset({"natural language processing", "nlp"}),
    frozenset({"continuous integration", "ci cd", "cicd", "ci/cd"}),
    frozenset({"unit testing", "pytest", "unit tests"}),
    frozenset({"rest", "rest apis", "rest api"}),
    frozenset({"sql", "ansi sql"}),
    frozenset({"frontend", "front end", "front-end"}),
    frozenset({"backend", "back end", "back-end"}),
    frozenset({"data visualisation", "data visualization"}),
    frozenset({"a/b testing", "ab testing", "split testing"}),
    frozenset({"mlops", "ml ops"}),
    frozenset({"user experience", "ux"}),
    frozenset({"user interface", "ui"}),
)

# Words that describe how much rather than which skill. They are dropped before
# comparison so "advanced Python" and "Python" are the same skill.
_FILLER_TOKENS = frozenset({
    "advanced", "basic", "intermediate", "expert", "strong", "solid", "good",
    "experience", "experienced", "knowledge", "familiar", "familiarity",
    "proficient", "proficiency", "skills", "skill", "with", "using", "use",
    "and", "or", "the", "a", "an", "in", "of", "to", "plus", "nice", "must",
})

# Deliberately high: this decides *equivalence*, not relevance. Anything less is
# reported as ambiguous so a human (or Jev) can settle it instead of guessing.
MATCH_THRESHOLD = 0.62
NO_MATCH_THRESHOLD = 0.42


class SkillDecision(BaseModel):
    """One typed answer: do two skill labels describe the same capability?"""

    left: str
    right: str
    probability: float = Field(ge=0, le=1)
    verdict: Verdict
    method: Method
    explanation: str


class SkillRefinement(BaseModel):
    """Advisory re-scoring of one job's requirement list against CV skills.

    ``refined_score`` mirrors the canonical weighting (required 0.8, preferred
    0.2) but is produced by the decision model. It is reported next to the
    canonical score, never in place of it.
    """

    source: Literal["local", "jev"]
    refined_score: int = Field(ge=0, le=100)
    canonical_score: int = Field(ge=0, le=100)
    decisions: tuple[SkillDecision, ...] = Field(default_factory=tuple)
    matched_skills: tuple[str, ...] = Field(default_factory=tuple)
    ambiguous_skills: tuple[str, ...] = Field(default_factory=tuple)
    changed_requirements: tuple[str, ...] = Field(default_factory=tuple)
    escalated_to_jev: int = 0


def _canonical(value: str) -> str:
    """Lowercase, strip punctuation, and drop quantity-only filler words."""

    text = re.sub(r"[^a-z0-9+#/ ]+", " ", value.casefold())
    tokens = [token for token in text.split() if token and token not in _FILLER_TOKENS]
    return " ".join(tokens)


def _tokens(value: str) -> set[str]:
    return set(_canonical(value).split())


def _group_for(value: str) -> frozenset[str] | None:
    canonical = _canonical(value)
    for group in EQUIVALENCE_GROUPS:
        if canonical in group:
            return group
    return None


def _similarity(left: str, right: str) -> tuple[float, Method, str]:
    """Deterministic similarity with an explicit, reviewable reason."""

    a, b = _canonical(left), _canonical(right)
    if not a or not b:
        return 0.0, "token", "One label has no comparable words."
    if a == b:
        return 1.0, "exact", "The labels are identical after normalisation."
    group = _group_for(left)
    if group is not None and group is _group_for(right):
        return 0.95, "alias", f"Both labels belong to the same equivalence group ({', '.join(sorted(group)[:3])})."

    tokens_a, tokens_b = set(a.split()), set(b.split())
    union = tokens_a | tokens_b
    jaccard = len(tokens_a & tokens_b) / len(union) if union else 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    # Substring evidence is graded by *where* the overlap sits. A label embedded
    # inside a longer one ("sql" in "postgresql") is strong evidence; a bare
    # prefix ("java" → "javascript", "react" → "react native") is the classic
    # false positive, so it is deliberately held below the match threshold.
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    containment = 0.0
    if shorter and shorter != longer and shorter in longer:
        if longer.startswith(shorter):
            containment = 0.55 if len(shorter) >= 5 else 0.40
        else:
            containment = 0.90

    probability = min(0.94, max(jaccard * 0.9, ratio * 0.8, containment))
    method: Method = "token" if jaccard >= ratio else "fuzzy"
    parts = [f"token overlap {jaccard:.2f}", f"text similarity {ratio:.2f}"]
    if containment:
        parts.append(f"containment {containment:.2f}")
    return round(probability, 3), method, "; ".join(parts)


def _verdict(probability: float) -> Verdict:
    if probability >= MATCH_THRESHOLD:
        return "match"
    if probability <= NO_MATCH_THRESHOLD:
        return "no_match"
    return "ambiguous"


Resolver = Callable[[str, str], float | None]


def decide_skill_match(left: str, right: str, *, resolver: Resolver | None = None) -> SkillDecision:
    """Typed decision for one pair, optionally escalating ambiguity to Jev.

    ``resolver`` is only consulted for pairs inside the ambiguous band, so an
    opted-in remote model can never override a confident local answer. A
    resolver that fails or returns ``None`` leaves the local verdict intact.
    """

    probability, method, explanation = _similarity(left, right)
    verdict = _verdict(probability)
    if verdict == "ambiguous" and resolver is not None:
        remote = resolver(left, right)
        if remote is not None:
            probability = round(max(0.0, min(1.0, float(remote))), 3)
            verdict = _verdict(probability)
            method = "jev"
            explanation = f"Jev decision model returned {probability:.2f} for this ambiguous pair."
    return SkillDecision(
        left=left, right=right, probability=probability,
        verdict=verdict, method=method, explanation=explanation,
    )


def refine_requirement_matches(
    candidate_skills: tuple[str, ...] | list[str],
    requirements: tuple | list,
    *,
    resolver: Resolver | None = None,
) -> SkillRefinement:
    """Re-score a requirement list with the decision model (advisory).

    Every requirement is paired with its best candidate skill; the verdicts are
    combined with the same 0.8 required / 0.2 preferred weighting the canonical
    score uses, so the two numbers are directly comparable.
    """

    skills = [skill for skill in candidate_skills if skill and skill.strip()]
    decisions: list[SkillDecision] = []
    matched: list[str] = []
    ambiguous: list[str] = []
    changed: list[str] = []
    escalated = 0
    required_hits = required_total = 0
    preferred_hits = preferred_total = 0

    for requirement in requirements:
        skill = getattr(requirement, "skill", "")
        if not skill:
            continue
        required = bool(getattr(requirement, "required", False))
        if getattr(requirement, "importance", "") == "uncertain":
            continue
        best = max(
            (decide_skill_match(skill, candidate, resolver=resolver) for candidate in skills),
            key=lambda decision: decision.probability,
            default=None,
        )
        if best is None:
            best = decide_skill_match(skill, "")
        decisions.append(best)
        if best.method == "jev":
            escalated += 1
        if best.verdict == "match":
            matched.append(skill)
            exact = _canonical(skill) == _canonical(best.right)
            if not exact:
                changed.append(skill)
            hit = 1
        else:
            hit = 0
            if best.verdict == "ambiguous":
                ambiguous.append(skill)
        if required:
            required_total += 1
            required_hits += hit
        else:
            preferred_total += 1
            preferred_hits += hit

    if not skills:
        # Nothing to compare against: report an honest zero rather than the
        # canonical "empty category is satisfied" shortcut.
        required_fraction = preferred_fraction = 0.0
    else:
        required_fraction = 1.0 if not required_total else required_hits / required_total
        preferred_fraction = 1.0 if not preferred_total else preferred_hits / preferred_total
    refined = round((required_fraction * 0.8 + preferred_fraction * 0.2) * 100) if (required_total or preferred_total) else 0
    return SkillRefinement(
        source="jev" if escalated else "local",
        refined_score=refined,
        canonical_score=0,
        decisions=tuple(decisions),
        matched_skills=tuple(dict.fromkeys(matched)),
        ambiguous_skills=tuple(dict.fromkeys(ambiguous)),
        changed_requirements=tuple(dict.fromkeys(changed)),
        escalated_to_jev=escalated,
    )
