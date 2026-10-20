from datetime import UTC, datetime, timedelta

from streamlit.testing.v1 import AppTest

from tau_job_application.application_tracker import ApplicationTrackerStore
from tau_job_application.monitoring import JobMonitor
from tau_job_application.requirement_memory import RequirementMemory
from tau_job_application.role_discovery import RoleDiscoveryStore
from tau_job_application.role_market_state import RoleMarketStateStore, opening_key
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import WorkspaceStore

ROLE = "Hardware Engineer"


def setup_ui(tmp_path, monkeypatch):
    from tau_job_application import ui

    path = tmp_path / "portal.sqlite"
    for name, store in {"WORKSPACES": WorkspaceStore(path), "STORE": LocalStore(path), "MONITOR": JobMonitor(path),
                        "REQUIREMENT_MEMORY": RequirementMemory(path), "ROLE_DISCOVERY": RoleDiscoveryStore(path)}.items():
        monkeypatch.setattr(ui, name, store)
    return ui


def fake_openings(source, identifier, *, company):
    if company != "OpenAI":
        return []
    five_days_ago = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    return [
        {"title": "Hardware Engineer", "source": source, "source_id": "hw-1", "board_identifier": identifier,
         "url": "https://jobs.ashbyhq.com/openai/hw-1", "description": "Required skills: Python, C++",
         "location": "San Francisco", "workplace_type": "Hybrid",
         "source_timestamp": five_days_ago, "source_timestamp_kind": "published"},
        {"title": "Hardware Engineer, Intern", "source": source, "source_id": "hw-2", "board_identifier": identifier,
         "url": "https://jobs.ashbyhq.com/openai/hw-2", "description": "Required skills: Python",
         "location": "Zurich", "source_timestamp": five_days_ago, "source_timestamp_kind": "published"},
    ]


def _cluster_app(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    monkeypatch.setattr(ui, "fetch_public_board_openings", fake_openings)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=40)
    app.query_params.update({"view": "role", "role": ROLE})
    app.run()
    assert not app.exception
    return ui, app


def _track(app):
    return app.session_state["workspace_selector"]


def test_cluster_dashboard_lists_rows_like_a_saved_jobs_page(tmp_path, monkeypatch):
    ui, app = _cluster_app(tmp_path, monkeypatch)

    titles = [item.label for item in app.button]
    assert "Hardware Engineer" in titles and "Hardware Engineer, Intern" in titles
    apply_links = [item for item in app.get("link_button") if item.label == "Apply ↗"]
    assert [link.url for link in apply_links] == [
        "https://jobs.ashbyhq.com/openai/hw-1",
        "https://jobs.ashbyhq.com/openai/hw-2",
    ]
    page_text = " ".join(item.value for item in app.markdown)
    assert "Not tracked" in page_text
    assert "Posted 5d ago" in page_text
    assert "San Francisco" in page_text and "(Hybrid)" in page_text
    assert any("selected" in item.value for item in app.caption)
    assert any("Not seeing some jobs?" in item.value for item in app.caption)


def test_add_note_starts_tracking_and_appends_dated_notes(tmp_path, monkeypatch):
    ui, app = _cluster_app(tmp_path, monkeypatch)

    note_area = next(item for item in app.text_area if item.label == "New note")
    note_area.set_value("Recruiter asked for my transcript.")
    next(item for item in app.button if item.label == "Save note").click()
    app.run()
    assert not app.exception

    track = _track(app)
    records = ApplicationTrackerStore(ui.WORKSPACES.path).list_records(track)
    assert len(records) == 1  # adding a note started tracking exactly one role
    assert records[0].progress.stage.value == "saved"
    assert "Recruiter asked for my transcript." in records[0].progress.notes
    assert datetime.now(UTC).date().isoformat() in records[0].progress.notes

    app.run()
    assert any("Latest notes" in item.value for item in app.caption)
    assert "Saved" in " ".join(item.value for item in app.markdown)


def test_status_pill_reflects_the_tracked_stage(tmp_path, monkeypatch):
    ui, app = _cluster_app(tmp_path, monkeypatch)
    track = _track(app)
    tracker = ApplicationTrackerStore(ui.WORKSPACES.path)
    record = tracker.list_records(track)
    # Track the first row through its note flow, then move it to Applied.
    note_area = next(item for item in app.text_area if item.label == "New note")
    note_area.set_value("Preparing documents.")
    next(item for item in app.button if item.label == "Save note").click()
    app.run()
    record = ApplicationTrackerStore(ui.WORKSPACES.path).list_records(track)[0]
    from tau_job_application.application_tracker import ApplicationStage
    progress = record.progress.model_copy(update={"stage": ApplicationStage.APPLIED, "applied_on": datetime.now(UTC).date()})
    ApplicationTrackerStore(ui.WORKSPACES.path).update(track, record.id, progress)
    app.run()
    assert not app.exception
    assert "Applied" in " ".join(item.value for item in app.markdown)


def test_bulk_hide_removes_rows_and_preserves_state(tmp_path, monkeypatch):
    ui, app = _cluster_app(tmp_path, monkeypatch)
    track = _track(app)

    boxes = [item for item in app.checkbox if item.label == "Select"]
    assert len(boxes) == 2
    boxes[0].check().run()
    hide = next(item for item in app.button if item.label == "Hide selected")
    assert hide.disabled is False
    hide.click().run()
    assert not app.exception

    titles = [item.label for item in app.button if item.label.startswith("Hardware Engineer")]
    assert len(titles) == 1
    store = RoleMarketStateStore(ui.WORKSPACES.path)
    hidden = [state for state in store.list_states(track, _thread(ui, track)) if state.status.value == "hidden"]
    assert len(hidden) == 1
    assert any("1 hidden by you" in item.value for item in app.caption)


def test_bulk_track_creates_application_records(tmp_path, monkeypatch):
    ui, app = _cluster_app(tmp_path, monkeypatch)
    track = _track(app)

    for box in [item for item in app.checkbox if item.label == "Select"]:
        box.check().run()
    next(item for item in app.button if item.label == "Track selected").click().run()
    assert not app.exception
    assert len(ApplicationTrackerStore(ui.WORKSPACES.path).list_records(track)) == 2
    assert "Saved" in " ".join(item.value for item in app.markdown)


def test_title_opens_the_application_workspace(tmp_path, monkeypatch):
    ui, app = _cluster_app(tmp_path, monkeypatch)
    next(item for item in app.button if item.label == "Hardware Engineer").click().run()
    assert not app.exception
    assert app.query_params["view"] == ["application"]


def _thread(ui, track):
    return next(thread["id"] for thread in ui.WORKSPACES.list_threads(track))
