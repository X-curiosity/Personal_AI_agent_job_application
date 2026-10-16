from streamlit.testing.v1 import AppTest

from tau_job_application.application_tracker import ApplicationTrackerStore
from tau_job_application.capital_atlas import AtlasStore
from tau_job_application.company_catalog import CompanyCatalogStore
from tau_job_application.eligibility import ResidencyStore
from tau_job_application.hiring_index import HiringIndexStore
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
        "ATLAS": AtlasStore(path), "HIRING_INDEX": HiringIndexStore(path),
    }.items():
        monkeypatch.setattr(ui, name, store)
    return ui


def test_top_nav_bar_renders_and_navigates(tmp_path, monkeypatch):
    setup_ui(tmp_path, monkeypatch)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=60)
    app.run()
    assert not app.exception
    nav = app.segmented_control[0]
    assert set(nav.options) == {"Home", "Workspace", "Role pages", "Applications", "Companies", "Eligibility", "Agent team"}
    assert nav.value == "Workspace"
    nav.set_value("Companies").run()
    assert not app.exception
    assert app.query_params["view"] == ["companies"]
    assert app.segmented_control[0].value == "Companies"


def test_programmatic_navigation_does_not_trigger_nav(tmp_path, monkeypatch):
    setup_ui(tmp_path, monkeypatch)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=60)
    app.query_params.update({"view": "role", "role": "Hardware Engineer"})
    app.run()
    assert not app.exception
    # The pill reflects the current section without hijacking the route.
    assert app.segmented_control[0].value == "Role pages"
    assert app.query_params["view"] == ["role"]


def test_no_dash_placeholders_in_metrics_and_tables(tmp_path, monkeypatch):
    setup_ui(tmp_path, monkeypatch)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=60)
    app.query_params["view"] = "companies"
    app.run()
    assert not app.exception
    rendered = " ".join(item.value for item in app.markdown if item.value)
    assert "—" not in rendered
