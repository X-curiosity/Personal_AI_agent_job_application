from streamlit.testing.v1 import AppTest


def test_switch_threads_directions_and_restore_chats(tmp_path, monkeypatch):
    from tau_job_application import ui
    from tau_job_application.storage import LocalStore
    from tau_job_application.monitoring import JobMonitor
    from tau_job_application.requirement_memory import RequirementMemory
    from tau_job_application.workspaces import WorkspaceStore

    db = tmp_path / "workspace.sqlite"
    store = WorkspaceStore(db)
    monkeypatch.setattr(ui, "STORE", LocalStore(db))
    monkeypatch.setattr(ui, "MONITOR", JobMonitor(db))
    monkeypatch.setattr(ui, "REQUIREMENT_MEMORY", RequirementMemory(db))
    monkeypatch.setattr(ui, "WORKSPACES", store)
    script = "from tau_job_application.ui import main\nmain()"
    app = AppTest.from_string(script, default_timeout=30).run()

    def widget(kind, label):
        return next(w for w in getattr(app, kind) if w.label == label)

    widget("text_area", "Or paste your CV text").set_value("Name: Alex\nSkills: C++, Python")
    widget("text_input", "Job title").set_value("Firmware Engineer")
    widget("text_area", "Job description").set_value("Required skills: C++, RTOS")
    widget("button", "Analyze this job").click()
    app.run()
    assert not app.exception
    primary, firmware = app.session_state["active_scope"]
    widget("button", "Save as shared profile for new Job Workspaces").click()
    app.run()
    app.chat_input[0].set_value("show skills")
    app.run()
    assert not app.exception
    assert len(store.messages(primary, firmware)) == 2
    assert "RTOS" in store.messages(primary, firmware)[1]["content"]

    # A related title gets its own blank job draft and conversation, but shared CV.
    widget("text_input", "Job workspace name").set_value("Systems Programmer")
    widget("button", "Create job workspace").click()
    app.run()
    assert not app.exception
    related = app.session_state["active_scope"][1]
    assert related != firmware
    assert widget("text_area", "Job description").value == ""
    assert widget("text_area", "Or paste your CV text").value.startswith("Name: Alex")
    assert store.messages(primary, related) == []

    # Switch directions; do not retain another thread's job or output.
    gpu = store.create_workspace("GPU Computing")
    app.run()  # Reload the selector so the newly created track is an available option.
    widget("selectbox", "Career track").select(gpu)
    app.run()
    assert not app.exception
    gpu_thread = app.session_state["active_scope"][1]
    assert widget("text_input", "Job title").value == ""
    assert app.session_state["analysis"] is None
    widget("text_input", "Job title").set_value("GPU Kernel Engineer")
    widget("text_area", "Job description").set_value("Required skills: C++, CUDA")
    widget("button", "Analyze this job").click()
    app.run()
    assert not app.exception
    assert app.session_state["analysis"].job.title == "GPU Kernel Engineer"
    assert store.messages(gpu, gpu_thread) == []

    # Original thread survives switching and a fresh browser session.
    widget("selectbox", "Career track").select(primary)
    app.run()
    widget("selectbox", "Job workspace").select(firmware)
    app.run()
    assert not app.exception
    assert widget("text_input", "Job title").value == "Firmware Engineer"
    assert "RTOS" in widget("text_area", "Job description").value
    assert app.session_state["analysis"].job.title == "Firmware Engineer"
    assert len(app.chat_message) == 2
    restarted = AppTest.from_string(script, default_timeout=30).run()
    assert not restarted.exception
    assert restarted.session_state["analysis"].job.title == "Firmware Engineer"
    assert len(restarted.chat_message) == 2

    # Editing inputs marks results stale instead of misattributing an old score.
    widget("text_area", "Job description").set_value("Required skills: FPGA")
    app.run()
    assert not app.exception
    assert app.session_state["analysis"] is None
    assert store.thread(primary, firmware)["stale"]

    from tau_job_application.parsing import parse_job_text
    app.session_state["imported_jobs"] = [parse_job_text("Required skills: Python, Linux", title="Platform Developer", company="Source Co")]
    app.run()
    next(b for b in app.button if b.key == "open-import:0").click()
    app.run()
    assert not app.exception
    assert app.session_state["active_scope"][0] == primary
    assert widget("text_input", "Job title").value == "Platform Developer"
    assert widget("text_input", "Company").value == "Source Co"
    assert app.session_state["analysis"] is None
    widget("selectbox", "Move to career track").select(gpu)
    widget("button", "Move workspace (keep its history)").click()
    app.run()
    assert not app.exception
    assert app.session_state["active_scope"][0] == gpu
    assert widget("text_input", "Job title").value == "Platform Developer"


