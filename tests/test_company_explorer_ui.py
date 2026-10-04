from streamlit.testing.v1 import AppTest


def test_profile_company_explorer_renders_an_accessible_map_and_company_picker(tmp_path, monkeypatch):
    from tau_job_application import ui
    from tau_job_application.monitoring import JobMonitor
    from tau_job_application.requirement_memory import RequirementMemory
    from tau_job_application.storage import LocalStore
    from tau_job_application.workspaces import WorkspaceStore

    db = tmp_path / "company-explorer.sqlite"
    monkeypatch.setattr(ui, "WORKSPACES", WorkspaceStore(db))
    monkeypatch.setattr(ui, "STORE", LocalStore(db))
    monkeypatch.setattr(ui, "MONITOR", JobMonitor(db))
    monkeypatch.setattr(ui, "REQUIREMENT_MEMORY", RequirementMemory(db))
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30).run()

    next(item for item in app.text_area if item.label == "Or paste your CV text").set_value(
        "Name: Maya\nSkills: Python, CUDA, PyTorch, C++"
    )
    app.run()

    assert not app.exception
    picker = next(item for item in app.selectbox if item.label == "Inspect a company's footprint")
    picker.select("NVIDIA — Santa Clara, United States")
    app.run()
    assert not app.exception
    assert "NVIDIA footprint" in " ".join(item.value for item in app.markdown if item.value)
    assert "Yokneam, Israel" in " ".join(item.value for item in app.markdown if item.value)
    charts = app.get("deck_gl_json_chart")
    assert len(charts) == 2
    chart_json = " ".join(chart.proto.json for chart in charts)
    assert "company-explorer-markers" in chart_json
    assert "company-footprint-markers" in chart_json
    assert "NVIDIA" in chart_json
