from __future__ import annotations

from tau_job_application.company_branding import CompanyBrandStore
from tau_job_application.role_discovery import (
    CompanyFacts,
    DiscoveredOpening,
    RoleDiscoveryStore,
    RoleQuery,
    SourceSnapshot,
    rank_openings,
)
from tau_job_application.role_market_state import RoleMarketStateStore
from tau_job_application.workspaces import WorkspaceStore


def test_landing_snapshot_uses_the_newest_local_market_and_its_shortlist(tmp_path, monkeypatch) -> None:
    from tau_job_application import ui

    database = tmp_path / "landing.sqlite"
    workspaces = WorkspaceStore(database)
    discovery = RoleDiscoveryStore(database)
    monkeypatch.setattr(ui, "WORKSPACES", workspaces)
    monkeypatch.setattr(ui, "ROLE_DISCOVERY", discovery)

    track_id = workspaces.create_workspace("Engineering")
    thread_id = workspaces.create_thread(track_id, "Backend roles")
    opening = DiscoveredOpening(
        title="Backend Engineer",
        company=CompanyFacts(name="Figma"),
        source="Greenhouse",
        source_identifier="figma",
        external_id="backend-1",
        source_url="https://boards.greenhouse.io/figma/jobs/backend-1",
        location="San Francisco, CA",
        workplace_type="Hybrid",
        retrieved_at="2026-10-06T10:00:00+00:00",
    )
    query = RoleQuery(title="Backend Engineer", aliases=("Platform Engineer",))
    matches = rank_openings(query, [opening])
    discovery.save_latest_run(
        career_track_id=track_id,
        workspace_id=thread_id,
        query=query,
        matches=matches,
        sources=(SourceSnapshot(source="Figma · Greenhouse", identifier="figma", opening_count=1),),
    )
    RoleMarketStateStore(database).set_status(track_id, thread_id, opening, "saved")
    CompanyBrandStore(database).upsert(
        "Figma",
        "https://assets.example.test/figma.svg",
        source="candidate-provided",
    )

    data = ui._landing_page_data()

    assert data.role_pages == 1
    assert data.official_openings == 1
    assert data.shortlisted_openings == 1
    assert data.companies == 1
    assert data.latest_role_title == "Backend Engineer"
    assert len(data.opportunities) == 1
    assert data.opportunities[0].company == "Figma"
    # Remote logos stay off until the user opts in (IP privacy), even when a
    # local mapping exists.
    assert data.opportunities[0].logo_url is None

    monkeypatch.setattr(ui, "_remote_logos_allowed", lambda: True)
    opted_in = ui._landing_page_data()
    assert opted_in.opportunities[0].logo_url == "https://assets.example.test/figma.svg"


def test_role_mark_uses_catalog_then_prefers_a_local_override(tmp_path, monkeypatch) -> None:
    from tau_job_application import ui

    database = tmp_path / "brands.sqlite"
    monkeypatch.setattr(ui, "WORKSPACES", WorkspaceStore(database))

    # Default: a local monogram only; no remote request is made without opt-in.
    private_markup = ui._company_mark_markup("Figma")
    assert "<img" not in private_markup
    assert ">FI</span>" in private_markup

    monkeypatch.setattr(ui, "_remote_logos_allowed", lambda: True)
    catalog_markup = ui._company_mark_markup("Figma")
    assert 'src="https://cdn.simpleicons.org/figma/000000"' in catalog_markup
    assert 'aria-label="Figma"' in catalog_markup
    assert ">FI</span>" in catalog_markup

    CompanyBrandStore(database).upsert(
        "Figma",
        "https://assets.example.test/figma.svg",
        source="candidate-provided",
    )
    custom_markup = ui._company_mark_markup("Figma")
    assert 'src="https://assets.example.test/figma.svg"' in custom_markup
    assert "cdn.simpleicons.org" not in custom_markup
