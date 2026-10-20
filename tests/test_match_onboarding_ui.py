from streamlit.testing.v1 import AppTest

from tau_job_application.career_hub import HubStore
from tau_job_application.company_catalog import CatalogCompany, CompanyCatalogStore
from tau_job_application.hiring_index import HiringEntry, HiringIndexStore
from tau_job_application.monitoring import JobMonitor
from tau_job_application.requirement_memory import RequirementMemory
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import WorkspaceStore


def _app(tmp_path, monkeypatch):
    from tau_job_application import ui

    path = tmp_path / "match.sqlite"
    for name, store in {"WORKSPACES": WorkspaceStore(path), "STORE": LocalStore(path), "MONITOR": JobMonitor(path),
                        "REQUIREMENT_MEMORY": RequirementMemory(path)}.items():
        monkeypatch.setattr(ui, name, store)
    hiring = HiringIndexStore(path)
    hiring.save_run([
        HiringEntry(company_key="board:Greenhouse:figma", name="Figma", signal="live_openings",
                    team_size=1400, industry="Design", locations="San Francisco, USA",
                    source_label="Live Greenhouse board", source_url="https://boards.greenhouse.io/figma"),
        HiringEntry(company_key="yc:alpha", name="Alpha AI", signal="directory_flag",
                    team_size=30, industry="Fintech", locations="Berlin, Germany",
                    source_label="YC directory flag (unverified)", source_url="https://www.ycombinator.com/companies/alpha"),
    ])
    CompanyCatalogStore(path).import_companies([CatalogCompany(
        source="CompaniesMarketCap", source_key="nvidia", name="NVIDIA",
        source_url="https://companiesmarketcap.com/nvidia/marketcap/",
        industry="Semiconductors", country="USA", market_cap="$5.2 T", hiring=True,
    )])
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=40)
    app.query_params["view"] = "match"
    app.run()
    assert not app.exception
    return ui, app


def _continue(app):
    app.run()  # apply widget values so step validation recomputes
    next(item for item in app.button if item.label == "Continue →").click()
    app.run()


def test_guided_flow_narrows_the_count_and_builds_role_pages(tmp_path, monkeypatch):
    ui, app = _app(tmp_path, monkeypatch)
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["Companies hiring that fit"] == "3"

    # Step 1: role areas (never narrows the company count, by design).
    next(item for item in app.multiselect if item.label == "Role areas").set_value(["Engineering"])
    _continue(app)
    assert {item.label: item.value for item in app.metric}["Companies hiring that fit"] == "3"

    # Step 2: experience.
    next(item for item in app.radio if item.label == "Experience").set_value("3_5")
    _continue(app)

    # Step 3: work style + country Germany → only Alpha AI remains.
    next(item for item in app.multiselect if item.label == "Work styles").set_value(["remote"])
    next(item for item in app.radio if item.label == "Location").set_value("country")
    app.run()
    next(item for item in app.text_input if item.label == "Country").set_value("Germany")
    _continue(app)
    assert {item.label: item.value for item in app.metric}["Companies hiring that fit"] == "1"

    # Steps 4 and 5 are skippable ("any").
    next(item for item in app.button if item.label == "Skip — any").click()
    app.run()
    next(item for item in app.button if item.label == "Skip — any").click()
    app.run()
    assert not app.exception

    # Finish: summary and role-page creation.
    assert any("1 hiring companies fit" in item.body for item in app.success)
    table = app.dataframe[0].value
    assert list(table["Company"]) == ["Alpha AI"]
    next(item for item in app.button if item.label == "Build role pages from my role areas").click()
    app.run()
    assert not app.exception
    track = ui.WORKSPACES.list_workspaces()[0]["id"]
    interests = HubStore(ui.WORKSPACES.path).interests(track)
    assert "Engineering" in interests.fields
    assert interests.roles  # role suggestions were generated from the field
    assert app.query_params["view"] == ["career"]


def test_stage_filter_uses_honest_basis_and_edit_restarts(tmp_path, monkeypatch):
    ui, app = _app(tmp_path, monkeypatch)
    next(item for item in app.multiselect if item.label == "Role areas").set_value(["Engineering"])
    _continue(app)
    next(item for item in app.radio if item.label == "Experience").set_value("lt1")
    _continue(app)
    next(item for item in app.multiselect if item.label == "Work styles").set_value(["hybrid"])
    _continue(app)

    # Stage step: picking "Early startup" leaves only Alpha AI (team ~30).
    next(item for item in app.multiselect if item.label == "Company stages").set_value(["early"])
    _continue(app)
    assert {item.label: item.value for item in app.metric}["Companies hiring that fit"] == "1"
    next(item for item in app.button if item.label == "Skip — any").click()
    app.run()
    assert any("team ~30" in str(cell) for cell in app.dataframe[0].value["Stage"])

    next(item for item in app.button if item.label == "Edit my answers").click()
    app.run()
    assert any(item.label == "Role areas" for item in app.multiselect)


def test_continue_is_blocked_until_required_answers(tmp_path, monkeypatch):
    ui, app = _app(tmp_path, monkeypatch)
    button = next(item for item in app.button if item.label == "Continue →")
    assert button.disabled is True  # no role area picked yet
