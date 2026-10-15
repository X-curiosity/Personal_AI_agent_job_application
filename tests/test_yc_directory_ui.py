from streamlit.testing.v1 import AppTest

from tau_job_application.application_tracker import ApplicationTrackerStore
from tau_job_application.company_catalog import CompanyCatalogStore
from tau_job_application.eligibility import ResidencyStore
from tau_job_application.monitoring import JobMonitor
from tau_job_application.requirement_memory import RequirementMemory
from tau_job_application.role_discovery import RoleDiscoveryStore
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import WorkspaceStore
from tau_job_application.yc_directory import YCDirectoryStore, parse_yc_directory


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


def _seed(ui):
    ui.YC_DIRECTORY.refresh(parse_yc_directory([
        {"slug": "alpha-ai", "name": "Alpha AI", "status": "Active", "isHiring": True, "industries": ["Fintech"]},
        {"slug": "beta-health", "name": "Beta Health", "status": "Active", "isHiring": False},
        {"slug": "gamma-pay", "name": "Gamma Pay", "status": "Acquired", "isHiring": True},
    ]))


def _app(view_params):
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=60)
    app.query_params.update(view_params)
    return app


def test_empty_snapshot_shows_explicit_state(tmp_path, monkeypatch):
    setup_ui(tmp_path, monkeypatch)
    app = _app({"view": "yc"})
    app.run()
    assert not app.exception
    assert any("No directory snapshot yet" in item.value for item in app.caption)
    assert any("Refresh the snapshot once" in item.body for item in app.info)


def test_url_filters_seed_the_vclense_style_query(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    _seed(ui)
    app = _app({"view": "yc", "status": "Active", "flags": "hiring"})
    app.run()
    assert not app.exception
    status_widget = next(item for item in app.multiselect if item.label == "Status")
    assert status_widget.value == ["Active"]
    hiring_widget = next(item for item in app.checkbox if item.label == "Hiring only")
    assert hiring_widget.value is True
    # Only the active + hiring company is listed.
    subheaders = [item.value for item in app.subheader]
    assert "Alpha AI" in subheaders
    assert "Beta Health" not in subheaders
    assert "Gamma Pay" not in subheaders


def test_saving_selection_imports_reviewed_leads(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    _seed(ui)
    app = _app({"view": "yc"})
    app.run()
    assert not app.exception
    save_box = next(item for item in app.checkbox if item.key == "yc-save:alpha-ai")
    save_box.set_value(True).run()
    button = next(item for item in app.button if "selected to company database" in item.label)
    button.click().run()
    assert not app.exception
    rows = ui.COMPANY_CATALOG.list_companies()
    assert len(rows) == 1
    assert rows[0]["company"].name == "Alpha AI"
    assert rows[0]["company"].source == "YC community API"
