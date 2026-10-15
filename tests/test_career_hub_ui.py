from streamlit.testing.v1 import AppTest

from tau_job_application.application_tracker import ApplicationTrackerStore
from tau_job_application.career_hub import HubStore
from tau_job_application.company_catalog import CatalogCompany, CompanyCatalogStore
from tau_job_application.monitoring import JobMonitor
from tau_job_application.requirement_memory import RequirementMemory
from tau_job_application.role_discovery import CompanyFacts, DiscoveredOpening, RoleDiscoveryStore
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import WorkspaceStore


def setup_ui(tmp_path, monkeypatch):
    from tau_job_application import ui
    path = tmp_path / "portal.sqlite"
    for name, store in {"WORKSPACES": WorkspaceStore(path), "STORE": LocalStore(path), "MONITOR": JobMonitor(path),
                        "REQUIREMENT_MEMORY": RequirementMemory(path), "ROLE_DISCOVERY": RoleDiscoveryStore(path)}.items():
        monkeypatch.setattr(ui, name, store)
    return ui


def test_onboarding_supports_multiple_fields_and_custom_roles(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30)
    app.query_params["view"] = "career"
    app.run()
    next(item for item in app.multiselect if item.label == "1 · Fields that interest you").set_value(["Engineering", "Finance"]).run()
    next(item for item in app.multiselect if item.label == "2 · Go a little deeper").set_value(["Electrical engineering", "Venture capital"]).run()
    next(item for item in app.multiselect if item.label == "3 · Roles you would like to explore").set_value(["Hardware Engineer", "Venture Capital Analyst"])
    next(item for item in app.button if item.label == "Build my role pages").click().run()
    assert not app.exception
    track = ui.WORKSPACES.list_workspaces()[0]["id"]
    assert len(HubStore(ui.WORKSPACES.path).interests(track).roles) == 2
    assert any(item.label == "Explore Hardware Engineer" for item in app.button)


def test_application_documents_score_and_drafts_are_scoped_and_persisted(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    track = ui.WORKSPACES.create_workspace("Hardware")
    opening = DiscoveredOpening(title="Hardware Engineer", company=CompanyFacts(name="Example Co"), source="Ashby",
                                source_url="https://jobs.ashbyhq.com/example/job", description="Required skills: Python, C++")
    thread = ui._create_discovered_job_workspace(track, opening)
    record = ApplicationTrackerStore(ui.WORKSPACES.path).save(track, thread, opening)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30)
    app.query_params.update({"view": "application", "application": record.id})
    app.run()
    assert not app.exception
    next(item for item in app.text_area if item.label == "CV or factual background").set_value("Name: Alex Example\nSkills: Python\nExperience: Built a tested sensor prototype.").run()
    next(item for item in app.multiselect if item.label == "Skills you can substantiate for this application").set_value(["Python"])
    next(item for item in app.text_area if item.label == "Motivation letter").set_value("My role-specific motivation letter.")
    next(item for item in app.button if item.label == "Save documents & assess fit").click().run()
    assert not app.exception
    assert any(item.label == "CV requirement coverage" for item in app.metric)
    assert HubStore(ui.WORKSPACES.path).documents(track, thread)["letter"] == "My role-specific motivation letter."
    next(item for item in app.button if item.label == "Create reviewable CV & letter drafts").click().run()
    assert not app.exception
    assert "Dear Example Co" in next(item for item in app.text_area if item.label == "Motivation letter").value
    assert "Built a tested sensor prototype" in HubStore(ui.WORKSPACES.path).documents(track, thread)["resume"]
    assert ApplicationTrackerStore(ui.WORKSPACES.path).get(track, record.id).progress.stage.value == "saved"


def test_opening_role_loads_cluster_and_creates_a_dedicated_application(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    calls = []
    def fake_fetch(source, identifier, *, company):
        calls.append(company)
        return [{"title": "Hardware Engineer", "source": source, "source_id": "hardware-1", "board_identifier": identifier,
                 "url": "https://jobs.ashbyhq.com/openai/hardware-1", "description": "Required skills: Python, C++", "location": "San Francisco"}] if company == "OpenAI" else []
    monkeypatch.setattr(ui, "fetch_public_board_openings", fake_fetch)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30)
    app.query_params.update({"view": "role", "role": "Hardware Engineer"})
    app.run()
    assert not app.exception
    assert "OpenAI" in calls
    next(item for item in app.button if item.label == "Open application workspace").click().run()
    assert not app.exception
    assert app.query_params["view"] == ["application"]
    track = ui.WORKSPACES.list_workspaces()[0]["id"]
    record = ApplicationTrackerStore(ui.WORKSPACES.path).list_records(track)[0]
    assert ui.WORKSPACES.thread(track, record.thread_id)["draft"]["job_url"] == record.opening.source_url
    assert record.progress.stage.value == "saved"


def test_company_database_renders_sourced_records_without_remote_logo_request(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    CompanyCatalogStore(ui.WORKSPACES.path).import_companies([CatalogCompany(
        source="YC community API", source_key="example-hardware",
        source_url="https://www.ycombinator.com/companies/example-hardware",
        name="Example Hardware", company_type="Startup", industry="Industrials",
        hiring=True, logo_url="https://images.example.com/logo.png",
    )])
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30)
    app.query_params["view"] = "companies"
    app.run()
    assert not app.exception
    assert any(item.value == "Example Hardware" for item in app.subheader)
    assert next(item for item in app.checkbox if item.label == "Load remote company logos").value is False
    assert any(item.label == "Verify and save board" for item in app.button)
