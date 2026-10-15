from datetime import date

from streamlit.testing.v1 import AppTest

from tau_job_application.application_tracker import ApplicationStage, ApplicationTrackerStore
from tau_job_application.monitoring import JobMonitor
from tau_job_application.requirement_memory import RequirementMemory
from tau_job_application.role_discovery import CompanyFacts, DiscoveredOpening, RoleDiscoveryStore
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import WorkspaceStore


def test_saved_role_can_be_tracked_through_application_interview_and_closure(tmp_path, monkeypatch):
    from tau_job_application import ui

    database = tmp_path / "tracker-ui.sqlite"
    workspaces = WorkspaceStore(database)
    for name, value in {
        "WORKSPACES": workspaces, "STORE": LocalStore(database), "MONITOR": JobMonitor(database),
        "REQUIREMENT_MEMORY": RequirementMemory(database), "ROLE_DISCOVERY": RoleDiscoveryStore(database),
    }.items():
        monkeypatch.setattr(ui, name, value)
    def fake_fetch(source, identifier, *, company):
        if company != "Figma":
            return []
        return [{"source": source, "source_id": "job-1", "board_identifier": identifier,
                 "title": "Backend Engineer", "location": "Zurich, Switzerland",
                 "url": "https://boards.greenhouse.io/figma/jobs/job-1", "description": "Build Python services"}]
    monkeypatch.setattr(ui, "fetch_public_board_openings", fake_fetch)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30).run()
    next(item for item in app.text_input if item.label == "Role to explore").set_value("Backend Engineer")
    next(item for item in app.button if item.label == "Discover matching openings").click().run()
    next(item for item in app.button if item.label == "Save for review").click().run()
    track = workspaces.list_workspaces()[0]["id"]
    store = ApplicationTrackerStore(database)
    record = store.list_records(track)[0]
    assert record.progress.stage is ApplicationStage.SAVED
    next(item for item in app.button if item.label == "Start tracking").click().run()
    assert not app.exception
    assert app.query_params["view"] == ["applications"]
    assert store.get(track, record.id).progress.stage is ApplicationStage.SAVED
    next(item for item in app.button if item.label == "I applied").click().run()
    assert not app.exception
    assert store.get(track, record.id).progress.stage is ApplicationStage.APPLIED
    assert store.get(track, record.id).progress.applied_on is not None

    next(item for item in app.selectbox if item.label == "Status").select(ApplicationStage.INTERVIEW)
    next(item for item in app.text_input if item.label == "Next step").set_value("Prepare technical demo")
    next(item for item in app.date_input if item.label == "Next-step date (optional)").set_value(date(2026, 10, 15))
    next(item for item in app.text_area if item.label == "Application notes").set_value("Bring the Python project")
    next(item for item in app.button if item.label == "Save application update").click().run()
    assert not app.exception
    updated = store.get(track, record.id)
    assert updated.progress.stage is ApplicationStage.INTERVIEW
    assert updated.progress.next_step_on == date(2026, 10, 15)
    assert updated.progress.notes == "Bring the Python project"
    assert len(store.history(track, record.id)) == 3

    next(item for item in app.button if item.label == "Interview · 1").click().run()
    assert not app.exception
    assert next(item for item in app.selectbox if item.label == "Application stage").value == "Interview"
    next(item for item in app.checkbox if item.label == "Needs attention in the next seven days").check().run()
    assert not app.exception
    next(item for item in app.checkbox if item.label == "Needs attention in the next seven days").uncheck().run()
    assert not app.exception
    next(item for item in app.selectbox if item.label == "Application stage").select("All active").run()

    next(item for item in app.selectbox if item.label == "Status").select(ApplicationStage.CLOSED)
    next(item for item in app.selectbox if item.label == "Reason if closed").select("withdrawn")
    next(item for item in app.button if item.label == "Save application update").click().run()
    assert not app.exception
    assert not any(item.label == "Save application update" for item in app.button)
    next(item for item in app.selectbox if item.label == "Application stage").select("Closed").run()
    assert not app.exception
    assert any(item.label == "Save application update" for item in app.button)
    assert store.get(track, record.id).progress.closed_reason == "withdrawn"


def test_tracker_empty_state_does_not_create_fake_applications(tmp_path, monkeypatch):
    from tau_job_application import ui
    database = tmp_path / "empty.sqlite"
    workspaces = WorkspaceStore(database)
    monkeypatch.setattr(ui, "WORKSPACES", workspaces)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30)
    app.query_params["view"] = "applications"
    app.run()
    assert not app.exception
    assert any("Save a role from the Role market" in item.value for item in app.info)
    assert ApplicationTrackerStore(database).list_records(workspaces.list_workspaces()[0]["id"]) == []
