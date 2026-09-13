"""Typed, evidence-first contracts for the job-readiness assistant."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RequirementStatus(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"
    UNKNOWN = "unknown"


class EvidenceItem(BaseModel):
    """A fact with a traceable source. It is not a claim the agent may invent."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    location: str = Field(min_length=1)
    confirmed: bool = False
    url: str | None = None


class ProfileLinks(BaseModel):
    github: str | None = None
    portfolio: str | None = None
    linkedin: str | None = None
    x: str | None = None


class CandidateProfile(BaseModel):
    name: str = Field(min_length=1)
    headline: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience_summary: str | None = None
    links: ProfileLinks = Field(default_factory=ProfileLinks)
    raw_cv: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)


class JobRequirement(BaseModel):
    skill: str = Field(min_length=1)
    required: bool = True
    evidence_id: str
    importance: Literal["required", "preferred", "uncertain"] = "required"
    confidence: float = Field(default=1.0, ge=0, le=1)
    extraction_method: Literal["explicit", "context", "phrase", "learned", "reviewed"] = "explicit"
    needs_review: bool = False

    @model_validator(mode="before")
    @classmethod
    def legacy_importance(cls, value):
        if isinstance(value, dict) and "importance" not in value:
            return {**value, "importance": "required" if value.get("required", True) else "preferred"}
        return value


class JobPosting(BaseModel):
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    location: str | None = None
    url: str | None = None
    description: str | None = None
    requirements: list[JobRequirement]
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_at_least_one_skill(self) -> "JobPosting":
        if not self.requirements:
            raise ValueError("A job needs at least one required or preferred skill")
        return self


class RequirementMatch(BaseModel):
    skill: str
    required: bool
    status: RequirementStatus
    job_evidence_id: str
    candidate_evidence_ids: list[str] = Field(default_factory=list)


class MatchResult(BaseModel):
    score: int = Field(ge=0, le=100)
    required_score: float = Field(ge=0, le=1)
    preferred_score: float = Field(ge=0, le=1)
    requirements: list[RequirementMatch]


class ScoreComponent(BaseModel):
    name: str
    score: int = Field(ge=0, le=100)
    weight: int = Field(ge=0, le=100)
    explanation: str


class CVScore(BaseModel):
    """A transparent document-readiness score, not a prediction of hiring."""

    score: int = Field(ge=0, le=100)
    components: list[ScoreComponent]
    missing_sections: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class LearningResource(BaseModel):
    title: str
    kind: Literal["book", "course", "documentation", "practice"]
    url: str | None = None
    note: str


class SkillNode(BaseModel):
    skill: str
    priority: Literal["high", "medium", "low"]
    reason: str
    prerequisites: list[str] = Field(default_factory=list)
    completion_evidence: str
    resources: list[LearningResource] = Field(default_factory=list)


class ProjectPlan(BaseModel):
    title: str
    problem: str
    skills_practised: list[str]
    milestones: list[str]
    deliverables: list[str]
    acceptance_tests: list[str]
    estimated_hours: int = Field(gt=0)
    readme_outline: list[str] = Field(default_factory=list)


class ResumeSuggestion(BaseModel):
    section: str
    recommendation: str
    evidence_ids: list[str] = Field(default_factory=list)
    safe_draft: str


class TailoredResume(BaseModel):
    target_title: str
    summary: str
    relevant_skills: list[str]
    suggestions: list[ResumeSuggestion]
    safety_note: str


class GenericPhraseHit(BaseModel):
    phrase: str
    location: str
    suggestion: str


class UnsupportedClaim(BaseModel):
    claim: str
    section: str
    reason: str
    suggested_fix: str


class WeakMetric(BaseModel):
    text: str
    section: str
    issue: str


class RewriteSection(BaseModel):
    section: str
    reason: str
    candidate_action: str


class AuthenticityReport(BaseModel):
    status: Literal["ready", "needs_review", "blocked"]
    generic_phrases: list[GenericPhraseHit] = Field(default_factory=list)
    unsupported_claims: list[UnsupportedClaim] = Field(default_factory=list)
    weak_metrics: list[WeakMetric] = Field(default_factory=list)
    rewrite_sections: list[RewriteSection] = Field(default_factory=list)
    ai_disclosure_note: str | None = None
    overall_guidance: str


class ContactLead(BaseModel):
    name: str
    role: str
    profile_url: str | None = None
    public_email: str | None = None
    evidence: str
    confidence: Literal["verified", "needs_review"] = "needs_review"


class ContactResearchPlan(BaseModel):
    company: str
    target_roles: list[str]
    search_queries: list[str]
    leads: list[ContactLead] = Field(default_factory=list)
    email_pattern: str | None = None
    safety_note: str


class InterviewQuestion(BaseModel):
    id: str
    category: Literal["technical", "behavioral", "project", "motivation"]
    question: str
    what_good_evidence_looks_like: list[str]


class InterviewFeedback(BaseModel):
    question_id: str
    strengths: list[str]
    missing: list[str]
    follow_up: str
    score: int = Field(ge=0, le=100)


class AnalysisResult(BaseModel):
    candidate: CandidateProfile
    job: JobPosting
    match: MatchResult
    skill_tree: list[SkillNode]
    project_plans: list[ProjectPlan]
    cv_score: CVScore | None = None
    tailored_resume: TailoredResume | None = None
    authenticity_report: AuthenticityReport | None = None
