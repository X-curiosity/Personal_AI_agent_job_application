from pathlib import Path


def test_agent_policy_and_tools_are_declared() -> None:
    """Keep this check offline: Tau's provider integration is exercised manually."""
    source = (Path(__file__).parents[1] / "src" / "tau_job_application" / "agent.py").read_text()

    assert "Never invent skills" in source
    assert "Do not scrape or\nautomate LinkedIn or X" in source
    assert "max_turns=8" in source
