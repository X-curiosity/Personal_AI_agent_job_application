from datetime import date

import pytest

from tau_job_application.application_tracker import ApplicationProgress, ApplicationStage, ApplicationTrackerStore
from tau_job_application.application_tracker_ui import ordered_applications, weekly_attention
from tau_job_application.role_discovery import CompanyFacts, DiscoveredOpening
from tau_job_application.role_market_state import RoleMarketStateStore
from tau_job_application.workspaces import WorkspaceStore


def opening(suffix="1", **updates):
    values = dict(title="Backend Engineer", company=CompanyFacts(name="Example Co"), source="Greenhouse",
                  source_identifier="example", external_id=suffix,
                  source_url=f"https://boards.greenhouse.io/example/jobs/{suffix}",
                  description="Build Python services", location="Zurich, Switzerland")
    return DiscoveredOpening(**(values | updates))


@pytest.fixture
def stores(tmp_path):
    path = tmp_path / "tracker.sqlite"
    workspaces = WorkspaceStore(path)
    track = workspaces.create_workspace("Engineering")
    other = workspaces.create_workspace("Design")
    thread = workspaces.create_thread(track, "Backend market")
    return workspaces, ApplicationTrackerStore(path), track, other, thread


def test_save_is_idempotent_and_retains_original_advert_and_progress(stores):
    _, store, track, _, thread = stores
    saved = store.save(track, thread, opening(), relevance=82)
    progress = ApplicationProgress(stage="interview", stage_on=date(2026, 10, 6),
                                   applied_on=date(2026, 10, 3), next_step="Technical interview",
                                   next_step_on=date(2026, 10, 9), notes="Prepare the Python demo")
    updated = store.update(track, saved.id, progress)
    returned = store.save(track, thread, opening(title="Renamed role", description="Changed advert"), relevance=60)
    assert returned.id == saved.id
    assert returned.progress == progress
    assert returned.opening.description == "Build Python services"
    assert returned.relevance == 82
    assert len(store.list_records(track)) == 1
    assert [event.action for event in store.history(track, saved.id)] == ["updated", "saved"]
    store.update(track, saved.id, progress)
    assert len(store.history(track, saved.id)) == 2
    with pytest.raises(ValueError, match="another view"):
        store.update(track, saved.id, ApplicationProgress(), expected_updated_at=saved.updated_at)
    assert store.get(track, saved.id).updated_at == updated.updated_at


def test_weekly_attention_excludes_closed_expired_and_already_applied_deadlines(stores):
    _, store, track, _, thread = stores
    today = date(2026, 10, 7)
    cases = [
        ("1", ApplicationProgress(next_step="Prepare CV", next_step_on=date(2026, 10, 6), deadline=date(2026, 10, 9))),
        ("2", ApplicationProgress(stage="closed", next_step="Old task", next_step_on=today, deadline=today)),
        ("3", ApplicationProgress(stage="applied", deadline=today)),
        ("4", ApplicationProgress(availability="expired", deadline=today)),
        ("5", ApplicationProgress(next_step="Later task", next_step_on=date(2026, 10, 15), deadline=date(2026, 10, 15))),
        ("6", ApplicationProgress(next_step="Undated task")),
    ]
    for identifier, progress in cases:
        record = store.save(track, thread, opening(identifier))
        store.update(track, record.id, progress)
    actions, deadlines = weekly_attention(store.list_records(track), today)
    assert [row.opening.external_id for row in actions] == ["1"]
    assert [row.opening.external_id for row in deadlines] == ["1"]


def test_scope_move_and_delete_keep_ownership_and_history_consistent(stores):
    workspaces, store, track, other, thread = stores
    saved = store.save(track, thread, opening())
    for action in (
        lambda: store.save(other, thread, opening()),
        lambda: store.get(other, saved.id),
        lambda: store.update(other, saved.id, ApplicationProgress(stage="applied")),
        lambda: store.history(other, saved.id),
        lambda: store.delete(other, saved.id),
        lambda: store.list_records(other, thread_id=thread),
    ):
        with pytest.raises(ValueError):
            action()
    workspaces.move_thread(track, thread, other)
    assert store.list_records(track) == []
    assert store.get(other, saved.id).id == saved.id
    assert len(store.history(other, saved.id)) == 1
    workspaces.delete_thread(other, thread)
    assert store.list_records(other) == []
    with store._connect() as db:
        assert db.execute("SELECT count(*) FROM application_events").fetchone()[0] == 0


def test_shortlist_import_preserves_saved_intent_and_never_resurrects_removed_records(stores):
    _, store, track, _, thread = stores
    shortlist = RoleMarketStateStore(store.path)
    shortlist.set_status(track, thread, opening("1"), "saved")
    shortlist.set_status(track, thread, opening("2"), "tracking")
    shortlist.set_status(track, thread, opening("3"), "hidden")
    assert store.import_shortlist(track) == 2
    assert store.import_shortlist(track) == 0
    rows = store.list_records(track)
    assert len(rows) == 2
    assert all(row.progress.stage is ApplicationStage.SAVED for row in rows)
    store.delete(track, rows[0].id)
    assert store.import_shortlist(track) == 0
    assert len(store.list_records(track)) == 1
    with pytest.raises(ValueError):
        store.history(track, rows[0].id)
    # Saving deliberately again remains possible.
    store.save(track, thread, rows[0].opening)
    assert len(store.list_records(track)) == 2


def test_dates_availability_and_archiving_are_independent(stores):
    _, store, track, _, thread = stores
    no_deadline = store.save(track, thread, opening("1"))
    soon = store.save(track, thread, opening("2"))
    closed = store.save(track, thread, opening("3"))
    soon = store.update(track, soon.id, ApplicationProgress(stage="interview", deadline=date(2026, 10, 9), availability="expired"))
    closed = store.update(track, closed.id, ApplicationProgress(stage="closed", deadline=date(2026, 10, 1), closed_reason="withdrawn"))
    assert [row.id for row in ordered_applications([closed, no_deadline, soon])] == [soon.id, no_deadline.id, closed.id]
    assert soon.progress.stage is ApplicationStage.INTERVIEW
    assert soon.opening.description
    assert len(store.list_records(track)) == 3
    with pytest.raises(ValueError, match="next step"):
        ApplicationProgress(next_step_on=date(2026, 10, 9))
    with pytest.raises(ValueError, match="closing reason"):
        ApplicationProgress(stage="saved", closed_reason="rejected")


def test_tracking_requires_an_official_identity_and_keeps_distinct_roles(stores):
    _, store, track, _, thread = stores
    with pytest.raises(ValueError):
        store.save(track, thread, opening(source_url=None, external_id=None))
    first = store.save(track, thread, opening("1"))
    second = store.save(track, thread, opening("2"))
    assert first.id != second.id
    assert first.opening.title == second.opening.title
