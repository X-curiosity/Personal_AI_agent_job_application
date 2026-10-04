from streamlit.testing.v1 import AppTest


def test_role_discovery_renders_role_like_openings_filters_and_role_locations(tmp_path, monkeypatch):
    from tau_job_application import ui
    from tau_job_application.monitoring import JobMonitor
    from tau_job_application.requirement_memory import RequirementMemory
    from tau_job_application.role_discovery import RoleDiscoveryStore
    from tau_job_application.storage import LocalStore
    from tau_job_application.workspaces import WorkspaceStore

    database = tmp_path / "role-market.sqlite"
    monkeypatch.setattr(ui, "WORKSPACES", WorkspaceStore(database))
    monkeypatch.setattr(ui, "STORE", LocalStore(database))
    monkeypatch.setattr(ui, "MONITOR", JobMonitor(database))
    monkeypatch.setattr(ui, "REQUIREMENT_MEMORY", RequirementMemory(database))
    monkeypatch.setattr(ui, "ROLE_DISCOVERY", RoleDiscoveryStore(database))

    def fake_fetch(source: str, identifier: str, *, company: str):
        if company == "Figma":
            return [{
                "source": source,
                "source_id": "figma-backend-1",
                "board_identifier": identifier,
                "company": company,
                "title": "Backend Engineer",
                "location": "San Francisco, CA • New York, NY • United States",
                "url": "https://boards.greenhouse.io/figma/jobs/backend-1",
                "description": "Build Python services.",
                "published_at": "2026-10-04T08:00:00Z",
                "work_mode": "Hybrid",
            }]
        if company == "Mistral AI":
            return [{
                "source": source,
                "source_id": "mistral-platform-1",
                "board_identifier": identifier,
                "company": company,
                "title": "Platform Engineer",
                "location": "Paris, France",
                "url": "https://jobs.lever.co/mistral/platform-1",
                "description": "Build Python infrastructure.",
                "published_at": "2026-10-04T08:00:00Z",
                "work_mode": "On-site",
            }]
        return []

    monkeypatch.setattr(ui, "fetch_public_board_openings", fake_fetch)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30).run()

    next(item for item in app.text_input if item.label == "Role to explore").set_value("Backend Engineer")
    next(item for item in app.button if item.label == "Discover matching openings").click()
    app.run()

    assert not app.exception
    rendered = " ".join(item.value for item in app.markdown if item.value)
    captions = " ".join(item.value for item in app.caption if item.value)
    assert "Backend Engineer · Figma" in rendered
    assert "Platform Engineer · Mistral AI" in rendered
    assert "San Francisco, CA • New York, NY • United States" in captions
    assert "Paris, France" in captions
    assert "not headquarters" in captions
    location_picker = next(item for item in app.selectbox if item.label == "Inspect a company's role locations")
    location_picker.select("Mistral AI")
    app.run()
    chart_json = " ".join(chart.proto.json for chart in app.get("deck_gl_json_chart"))
    assert "role-location-markers" in chart_json
    assert "Paris" in chart_json

    location_picker = next(item for item in app.selectbox if item.label == "Inspect a company's role locations")
    location_picker.select("Figma")
    app.run()
    chart_json = " ".join(chart.proto.json for chart in app.get("deck_gl_json_chart"))
    assert "San Francisco, CA" in chart_json
    assert "New York, NY" in chart_json

    company_type = next(item for item in app.multiselect if item.label == "Company type")
    company_type.set_value(["Startup"])
    app.run()
    rendered = " ".join(item.value for item in app.markdown if item.value)
    assert "Platform Engineer · Mistral AI" in rendered
    assert "Backend Engineer · Figma" not in rendered


def test_role_discovery_keeps_last_successful_board_when_every_feed_fails(tmp_path, monkeypatch):
    from tau_job_application import ui
    from tau_job_application.monitoring import JobMonitor
    from tau_job_application.requirement_memory import RequirementMemory
    from tau_job_application.role_discovery import RoleDiscoveryStore
    from tau_job_application.storage import LocalStore
    from tau_job_application.workspaces import WorkspaceStore

    database = tmp_path / "role-market-failure.sqlite"
    monkeypatch.setattr(ui, "WORKSPACES", WorkspaceStore(database))
    monkeypatch.setattr(ui, "STORE", LocalStore(database))
    monkeypatch.setattr(ui, "MONITOR", JobMonitor(database))
    monkeypatch.setattr(ui, "REQUIREMENT_MEMORY", RequirementMemory(database))
    monkeypatch.setattr(ui, "ROLE_DISCOVERY", RoleDiscoveryStore(database))

    def successful_fetch(source: str, identifier: str, *, company: str):
        return [{
            "source": source,
            "source_id": f"{company}-1",
            "board_identifier": identifier,
            "company": company,
            "title": "Backend Engineer",
            "location": "Paris, France",
            "url": f"https://jobs.example/{company}",
            "description": "Build Python services.",
            "published_at": "2026-10-04T08:00:00Z",
            "work_mode": "Hybrid",
        }]

    monkeypatch.setattr(ui, "fetch_public_board_openings", successful_fetch)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30).run()
    next(item for item in app.text_input if item.label == "Role to explore").set_value("Backend Engineer")
    next(item for item in app.button if item.label == "Discover matching openings").click()
    app.run()

    def failed_fetch(*args, **kwargs):
        raise RuntimeError("temporary board outage")

    monkeypatch.setattr(ui, "fetch_public_board_openings", failed_fetch)
    next(item for item in app.button if item.label == "Discover matching openings").click()
    app.run()

    rendered = " ".join(item.value for item in app.markdown if item.value)
    warnings = " ".join(item.value for item in app.warning if item.value)
    assert "Backend Engineer · Figma" in rendered
    assert "No registered feed could be refreshed" in warnings
    assert "last successful opportunity board is still shown" in warnings
