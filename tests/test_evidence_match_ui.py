from streamlit.testing.v1 import AppTest


def test_completed_project_evidence_is_saved_only_after_candidate_confirmation(tmp_path, monkeypatch):
    from tau_job_application import ui
    from tau_job_application.evidence_match_store import EvidenceMatchStore
    from tau_job_application.monitoring import JobMonitor
    from tau_job_application.requirement_memory import RequirementMemory
    from tau_job_application.storage import LocalStore
    from tau_job_application.workspaces import WorkspaceStore

    db = tmp_path / "evidence-ui.sqlite"
    workspace_store = WorkspaceStore(db)
    monkeypatch.setattr(ui, "STORE", LocalStore(db))
    monkeypatch.setattr(ui, "MONITOR", JobMonitor(db))
    monkeypatch.setattr(ui, "REQUIREMENT_MEMORY", RequirementMemory(db))
    monkeypatch.setattr(ui, "WORKSPACES", workspace_store)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30).run()

    def widget(kind, label):
        return next(item for item in getattr(app, kind) if item.label == label)

    widget("text_area", "Or paste your CV text").set_value("Name: Alex\nSkills: Python")
    widget("text_input", "Job title").set_value("Platform Engineer")
    widget("text_input", "Company").set_value("Example")
    widget("text_area", "Job description").set_value("Required skills: Python, Docker")
    widget("button", "Analyze this job").click()
    app.run()
    assert not app.exception

    widget("text_input", "Completed project title").set_value("Dockerized service")
    widget("text_area", "Your concrete contribution").set_value(
        "Designed the container image and implemented the deployment workflow."
    )
    widget("text_input", "Skills demonstrated").set_value("Docker")
    widget("text_input", "Proof link or source reference").set_value("https://example.test/demo")
    widget("text_area", "Observable outcome or test").set_value("The end-to-end deployment check passes.")
    widget("checkbox", "I confirm this is completed work, my contribution is accurate, and I can discuss the proof.").check()
    widget("button", "Save completed project evidence").click()
    app.run()
    assert not app.exception

    workspace_id, thread_id = app.session_state["active_scope"]
    saved = EvidenceMatchStore(db).list_projects(workspace_id, thread_id)
    assert [(project.title, project.skills) for project in saved] == [("Dockerized service", ("Docker",))]
    analysis = workspace_store.thread(workspace_id, thread_id)["analysis"]
    assessment = ui.calculate_evidence_match(analysis.candidate, analysis.job, saved)
    assert ui._standout_plans(analysis, assessment) == []
