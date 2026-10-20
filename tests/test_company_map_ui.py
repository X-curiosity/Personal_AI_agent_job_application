from streamlit.testing.v1 import AppTest

from tau_job_application.company_catalog import CatalogCompany, CompanyCatalogStore
from tau_job_application.hiring_index import HiringEntry, HiringIndexStore
from tau_job_application.monitoring import JobMonitor
from tau_job_application.requirement_memory import RequirementMemory
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import WorkspaceStore


def _app(tmp_path, monkeypatch):
    from tau_job_application import ui

    path = tmp_path / "map.sqlite"
    for name, store in {"WORKSPACES": WorkspaceStore(path), "STORE": LocalStore(path), "MONITOR": JobMonitor(path),
                        "REQUIREMENT_MEMORY": RequirementMemory(path)}.items():
        monkeypatch.setattr(ui, name, store)
    HiringIndexStore(path).save_run([
        HiringEntry(company_key="board:Greenhouse:figma", name="Figma", signal="live_openings",
                    team_size=1400, industry="Design", locations=None,
                    sample_locations=("San Francisco, CA, USA",),
                    source_label="Live Greenhouse board", source_url="https://boards.greenhouse.io/figma"),
        HiringEntry(company_key="yc:alpha", name="Alpha AI", signal="directory_flag",
                    team_size=30, industry="Fintech", locations="Berlin, Germany",
                    source_label="YC directory flag (unverified)", source_url="https://www.ycombinator.com/companies/alpha"),
        HiringEntry(company_key="yc:remote", name="Remote Co", signal="directory_flag",
                    team_size=12, industry="Climate", locations="Remote",
                    source_label="YC directory flag (unverified)", source_url="https://www.ycombinator.com/companies/remote"),
    ])
    CompanyCatalogStore(path).import_companies([CatalogCompany(
        source="CompaniesMarketCap", source_key="nvidia", name="NVIDIA",
        source_url="https://companiesmarketcap.com/nvidia/marketcap/",
        industry="Semiconductors", country="USA", market_cap="$5.2 T", hiring=True,
    )])
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=40)
    app.query_params["view"] = "companies"
    app.run()
    assert not app.exception
    return ui, app


def test_company_map_renders_pins_and_honest_counts(tmp_path, monkeypatch):
    ui, app = _app(tmp_path, monkeypatch)
    assert any("Hiring company map" in item.value for item in app.markdown)
    page = " ".join(item.value for item in app.markdown)
    assert "3 pinned" in page  # Figma (sample location), Alpha AI, NVIDIA
    assert "1 without a mappable location" in page  # Remote Co
    labels = [item.label for item in app.expander]
    assert "Pinned companies (3)" in labels
    assert "Not pinned (1)" in labels
    pinned = app.dataframe[0].value
    assert set(pinned["Company"]) == {"Figma", "Alpha AI", "NVIDIA"}
    assert set(pinned["Signal"]) == {"Live official board", "Directory flag (unverified)"}


def test_company_map_filters_by_stage_and_search(tmp_path, monkeypatch):
    ui, app = _app(tmp_path, monkeypatch)
    track = ui.WORKSPACES.list_workspaces()[0]["id"]
    next(item for item in app.multiselect if item.label == "Stage").set_value(["early"])
    app.run()
    assert not app.exception
    assert "1 pinned" in " ".join(item.value for item in app.markdown)
    next(item for item in app.text_input if item.label == "Company").set_value("alpha")
    app.run()
    pinned = app.dataframe[0].value
    assert list(pinned["Company"]) == ["Alpha AI"]


def test_match_filter_checkbox_needs_saved_answers(tmp_path, monkeypatch):
    ui, app = _app(tmp_path, monkeypatch)
    checkbox = next(item for item in app.checkbox if item.label == "Filter with my Match me answers")
    assert checkbox.disabled is True  # no Match me answers saved yet
