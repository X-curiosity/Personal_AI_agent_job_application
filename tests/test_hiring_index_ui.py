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
from tau_job_application.yc_directory import YCDirectoryStore, parse_yc_directory


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


def _app():
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=60)
    app.query_params["view"] = "companies"
    return app


def test_build_requires_a_startup_snapshot(tmp_path, monkeypatch):
    setup_ui(tmp_path, monkeypatch)
    app = _app()
    app.run()
    assert not app.exception
    assert any("Actively hiring index" in item.value for item in app.subheader)
    next(item for item in app.button if item.label == "Build / refresh index").click().run()
    assert any("Refresh the startup snapshot" in item.body for item in app.error)


def test_build_lists_active_hiring_companies_with_honest_signals(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    ui.YC_DIRECTORY.refresh(parse_yc_directory([
        {"slug": "alpha-ai", "name": "Alpha AI", "status": "Active", "isHiring": True,
         "industries": ["Fintech"], "all_locations": "Berlin, Germany"},
        {"slug": "beta-health", "name": "Beta Health", "status": "Active", "isHiring": True},
        {"slug": "delta-old", "name": "Delta Old", "status": "Inactive", "isHiring": True},
    ]))
    monkeypatch.setattr(ui, "fetch_public_board_openings",
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no network in tests")))
    app = _app()
    app.run()
    next(item for item in app.button if item.label == "Build / refresh index").click().run()
    assert not app.exception
    run = ui.HIRING_INDEX.run()
    assert run["entry_count"] == 2
    captions = " ".join(item.value for item in app.caption)
    assert "never scraped or automated" in captions
    table = app.dataframe[0].value
    assert set(table["Company"]) == {"Alpha AI", "Beta Health"}
    assert set(table["Signal"]) == {"Directory flag (unverified)"}
    # Signal filter isolates the live-openings bucket (empty here).
    signal = next(item for item in app.selectbox if item.label == "Signal")
    signal.select("live_openings").run()
    assert any("No companies match" in item.body for item in app.info)
