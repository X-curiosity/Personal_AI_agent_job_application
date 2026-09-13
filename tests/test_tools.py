import pytest

from tau_job_application.tools import create_tools


@pytest.mark.asyncio
async def test_tau_tool_executes_without_a_model() -> None:
    tool = create_tools()[0]
    result = await tool.execute(
        "test-call",
        {
            "candidate_text": "Name: Alex\nSkills: Python, SQL",
            "job_text": "Title: Engineer\nCompany: Example\nRequired skills: Python, Docker",
        },
    )

    assert result.details["ok"] is True
    assert result.details["match"]["score"] == 60
    assert result.details["tailored_resume"]["safety_note"]
