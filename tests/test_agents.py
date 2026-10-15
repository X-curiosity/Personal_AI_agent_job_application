import pytest

from tau_agent.messages import AssistantMessage, TextContent, ToolCall
from tau_ai import FakeProvider
from tau_ai.events import AssistantDoneEvent

from tau_job_application.agents import (
    AGENT_SPECS,
    SPECS_BY_KEY,
    TeamCoordinator,
    TeamDependencies,
    route_request,
)
from tau_job_application.company_catalog import CompanyCatalogStore
from tau_job_application.eligibility import ResidencyStore
from tau_job_application.yc_directory import YCDirectoryStore, parse_yc_directory


def _deps(tmp_path):
    database = tmp_path / "db.sqlite"
    return TeamDependencies(
        yc_store=YCDirectoryStore(database),
        catalog_store=CompanyCatalogStore(database),
        residency_store=ResidencyStore(database),
        workspace_id="track",
    )


def _text_stream(text):
    return [AssistantDoneEvent(reason="stop", message=AssistantMessage(content=[TextContent(text=text)]))]


def _tool_stream(tool_call):
    return [AssistantDoneEvent(reason="toolUse", message=AssistantMessage(content=[tool_call]))]


def test_routing_is_deterministic_and_explained():
    decision = route_request("Do I need a visa to work in Canada?")
    assert decision.agent_key == "eligibility_advisor"
    assert "visa" in decision.matched_keywords
    assert route_request("Show me active YC startups that are hiring").agent_key == "company_scout"
    default = route_request("How well does my CV match this job?")
    assert default.agent_key == "application_prep"
    assert default.matched_keywords == ()
    assert {spec.key for spec in AGENT_SPECS} == {"company_scout", "eligibility_advisor", "application_prep"}


@pytest.mark.asyncio
async def test_coordinator_runs_one_bounded_specialist_with_trace(tmp_path):
    deps = _deps(tmp_path)
    provider = FakeProvider([
        _tool_stream(ToolCall(id="c1", name="get_residency_profile", arguments={})),
        _tool_stream(ToolCall(id="c2", name="build_eligibility_checklist", arguments={"job_country": "Canada"})),
        _text_stream("You will likely need employer sponsorship; verify with IRCC."),
    ])
    deps.residency_store.save("track", _profile())
    coordinator = TeamCoordinator(provider=provider, model="fake", deps=deps)
    result = await coordinator.run("What documents do I need for a work visa to apply in Canada from France?")
    assert result.agent_key == "eligibility_advisor"
    assert result.error is None
    assert "sponsorship" in result.text.lower() or "verify" in result.text.lower()
    assert [entry.tool_name for entry in result.tool_trace] == ["get_residency_profile", "build_eligibility_checklist"]
    assert all(entry.ok for entry in result.tool_trace)
    assert result.turns == 3
    # The specialist only received its own narrow tools.
    tool_names = [tool.name for tool in provider.calls[0][3]]
    assert tool_names == ["save_residency_profile", "get_residency_profile", "build_eligibility_checklist"]


@pytest.mark.asyncio
async def test_company_scout_searches_local_snapshot_only(tmp_path):
    deps = _deps(tmp_path)
    deps.yc_store.refresh(parse_yc_directory([
        {"slug": "alpha-ai", "name": "Alpha AI", "status": "Active", "isHiring": True, "industries": ["Fintech"]},
        {"slug": "beta-health", "name": "Beta Health", "status": "Inactive", "isHiring": False},
    ]))
    provider = FakeProvider([
        _tool_stream(ToolCall(id="c1", name="search_yc_directory", arguments={"statuses": ["Active"], "hiring_only": True})),
        _text_stream("Alpha AI matches; the hiring flag is not a vacancy guarantee."),
    ])
    coordinator = TeamCoordinator(provider=provider, model="fake", deps=deps)
    result = await coordinator.run("Which active YC companies are hiring?", agent_key="company_scout")
    assert result.routing.reason == "Manually selected specialist."
    assert result.error is None
    trace = result.tool_trace[0]
    assert trace.tool_name == "search_yc_directory" and trace.ok
    assert "Found 1 companie(s)" in trace.message


@pytest.mark.asyncio
async def test_tool_call_budget_blocks_excess_calls(tmp_path):
    spec = SPECS_BY_KEY["eligibility_advisor"]
    one_turn_many_calls = AssistantDoneEvent(
        reason="toolUse",
        message=AssistantMessage(content=[
            ToolCall(id=f"c{index}", name="get_residency_profile", arguments={})
            for index in range(spec.max_tool_calls + 1)
        ]),
    )
    provider = FakeProvider([[one_turn_many_calls], _text_stream("Budget reached; answering from what I have.")])
    coordinator = TeamCoordinator(provider=provider, model="fake", deps=_deps(tmp_path))
    result = await coordinator.run("Check my eligibility everywhere", agent_key="eligibility_advisor")
    assert result.blocked_tool_calls == 1
    started = [entry for entry in result.tool_trace]
    assert len(started) == spec.max_tool_calls + 1
    assert sum(1 for entry in started if entry.ok is False) == 1
    assert result.turns <= spec.max_turns


@pytest.mark.asyncio
async def test_unknown_specialist_and_empty_request_are_rejected(tmp_path):
    coordinator = TeamCoordinator(provider=FakeProvider([]), model="fake", deps=_deps(tmp_path))
    with pytest.raises(ValueError):
        await coordinator.run("hello", agent_key="does_not_exist")
    with pytest.raises(ValueError):
        await coordinator.run("   ")


@pytest.mark.asyncio
async def test_provider_failure_is_reported_without_secrets(tmp_path):
    class BrokenProvider:
        def stream_response(self, **kwargs):
            raise RuntimeError("secret-api-key-details")

    coordinator = TeamCoordinator(provider=BrokenProvider(), model="fake", deps=_deps(tmp_path))
    result = await coordinator.run("Analyze this", agent_key="application_prep")
    assert result.error == "The specialist run failed: RuntimeError"
    assert "secret" not in result.error


def _profile():
    from tau_job_application.eligibility import ResidencyProfile

    return ResidencyProfile(citizenships=("France",), residence_country="France")
