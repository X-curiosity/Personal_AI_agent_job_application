import queue
import threading

from streamlit.testing.v1 import AppTest

from tau_job_application.computer_use import RunOutcome
from tau_job_application.computer_use_ui import _ask_user, _execute
from tau_job_application.rule_based_apply import RuleBasedApplyConfig


def test_rule_based_screen_requires_identity_and_cv():
    app = AppTest.from_string("from tau_job_application.computer_use_ui import render_computer_use\nrender_computer_use()").run()
    assert not app.exception
    app.button[0].click().run()
    assert any("Provide a job URL, full name, email, and CV" in error.value for error in app.error)
    assert all(item.label != "Provider API key (session only)" for item in app.text_input)


def test_worker_callbacks_use_queues_not_streamlit_thread_state():
    requests, answers = queue.Queue(), queue.Queue()
    answers.put(True)
    assert _ask_user(requests, answers, "submit", {"method": "post"}) is True
    assert requests.get_nowait()[0] == "submit"


def test_worker_returns_outcome_and_never_needs_provider(monkeypatch):
    calls = {}
    def fake_run(config, **kwargs):
        calls["config"] = config
        kwargs["approve_submit"]("fingerprint", {"method": "post"})
        return RunOutcome("pending_approval", "waiting")
    monkeypatch.setattr("tau_job_application.computer_use_ui.run", fake_run)
    requests, answers, outcomes = queue.Queue(), queue.Queue(), queue.Queue()
    answers.put(True)
    config = RuleBasedApplyConfig(job_url="https://jobs.example.com/1", application_id="app", full_name="Synthetic", email="synthetic@example.com")
    _execute(config, requests, answers, outcomes, threading.Event())
    assert outcomes.get_nowait().status == "pending_approval"
    assert requests.get_nowait()[0] == "submit"
    assert calls["config"] == config
