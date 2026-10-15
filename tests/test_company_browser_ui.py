from streamlit.testing.v1 import AppTest

from tau_job_application.application_tracker import ApplicationTrackerStore
from tau_job_application.capital_atlas import AtlasStore
from tau_job_application.company_catalog import CompanyCatalogStore
from tau_job_application.eligibility import ResidencyStore
from tau_job_application.monitoring import JobMonitor
from tau_job_application.requirement_memory import RequirementMemory
from tau_job_application.role_discovery import RoleDiscoveryStore
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import WorkspaceStore
from tau_job_application.yc_directory import YCDirectoryStore, parse_yc_directory

ATLAS_FIXTURE_JS = """
;var a=[{rank:1,name:`Foo Systems`,ticker:`FOO`,value:1566,country:`USA`,
source:`https://companiesmarketcap.com/foo/marketcap/`,ownership:`Public`,
website:`https://www.foo.example.com`,description:`Foo builds example infrastructure.`,
industry:`Technology`,subIndustry:`Semiconductors`},
{rank:2,name:`Bar Group`,value:42,country:`Germany`,ownership:`Private`,
source:`https://example.com/bar`,website:`https://bar.example.com`,description:`Bar invests.`}];
"""


def setup_ui(tmp_path, monkeypatch):
    from tau_job_application import ui
    path = tmp_path / "portal.sqlite"
    for name, store in {
        "WORKSPACES": WorkspaceStore(path), "STORE": LocalStore(path), "MONITOR": JobMonitor(path),
        "REQUIREMENT_MEMORY": RequirementMemory(path), "ROLE_DISCOVERY": RoleDiscoveryStore(path),
        "YC_DIRECTORY": YCDirectoryStore(path), "RESIDENCY": ResidencyStore(path),
        "COMPANY_CATALOG": CompanyCatalogStore(path), "APPLICATIONS": ApplicationTrackerStore(path),
        "ATLAS": AtlasStore(path),
    }.items():
        monkeypatch.setattr(ui, name, store)
    return ui


def _seed_startups(ui):
    ui.YC_DIRECTORY.refresh(parse_yc_directory([
        {"slug": "alpha-ai", "name": "Alpha AI", "status": "Active", "isHiring": True,
         "one_liner": "AI tooling", "small_logo_thumb_url": "https://img.example.com/alpha.png"},
        {"slug": "beta-health", "name": "Beta Health", "status": "Active", "isHiring": False,
         "one_liner": "Clinic software"},
        {"slug": "gamma-pay", "name": "Gamma Pay", "status": "Acquired", "isHiring": True},
    ]))


def _seed_atlas(ui):
    from tau_job_application.capital_atlas import parse_atlas_companies
    ui.ATLAS.refresh(parse_atlas_companies(ATLAS_FIXTURE_JS))


def _app(script_body: str):
    return AppTest.from_string(script_body, default_timeout=60)


def test_startup_browser_empty_snapshot_state(tmp_path, monkeypatch):
    setup_ui(tmp_path, monkeypatch)
    app = _app(
        "import tau_job_application.ui as ui\n"
        "from tau_job_application.company_browser_ui import render_company_browser\n"
        "render_company_browser(ui, role='Hardware Engineer', key_prefix='t')"
    )
    app.run()
    assert not app.exception
    assert any("No startup snapshot yet" in item.value for item in app.caption)
    assert any("Refresh the startup snapshot once" in item.body for item in app.info)


def test_startup_browser_cards_filters_and_logos_opt_in(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    _seed_startups(ui)
    app = _app(
        "import tau_job_application.ui as ui\n"
        "from tau_job_application.company_browser_ui import render_company_browser\n"
        "render_company_browser(ui, role='Hardware Engineer', key_prefix='t')"
    )
    app.run()
    assert not app.exception
    bodies = [item.value for item in app.markdown]
    # Default filters: Active + hiring only → only Alpha AI is shown.
    assert any("Alpha AI" in body for body in bodies)
    assert not any("Beta Health" in body for body in bodies)
    assert not any("Gamma Pay" in body for body in bodies)
    # Logos are opt-in: no remote image is rendered by default.
    assert not any("img.example.com" in body for body in bodies)
    logo_box = next(item for item in app.checkbox if "logos" in item.label.casefold())
    logo_box.set_value(True).run()
    assert not app.exception
    assert any("img.example.com" in item.value for item in app.markdown)


def test_startup_browser_save_selected_imports_lead(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    _seed_startups(ui)
    app = _app(
        "import tau_job_application.ui as ui\n"
        "from tau_job_application.company_browser_ui import render_company_browser\n"
        "render_company_browser(ui, key_prefix='t')"
    )
    app.run()
    next(item for item in app.checkbox if item.key == "t:yc-save:alpha-ai").set_value(True).run()
    next(item for item in app.button if "selected to company database" in item.label).click().run()
    assert not app.exception
    rows = ui.COMPANY_CATALOG.list_companies()
    assert len(rows) == 1 and rows[0]["company"].name == "Alpha AI"
    assert rows[0]["company"].logo_url == "https://img.example.com/alpha.png"


def test_big_company_browser_cards_and_filters(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    _seed_atlas(ui)
    app = _app(
        "import tau_job_application.ui as ui\n"
        "from tau_job_application.company_browser_ui import _big_company_browser\n"
        "_big_company_browser(ui, 't')"
    )
    app.run()
    assert not app.exception
    bodies = [item.value for item in app.markdown]
    assert any("Foo Systems" in body and "$1.6T" in body for body in bodies)
    assert any("Bar Group" in body for body in bodies)
    # No remote logo without opt-in; opt-in derives the logo from the website domain.
    assert not any("logo.clearbit.com" in body for body in bodies)
    logo_box = next(item for item in app.checkbox if "logos" in item.label.casefold())
    logo_box.set_value(True).run()
    assert any("https://logo.clearbit.com/foo.example.com" in item.value for item in app.markdown)
    # Save a big company into the database.
    next(item for item in app.checkbox if item.key == "t:atlas-save:bar-group").set_value(True).run()
    next(item for item in app.button if "selected to company database" in item.label).click().run()
    assert not app.exception
    rows = ui.COMPANY_CATALOG.list_companies()
    assert len(rows) == 1 and rows[0]["company"].name == "Bar Group"
    assert rows[0]["company"].source == "Global Capital Atlas"


def test_browser_offers_startup_or_big_company_choice(tmp_path, monkeypatch):
    setup_ui(tmp_path, monkeypatch)
    app = _app(
        "import tau_job_application.ui as ui\n"
        "from tau_job_application.company_browser_ui import render_company_browser\n"
        "render_company_browser(ui, key_prefix='t')"
    )
    app.run()
    assert not app.exception
    assert app.segmented_control and set(app.segmented_control[0].options) == {"Startups", "Big companies"}
