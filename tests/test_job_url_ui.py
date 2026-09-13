from streamlit.testing.v1 import AppTest

from tau_job_application.models import JobPosting, JobRequirement


def test_quickstart_reads_job_url_and_populates_fields(tmp_path, monkeypatch):
    from tau_job_application import ui
    from tau_job_application.storage import LocalStore
    from tau_job_application.monitoring import JobMonitor
    from tau_job_application.requirement_memory import RequirementMemory
    from tau_job_application.workspaces import WorkspaceStore

    db = tmp_path / "ui.sqlite"
    monkeypatch.setattr(ui, "WORKSPACES", WorkspaceStore(db))
    monkeypatch.setattr(ui, "STORE", LocalStore(db))
    monkeypatch.setattr(ui, "MONITOR", JobMonitor(db))
    monkeypatch.setattr(ui, "REQUIREMENT_MEMORY", RequirementMemory(db))
    monkeypatch.setattr(ui, "fetch_job_url", lambda url: JobPosting(
        title="GPU Engineer", company="Acme", url=url,
        description="Experienced with CUDA and C++.",
        requirements=[JobRequirement(skill="CUDA", required=True, evidence_id="job-cuda")],
        evidence=[],
    ))
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30).run()
    next(x for x in app.text_area if x.label == "Or paste your CV text").set_value("Name: Alex\nSkills: C++")
    next(x for x in app.text_input if x.label == "Job description URL").set_value("https://careers.acme.example/gpu")
    app.run()
    next(x for x in app.button if x.label == "Read job URL").click()
    app.run()
    assert not app.exception
    assert next(x for x in app.text_input if x.label == "Job title").value == "GPU Engineer"
    assert next(x for x in app.text_input if x.label == "Company").value == "Acme"
    assert "Experienced with CUDA" in next(x for x in app.text_area if x.label == "Job description").value
