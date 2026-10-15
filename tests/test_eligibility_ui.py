from streamlit.testing.v1 import AppTest

from tau_job_application.application_tracker import ApplicationTrackerStore
from tau_job_application.company_catalog import CompanyCatalogStore
from tau_job_application.eligibility import ResidencyStore
from tau_job_application.monitoring import JobMonitor
from tau_job_application.requirement_memory import RequirementMemory
from tau_job_application.role_discovery import RoleDiscoveryStore
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import WorkspaceStore
from tau_job_application.yc_directory import YCDirectoryStore


def setup_ui(tmp_path, monkeypatch):
    from tau_job_application import ui
    path = tmp_path / "portal.sqlite"
    for name, store in {
        "WORKSPACES": WorkspaceStore(path), "STORE": LocalStore(path), "MONITOR": JobMonitor(path),
        "REQUIREMENT_MEMORY": RequirementMemory(path), "ROLE_DISCOVERY": RoleDiscoveryStore(path),
        "YC_DIRECTORY": YCDirectoryStore(path), "RESIDENCY": ResidencyStore(path),
        "COMPANY_CATALOG": CompanyCatalogStore(path), "APPLICATIONS": ApplicationTrackerStore(path),
    }.items():
        monkeypatch.setattr(ui, name, store)
    return ui


def _app():
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=60)
    app.query_params["view"] = "eligibility"
    return app


def test_profile_is_required_before_checklists(tmp_path, monkeypatch):
    setup_ui(tmp_path, monkeypatch)
    app = _app()
    app.run()
    assert not app.exception
    assert any("Save your residency profile once" in item.body for item in app.info)


def test_save_profile_and_build_sponsorship_checklist(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    app = _app()
    app.run()
    track = ui.WORKSPACES.list_workspaces()[0]["id"]
    citizenships = next(item for item in app.multiselect if item.label == "Citizenship(s)")
    citizenships.set_value(["France"]).run()
    residence = next(item for item in app.selectbox if item.label == "Country of residence")
    residence.set_value("France").run()
    next(item for item in app.button if item.label == "Save residency profile").click().run()
    assert not app.exception
    saved = ui.RESIDENCY.get(track)
    assert saved is not None and saved.citizenships == ("France",)

    job_country = next(item for item in app.selectbox if item.label == "Country of the role")
    job_country.set_value("United States").run()
    next(item for item in app.button if item.label == "Build my document checklist").click().run()
    assert not app.exception
    assert any("Pathway: Employer-sponsored work visa" in item.body for item in app.markdown)
    assert any("H-1B" in item.value for item in app.markdown)
    assert any("not legal advice" in item.body for item in app.warning)
    assert any("Verify with the official source" in item.body for item in app.markdown)


def test_free_movement_pathway_is_rendered(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    app = _app()
    app.run()
    track = ui.WORKSPACES.list_workspaces()[0]["id"]
    from tau_job_application.eligibility import ResidencyProfile
    ui.RESIDENCY.save(track, ResidencyProfile(citizenships=("France",), residence_country="France"))
    app.run()
    job_country = next(item for item in app.selectbox if item.label == "Country of the role")
    job_country.set_value("Germany").run()
    next(item for item in app.button if item.label == "Build my document checklist").click().run()
    assert not app.exception
    assert any("Free-movement bloc" in item.body for item in app.markdown)
