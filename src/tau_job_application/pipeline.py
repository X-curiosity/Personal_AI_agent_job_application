"""Framework-independent, evidence-first job-readiness workflow."""

from pathlib import Path

from tau_job_application.authenticity import check_authenticity
from tau_job_application.career import score_cv, tailor_resume
from tau_job_application.matching import calculate_match
from tau_job_application.models import AnalysisResult
from tau_job_application.parsing import load_document, parse_candidate_text, parse_job_text
from tau_job_application.planning import build_project_plans, build_skill_tree
from tau_job_application.requirement_memory import RequirementMemory


def analyze_texts(
    candidate_text: str,
    job_text: str,
    *,
    links: dict[str, str] | None = None,
    job_title: str | None = None,
    company: str | None = None,
    job_url: str | None = None,
    requirement_memory: RequirementMemory | None = None,
) -> AnalysisResult:
    candidate = parse_candidate_text(candidate_text, links=links)
    job = parse_job_text(job_text, title=job_title, company=company, url=job_url, memory=requirement_memory)
    match = calculate_match(candidate, job)
    skill_tree = build_skill_tree(match)
    return AnalysisResult(
        candidate=candidate, job=job, match=match, skill_tree=skill_tree,
        project_plans=build_project_plans(skill_tree),
        cv_score=score_cv(candidate, job, match),
        tailored_resume=tailor_resume(candidate, job, match),
        authenticity_report=check_authenticity(candidate),
    )


def analyze_files(candidate_path: Path, job_path: Path) -> AnalysisResult:
    return analyze_texts(load_document(candidate_path), load_document(job_path))


def render_markdown(result: AnalysisResult) -> str:
    matched = [item.skill for item in result.match.requirements if item.status == "matched"]
    missing = [item.skill for item in result.match.requirements if item.status == "missing"]
    lines = [
        f"# {result.job.title} at {result.job.company}", "",
        f"Candidate: {result.candidate.name}",
        f"Role-evidence match: **{result.match.score}/100**",
        f"CV readiness: **{result.cv_score.score if result.cv_score else 'N/A'}/100**", "",
        f"Matched confirmed skills: {', '.join(matched) or 'None'}",
        f"Missing skills: {', '.join(missing) or 'None'}", "",
        "## Extracted role requirements",
    ]
    evidence = {item.id: item for item in result.job.evidence}
    for requirement in result.job.requirements:
        source = evidence[requirement.evidence_id]
        lines.extend([f"- **{requirement.skill}** — {requirement.importance}; {requirement.extraction_method}" +
                      ("; review suggested" if requirement.needs_review else ""), f"  > {source.quote}"])
    lines.extend(["", "## Gap-driven projects"])
    if result.project_plans:
        for plan in result.project_plans:
            lines.extend([f"### {plan.title}", plan.problem, "", "**Acceptance checks**"])
            lines.extend(f"- {item}" for item in plan.acceptance_tests)
    else:
        lines.append("No gap-driven project is needed for this specific role.")
    if result.tailored_resume:
        lines.extend(["", "## Truthful CV tailoring", result.tailored_resume.summary])
        for suggestion in result.tailored_resume.suggestions:
            lines.append(f"- **{suggestion.section}:** {suggestion.safe_draft}")
    if result.cv_score:
        lines.extend(["", "## Next actions"])
        lines.extend(f"- {action}" for action in result.cv_score.next_actions)
    if result.authenticity_report:
        lines.extend(["", "## Authenticity review"])
        lines.append(f"Status: **{result.authenticity_report.status}**")
        lines.append(result.authenticity_report.overall_guidance)
        for section in result.authenticity_report.rewrite_sections:
            lines.append(f"- **{section.section}:** {section.reason}")
    lines.extend(["", "> Evidence-first result. Review every extracted fact before using it in an application; the agent never submits applications or contacts people."])
    return "\n".join(lines)
