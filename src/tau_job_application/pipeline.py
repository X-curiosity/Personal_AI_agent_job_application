"""The framework-independent application pipeline."""

from pathlib import Path

from tau_job_application.matching import calculate_match
from tau_job_application.models import AnalysisResult
from tau_job_application.parsing import (
    load_document,
    parse_candidate_text,
    parse_job_text,
)
from tau_job_application.planning import build_project_plans, build_skill_tree


def analyze_texts(candidate_text: str, job_text: str) -> AnalysisResult:
    candidate = parse_candidate_text(candidate_text)
    job = parse_job_text(job_text)
    match = calculate_match(candidate, job)
    skill_tree = build_skill_tree(match)
    project_plans = build_project_plans(skill_tree)
    return AnalysisResult(
        candidate=candidate,
        job=job,
        match=match,
        skill_tree=skill_tree,
        project_plans=project_plans,
    )


def analyze_files(candidate_path: Path, job_path: Path) -> AnalysisResult:
    return analyze_texts(load_document(candidate_path), load_document(job_path))


def render_markdown(result: AnalysisResult) -> str:
    matched = [
        item.skill for item in result.match.requirements if item.status == "matched"
    ]
    missing = [
        item.skill for item in result.match.requirements if item.status == "missing"
    ]
    lines = [
        f"# {result.job.title} at {result.job.company}",
        "",
        f"Candidate: {result.candidate.name}",
        f"Match score: **{result.match.score}/100**",
        "",
        f"Matched skills: {', '.join(matched) or 'None'}",
        f"Missing skills: {', '.join(missing) or 'None'}",
        "",
        "## Suggested projects",
    ]
    if not result.project_plans:
        lines.append("No gap-driven project is needed for this fixture.")
    else:
        lines.extend(f"- {plan.title}" for plan in result.project_plans)
    lines.extend(
        [
            "",
            "> Template result only. Review all evidence before using it in an application.",
        ]
    )
    return "\n".join(lines)
