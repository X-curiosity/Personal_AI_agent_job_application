from streamlit.testing.v1 import AppTest


def _app(tmp_path, monkeypatch):
    from tau_job_application import ui
    from tau_job_application.monitoring import JobMonitor
    from tau_job_application.requirement_memory import RequirementMemory
    from tau_job_application.storage import LocalStore
    from tau_job_application.workspaces import WorkspaceStore

    db = tmp_path / "skill-decisions.sqlite"
    monkeypatch.setattr(ui, "STORE", LocalStore(db))
    monkeypatch.setattr(ui, "MONITOR", JobMonitor(db))
    monkeypatch.setattr(ui, "REQUIREMENT_MEMORY", RequirementMemory(db))
    monkeypatch.setattr(ui, "WORKSPACES", WorkspaceStore(db))
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=40).run()
    return ui, app


def _fill(app, *, cv: str, job: str) -> None:
    next(w for w in app.text_area if w.label == "Or paste your CV text").set_value(cv)
    next(w for w in app.text_input if w.label == "Job title").set_value("Platform Engineer")
    next(w for w in app.text_area if w.label == "Job description").set_value(job)
    next(w for w in app.button if w.label == "Analyze this job").click()
    app.run()
    app.run()  # the analyze handler saves after Overview renders; re-render the dashboard


def test_advisory_decision_model_recognises_synonyms_without_changing_the_canonical_score(tmp_path, monkeypatch):
    ui, app = _app(tmp_path, monkeypatch)
    _fill(app, cv="Name: Alex\nSkills: k8s, Python", job="Required skills: Kubernetes, Python")
    assert not app.exception

    scope = app.session_state["active_scope"]
    result = ui.WORKSPACES.thread(*scope)["analysis"]
    assert result is not None
    assert result.match.score == 60  # canonical scoring unchanged: k8s != Kubernetes

    expander_labels = [item.label for item in app.expander]
    assert "Advisory: decision-model skill matching" in expander_labels
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["Canonical coverage"] == "60%"
    assert metrics["Decision-model coverage"] == "100%"  # alias equivalence recognised
    assert metrics["Ambiguous pairs"] == "0"


def test_ambiguous_pairs_are_reported_and_jev_stays_disabled_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_URL", raising=False)
    ui, app = _app(tmp_path, monkeypatch)
    _fill(app, cv="Name: Alex\nSkills: React Native", job="Required skills: React")
    assert not app.exception

    metrics = {item.label: item.value for item in app.metric}
    assert metrics["Ambiguous pairs"] == "1"
    # Advisory only: the canonical number is still the deterministic one
    # (a single "React" requirement is scored as preferred, so the floor is 20).
    scope = app.session_state["active_scope"]
    assert ui.WORKSPACES.thread(*scope)["analysis"].match.score == 20

    jev_toggle = next(item for item in app.checkbox if item.label == "Ask Jev about ambiguous skill pairs")
    assert jev_toggle.disabled is True
    assert any("Undecided" in item.value for item in app.markdown)
