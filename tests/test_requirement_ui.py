"""Exercise the real Streamlit flow without network access or real candidate data."""
from streamlit.testing.v1 import AppTest


def test_prose_review_is_visible_and_used_by_quickstart(tmp_path, monkeypatch):
    from tau_job_application import ui
    from tau_job_application.storage import LocalStore
    from tau_job_application.monitoring import JobMonitor
    from tau_job_application.requirement_memory import RequirementMemory
    from tau_job_application.workspaces import WorkspaceStore

    database = tmp_path / "test.sqlite"
    monkeypatch.setattr(ui, "WORKSPACES", WorkspaceStore(database))
    monkeypatch.setattr(ui, "STORE", LocalStore(database))
    monkeypatch.setattr(ui, "MONITOR", JobMonitor(database))
    monkeypatch.setattr(ui, "REQUIREMENT_MEMORY", RequirementMemory(database))
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30).run()
    assert not app.exception
    next(x for x in app.text_area if x.label == "Or paste your CV text").set_value("Name: Alex\nSkills: Python")
    next(x for x in app.text_area if x.label == "Job description").set_value("Experienced with Python. Docker is a plus.")
    app.run()
    assert not app.exception
    assert any(e.label == "Review inferred requirements / teach the extractor" for e in app.expander)
    next(x for x in app.checkbox if x.label == "I reviewed these interpretations against the source text").check()
    app.run()
    next(x for x in app.button if x.label == "Save corrections for this description").click()
    app.run()
    assert not app.exception
    next(x for x in app.button if x.label == "Build my plan").click()
    app.run()
    assert not app.exception
    job = app.session_state["analysis"].job
    assert {r.skill for r in job.requirements} == {"Python", "Docker"}
    assert all(r.extraction_method == "reviewed" for r in job.requirements)