def test_interview_rehearsal_is_saved_inside_the_selected_job_workspace(tmp_path, monkeypatch):
    """Rehearsals live in the application workspace (the job status page)."""

    from tau_job_application import ui
    from tau_job_application.application_tracker import ApplicationTrackerStore
    from tau_job_application.monitoring import JobMonitor
    from tau_job_application.pipeline import analyze_texts
    from tau_job_application.requirement_memory import RequirementMemory
    from tau_job_application.role_discovery import CompanyFacts, DiscoveredOpening
    from tau_job_application.storage import LocalStore
    from tau_job_application.workspaces import WorkspaceStore

    db = tmp_path / "interview-workspace.sqlite"
    store = WorkspaceStore(db)
    monkeypatch.setattr(ui, "STORE", LocalStore(db))
    monkeypatch.setattr(ui, "MONITOR", JobMonitor(db))
    monkeypatch.setattr(ui, "REQUIREMENT_MEMORY", RequirementMemory(db))
    monkeypatch.setattr(ui, "WORKSPACES", store)
    monkeypatch.setattr(ui, "APPLICATIONS", ApplicationTrackerStore(db))

    track = store.create_workspace("Platforms")
    result = analyze_texts("Name: Alex\nSkills: Python", "Title: Platform Engineer\nCompany: Example\nRequired skills: Python, Docker")
    draft = {
        "cv_text": result.candidate.raw_cv, "job_title": result.job.title, "company": result.job.company,
        "job_text": result.job.description, "job_url": result.job.url or "",
        "github": "", "portfolio": "", "linkedin": "", "x": "",
    }
    thread = store.create_thread(track, "Platform Engineer · Example", draft)
    store.save_analysis(track, thread, result)
    opening = DiscoveredOpening(
        title="Platform Engineer", company=CompanyFacts(name="Example"), source="Greenhouse",
        description="Required skills: Python, Docker",
        source_identifier="example", external_id="platform-1",
    )
    record = ui.APPLICATIONS.save(track, thread, opening)

    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30)
    app.query_params.update({"view": "application", "application": str(record.id)})
    app.run()
    assert not app.exception

    def widget(kind, label):
        return next(w for w in getattr(app, kind) if w.label == label)

    widget("text_area", "Your answer (type it, or transcribe an optional recording below)").set_value(
        "I built a small service, tested its critical path, and used the result to improve it."
    )
    widget("button", "Score and save this rehearsal").click()
    app.run()
    assert not app.exception

    saved = store.interview_attempts(track, thread)
    assert len(saved) == 1
    assert saved[0]["question"]
    assert saved[0]["answer"].startswith("I built a small service")


def test_match_bar_chips_and_metric_cards_navigate(tmp_path, monkeypatch):
    from tau_job_application import ui
    from tau_job_application.monitoring import JobMonitor
    from tau_job_application.requirement_memory import RequirementMemory
    from tau_job_application.storage import LocalStore
    from tau_job_application.workspaces import WorkspaceStore

    db = tmp_path / "match-nav.sqlite"
    monkeypatch.setattr(ui, "STORE", LocalStore(db))
    monkeypatch.setattr(ui, "MONITOR", JobMonitor(db))
    monkeypatch.setattr(ui, "REQUIREMENT_MEMORY", RequirementMemory(db))
    monkeypatch.setattr(ui, "WORKSPACES", WorkspaceStore(db))
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=30).run()

    def widget(kind, label):
        return next(w for w in getattr(app, kind) if w.label == label)

    widget("text_area", "Or paste your CV text").set_value("Name: Alex\nSkills: Python")
    widget("text_input", "Job title").set_value("Platform Engineer")
    widget("text_input", "Company").set_value("Example")
    widget("text_area", "Job description").set_value("Required skills: Python, Docker")
    widget("button", "Analyze this job").click()
    app.run()
    app.run()  # the Overview renders on the pass after the analysis is saved
    assert not app.exception

    # The match bar exists with clickable breakdown chips instead of a separate page.
    assert not any(t.label == "Interview lab" for t in app.tabs)
    chip = next(b for b in app.button if b.label.startswith("Skills coverage"))
    chip.click().run()
    assert not app.exception
    assert app.query_params["focus"] == ["Job brief"]

    app.query_params.clear()
    app.run()
    cv_chip = next(b for b in app.button if b.label.startswith("CV readiness"))
    cv_chip.click().run()
    assert app.query_params["focus"] == ["CV studio"]

    app.query_params.clear()
    app.run()
    interview_card = next(b for b in app.button if "Interview practice" in b.label)
    interview_card.click().run()
    assert app.query_params["view"] == ["applications"]
