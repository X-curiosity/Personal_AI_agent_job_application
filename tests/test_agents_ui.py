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
    app.query_params["view"] = "agents"
    return app


def test_console_is_disabled_without_credentials(tmp_path, monkeypatch):
    setup_ui(tmp_path, monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    app = _app()
    app.run()
    assert not app.exception
    assert any("currently disabled" in item.body for item in app.info)
    assert not any(item.label == "Run specialist" for item in app.button)


def test_console_requires_consent_and_shows_routing_preview(tmp_path, monkeypatch):
    setup_ui(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    app = _app()
    app.run()
    assert not app.exception
    run_button = next(item for item in app.button if item.label == "Run specialist")
    assert run_button.disabled is True
    request = next(item for item in app.text_area if item.label == "Your request")
    request.set_value("Do I need a visa to apply in another country?").run()
    assert any("Eligibility advisor" in item.value for item in app.caption)
