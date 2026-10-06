from __future__ import annotations

import pytest

from tau_job_application.role_discovery import CompanyFacts, DiscoveredOpening
from tau_job_application.role_market_state import (
    RoleMarketStateStore,
    RoleMarketStatus,
    opening_key,
)
from tau_job_application.workspaces import WorkspaceStore


def _opening(
    *,
    title: str = "Backend Engineer",
    company: str = "Acme",
    source: str = "Greenhouse",
    board: str | None = "acme",
    external_id: str | None = "123",
    url: str | None = "https://boards.greenhouse.io/acme/jobs/123?utm_source=test",
    description: str | None = "Build reliable Python services.",
) -> DiscoveredOpening:
    return DiscoveredOpening(
        title=title,
        company=CompanyFacts(name=company),
        source=source,
        source_identifier=board,
        external_id=external_id,
        source_url=url,
        description=description,
        location="Berlin, Germany",
        retrieved_at="2026-10-06T10:00:00+00:00",
    )


def _scoped_store(tmp_path):
    database = tmp_path / "local.sqlite"
    workspaces = WorkspaceStore(database)
    market = RoleMarketStateStore(database)
    engineering = workspaces.create_workspace("Engineering")
    product = workspaces.create_workspace("Product")
    backend_thread = workspaces.create_thread(engineering, "Backend roles")
    product_thread = workspaces.create_thread(product, "Product roles")
    return workspaces, market, engineering, product, backend_thread, product_thread


def test_status_is_thread_scoped_and_keeps_a_source_snapshot_after_a_refresh(tmp_path) -> None:
    _, market, engineering, product, backend_thread, product_thread = _scoped_store(tmp_path)
    original = _opening()

    saved = market.set_status(engineering, backend_thread, original, RoleMarketStatus.SAVED)

    assert saved.status is RoleMarketStatus.SAVED
    assert saved.opening_key == "url:https://boards.greenhouse.io/acme/jobs/123"
    assert [state.status for state in market.list_states(engineering, backend_thread)] == [RoleMarketStatus.SAVED]
    assert market.list_states(product, product_thread) == []

    refreshed = _opening(
        title="Senior Platform Engineer",
        company="Renamed Acme",
        description="A refreshed source record.",
        url="https://boards.greenhouse.io/acme/jobs/123#job-details",
    )
    # The state is found through its source URL, not through mutable display
    # fields, and the pre-refresh source snapshot remains inspectable.
    restored = market.state_for(engineering, backend_thread, refreshed)
    assert restored is not None
    assert restored.status is RoleMarketStatus.SAVED
    assert restored.opening.title == "Backend Engineer"
    assert restored.opening.description == "Build reliable Python services."

    tracking = market.set_status(engineering, backend_thread, refreshed, "Tracking")
    assert tracking.status is RoleMarketStatus.TRACKING
    states = market.list_states(engineering, backend_thread)
    assert len(states) == 1
    assert states[0].opening.title == "Senior Platform Engineer"
    assert states[0].opening.description == "A refreshed source record."


def test_external_source_identity_is_used_without_title_or_company_inference(tmp_path) -> None:
    _, market, engineering, _, backend_thread, _ = _scoped_store(tmp_path)
    original = _opening(
        title="ML Engineer",
        company="Original Company",
        source="Ashby",
        board="acme.ai",
        external_id="external-9",
        url=None,
    )
    renamed = _opening(
        title="Applied Scientist",
        company="New Company Name",
        source="Ashby",
        board="acme.ai",
        external_id="external-9",
        url=None,
    )

    assert opening_key(original) == "source:ashby:acme.ai:external-9"
    market.set_status(engineering, backend_thread, original, "Hidden")
    found = market.state_for(engineering, backend_thread, renamed)

    assert found is not None
    assert found.status is RoleMarketStatus.HIDDEN
    assert found.opening.title == "ML Engineer"
    assert found.opening.company.name == "Original Company"


def test_state_rejects_title_company_fallbacks_and_non_viewing_statuses(tmp_path) -> None:
    _, market, engineering, _, backend_thread, _ = _scoped_store(tmp_path)
    unidentifiable = _opening(board=None, external_id=None, url=None)

    with pytest.raises(ValueError, match="canonical source URL or source, board, and external ID"):
        opening_key(unidentifiable)
    with pytest.raises(ValueError, match="Saved, Hidden, or Tracking"):
        market.set_status(engineering, backend_thread, _opening(), "Applied")
    with pytest.raises(ValueError, match="Saved, Hidden, or Tracking"):
        market.set_status(engineering, backend_thread, _opening(), "Submitted")


def test_scope_is_validated_for_each_operation_and_thread_deletion_cascades(tmp_path) -> None:
    workspaces, market, engineering, product, backend_thread, product_thread = _scoped_store(tmp_path)
    opening = _opening()
    market.set_status(engineering, backend_thread, opening, "Saved")

    with pytest.raises(ValueError, match="Job workspace not found in this career direction"):
        market.list_states(product, backend_thread)
    with pytest.raises(ValueError, match="Job workspace not found in this career direction"):
        market.state_for(engineering, product_thread, opening)
    with pytest.raises(ValueError, match="Job workspace not found in this career direction"):
        market.clear_status(product, backend_thread, opening)

    workspaces.delete_thread(engineering, backend_thread)
    with market._connect() as db:
        count = db.execute(
            "SELECT count(*) FROM role_market_states WHERE thread_id=?", (backend_thread,)
        ).fetchone()[0]
    assert count == 0


def test_clear_status_only_removes_the_matching_source_opening(tmp_path) -> None:
    _, market, engineering, _, backend_thread, _ = _scoped_store(tmp_path)
    first = _opening(external_id="first", url="https://boards.greenhouse.io/acme/jobs/first")
    second = _opening(external_id="second", url="https://boards.greenhouse.io/acme/jobs/second")
    market.set_status(engineering, backend_thread, first, "Saved")
    market.set_status(engineering, backend_thread, second, "Tracking")

    market.clear_status(engineering, backend_thread, first)

    assert market.state_for(engineering, backend_thread, first) is None
    remaining = market.list_states(engineering, backend_thread)
    assert [(state.opening.external_id, state.status) for state in remaining] == [
        ("second", RoleMarketStatus.TRACKING)
    ]
