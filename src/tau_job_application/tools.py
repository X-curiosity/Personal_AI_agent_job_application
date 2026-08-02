"""Tau adapters around tested job-domain functions."""

from collections.abc import Mapping

from tau_agent import AgentTool, AgentToolResult, TextContent
from tau_agent.types import JSONValue

from tau_job_application.pipeline import analyze_texts


async def execute_analyze_job(
    tool_call_id: str,
    arguments: Mapping[str, JSONValue],
    signal=None,
    on_update=None,
) -> AgentToolResult:
    del tool_call_id, on_update
    if signal is not None and signal.is_cancelled():
        return AgentToolResult(content="Analysis cancelled", details={"ok": False})
    try:
        candidate_text = str(arguments["candidate_text"])
        job_text = str(arguments["job_text"])
        result = analyze_texts(candidate_text, job_text)
    except (KeyError, TypeError, ValueError) as exc:
        return AgentToolResult(
            content=f"Invalid analysis input: {exc}",
            details={"ok": False, "error": str(exc)},
        )

    return AgentToolResult(
        content=[TextContent(text=f"Evidence-based match score: {result.match.score}/100")],
        details={"ok": True, "analysis": result.model_dump(mode="json")},
    )


def create_tools() -> list[AgentTool]:
    return [
        AgentTool(
            name="analyze_candidate_against_job",
            label="Analyze candidate against job",
            description=(
                "Parse synthetic candidate/job text and calculate a deterministic, "
                "evidence-based match."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "candidate_text": {"type": "string"},
                    "job_text": {"type": "string"},
                },
                "required": ["candidate_text", "job_text"],
                "additionalProperties": False,
            },
            execute_fn=execute_analyze_job,
        )
    ]
