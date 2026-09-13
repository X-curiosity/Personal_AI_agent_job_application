"""Narrow Tau tools around deterministic, evidence-preserving domain functions."""

from collections.abc import Mapping

from tau_agent import AgentTool, AgentToolResult, TextContent
from tau_agent.types import JSONValue

from tau_job_application.career import contact_research_plan, tailor_resume
from tau_job_application.interview import build_interview_questions
from tau_job_application.parsing import parse_candidate_text, parse_job_text
from tau_job_application.pipeline import analyze_texts
from tau_job_application.planning import build_project_plans, build_skill_tree


def _cancelled(signal) -> AgentToolResult | None:
    if signal is not None and signal.is_cancelled():
        return AgentToolResult(content="Tool call cancelled", details={"ok": False, "cancelled": True})
    return None


def _texts(arguments: Mapping[str, JSONValue]) -> tuple[str, str]:
    return str(arguments["candidate_text"]), str(arguments["job_text"])


async def execute_analyze_job(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
    del tool_call_id, on_update
    if cancelled := _cancelled(signal):
        return cancelled
    try:
        result = analyze_texts(*_texts(arguments))
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    return _ok(f"Evidence-based role match: {result.match.score}/100; CV readiness: {result.cv_score.score if result.cv_score else 'N/A'}/100.", result.model_dump(mode="json"))


async def execute_skill_plan(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
    del tool_call_id, on_update
    if cancelled := _cancelled(signal):
        return cancelled
    try:
        result = analyze_texts(*_texts(arguments))
        payload = {"skill_tree": [node.model_dump(mode="json") for node in result.skill_tree], "project_plans": [plan.model_dump(mode="json") for plan in result.project_plans]}
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    return _ok("Created an evidence-linked learning and portfolio plan.", payload)


async def execute_tailor_resume(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
    del tool_call_id, on_update
    if cancelled := _cancelled(signal):
        return cancelled
    try:
        result = analyze_texts(*_texts(arguments))
        payload = result.tailored_resume.model_dump(mode="json") if result.tailored_resume else {}
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    return _ok("Generated evidence-bounded CV editing suggestions; no claims were invented.", payload)


async def execute_interview_questions(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
    del tool_call_id, on_update
    if cancelled := _cancelled(signal):
        return cancelled
    try:
        candidate_text, job_text = _texts(arguments)
        candidate, job = parse_candidate_text(candidate_text), parse_job_text(job_text)
        payload = {"questions": [question.model_dump(mode="json") for question in build_interview_questions(candidate, job)]}
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    return _ok("Created structured interview questions.", payload)


async def execute_contact_plan(tool_call_id: str, arguments: Mapping[str, JSONValue], signal=None, on_update=None) -> AgentToolResult:
    del tool_call_id, on_update
    if cancelled := _cancelled(signal):
        return cancelled
    try:
        company, title = str(arguments["company"]), str(arguments["job_title"])
        payload = contact_research_plan(company, title).model_dump(mode="json")
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    return _ok("Created a manual, user-reviewed contact research checklist. No profiles were scraped and no email was guessed.", payload)


def _ok(message: str, details: dict) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=message)], details={"ok": True, **details})


def _error(exc: Exception) -> AgentToolResult:
    return AgentToolResult(content=f"Invalid tool input: {exc}", details={"ok": False, "error": str(exc)})


def _text_pair_schema() -> dict:
    return {"type": "object", "properties": {"candidate_text": {"type": "string"}, "job_text": {"type": "string"}}, "required": ["candidate_text", "job_text"], "additionalProperties": False}


def create_tools() -> list[AgentTool]:
    return [
        AgentTool(name="analyze_candidate_against_job", label="Analyze candidate against job", description="Calculate deterministic, evidence-based job match and CV readiness from supplied text.", parameters=_text_pair_schema(), execute_fn=execute_analyze_job),
        AgentTool(name="build_learning_and_project_plan", label="Build learning and project plan", description="Create an evidence-linked skill gap tree, learning resources, and portfolio project briefs.", parameters=_text_pair_schema(), execute_fn=execute_skill_plan),
        AgentTool(name="draft_truthful_cv_changes", label="Draft truthful CV changes", description="Suggest only CV edits that are grounded in supplied candidate evidence; never invent claims.", parameters=_text_pair_schema(), execute_fn=execute_tailor_resume),
        AgentTool(name="create_interview_practice", label="Create interview practice", description="Create role-specific technical, behavioural, and motivation practice questions.", parameters=_text_pair_schema(), execute_fn=execute_interview_questions),
        AgentTool(name="create_contact_research_plan", label="Create contact research plan", description="Create manual public-research queries and contact priorities; never scrape LinkedIn/X or generate emails.", parameters={"type": "object", "properties": {"company": {"type": "string"}, "job_title": {"type": "string"}}, "required": ["company", "job_title"], "additionalProperties": False}, execute_fn=execute_contact_plan),
    ]
