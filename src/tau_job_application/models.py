"""Typed contracts shared by the deterministic pipeline and Tau tools."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RequirementStatus(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"
    UNKNOWN = "unknown"


class EvidenceItem(BaseModel):
    """A source-backed fact used by a match or application claim."""

    id: str = Field(min_length=1)
    source: Literal["candidate", "job"]
    quote: str = Field(min_length=1)
    location: str = Field(min_length=1)
    confirmed: bool = False


class CandidateProfile(BaseModel):
    name: str = Field(min_length=1)
    headline: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience_summary: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)


class JobRequirement(BaseModel):
    skill: str = Field(min_length=1)
    required: bool = True
    evidence_id: str


class JobPosting(BaseModel):
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    location: str | None = None
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


class SkillNode(BaseModel):
    skill: str
    priority: Literal["high", "medium", "low"]
    reason: str
    prerequisites: list[str] = Field(default_factory=list)
    completion_evidence: str


class ProjectPlan(BaseModel):
    title: str
    problem: str
    skills_practised: list[str]
    milestones: list[str]
    deliverables: list[str]
    acceptance_tests: list[str]
    estimated_hours: int = Field(gt=0)


class AnalysisResult(BaseModel):
    candidate: CandidateProfile
    job: JobPosting
    match: MatchResult
    skill_tree: list[SkillNode]
    project_plans: list[ProjectPlan]
