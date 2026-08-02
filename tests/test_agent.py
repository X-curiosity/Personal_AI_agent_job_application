from tau_ai import FakeProvider

from tau_job_application.agent import build_agent


def test_agent_harness_can_be_built_without_network_access() -> None:
    harness = build_agent(provider=FakeProvider([]), model="fake-model")

    assert harness.config.model == "fake-model"
    assert [tool.name for tool in harness.config.tools] == [
        "analyze_candidate_against_job"
    ]
