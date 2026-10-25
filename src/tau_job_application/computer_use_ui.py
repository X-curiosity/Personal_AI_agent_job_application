"""Local deterministic auto-apply with interactive final approval (no LLM)."""
from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any
from uuid import uuid4

import streamlit as st

from tau_job_application.computer_use import ComputerUseError, RunOutcome
from tau_job_application.rule_based_apply import RuleBasedApplyConfig, run, validate_custom_answers


def _ask_user(requests: queue.Queue, answers: queue.Queue, kind: str, details: Any) -> bool:
    requests.put((kind, details))
    try:
        return bool(answers.get(timeout=330))
    except queue.Empty:
        return False


def _execute(config: RuleBasedApplyConfig, requests: queue.Queue, answers: queue.Queue, outcomes: queue.Queue, cancel_event: threading.Event) -> None:
    try:
        outcome = run(
            config,
            approve_submit=lambda _fp, details: not cancel_event.is_set() and _ask_user(requests, answers, "submit", details),
            cancel_event=cancel_event,
        )
    except Exception as exc:
        if isinstance(exc, ComputerUseError):
            reason = str(exc)
        elif "executable" in str(exc).lower() and "exist" in str(exc).lower():
            reason = "Playwright Chromium is not installed; run .venv/bin/playwright install chromium"
        else:
            reason = f"Browser automation failed: {type(exc).__name__}"
        outcome = RunOutcome("cancelled" if cancel_event.is_set() else "blocked", "Cancelled by user" if cancel_event.is_set() else reason)
    outcomes.put(outcome)


def _drain_worker() -> None:
    try:
        outcome = st.session_state.computer_outcomes.get_nowait()
        st.session_state.computer_result = {"status": outcome.status, "reason": outcome.reason, "fingerprint": outcome.submit_fingerprint}
        st.session_state.computer_running = False
        st.session_state.computer_prompt = None
    except queue.Empty:
        pass
    if st.session_state.get("computer_running") and not st.session_state.get("computer_prompt"):
        try:
            kind, details = st.session_state.computer_requests.get_nowait()
            st.session_state.computer_prompt = {"kind": kind, "details": details}
        except queue.Empty:
            pass


def render_computer_use() -> None:
    st.markdown('<div class="section-kicker">Deterministic, local, reviewed</div><h1>Rule-based auto-apply</h1>', unsafe_allow_html=True)
    st.write("Automatically fill recognized fields, attach your CV, and review the completed application before one submission. No LLM, provider key, model charge, or screenshot sharing.")
    st.caption("Unknown questions, ambiguous labels, CAPTCHA, consent decisions, and employer restrictions stop the run for manual handling.")

    st.subheader("Job and applicant")
    job_url = st.text_input("Public HTTPS job URL", key="computer-job-url", placeholder="https://employer.example/jobs/123")
    left, right = st.columns(2)
    full_name = left.text_input("Full name", key="apply-full-name")
    email = right.text_input("Email", key="apply-email")
    phone = left.text_input("Phone (only if requested)", key="apply-phone")
    location = right.text_input("Current location (only if requested)", key="apply-location")
    skills = st.text_area("Skills to use when a skills field is present", key="apply-skills", placeholder="Python, SQL, Docker")
    with st.expander("Profile links and custom answers"):
        linkedin = st.text_input("LinkedIn URL", key="apply-linkedin")
        github = st.text_input("GitHub URL", key="apply-github")
        portfolio = st.text_input("Portfolio URL", key="apply-portfolio")
        custom_text = st.text_area('Custom answers as JSON, using exact field labels', value="{}", key="apply-custom", help='Example: {"Years of Python experience": "3", "Open to relocation": true}')
        form_selector = st.text_input("Form CSS selector", value="form", key="apply-form-selector", help="Use #application or another exact selector when a page has multiple forms.")
        allow_json = st.checkbox("Allow explicitly verified JSON submission for this form", key="apply-json")
    upload = st.file_uploader("CV to attach", type=["pdf", "docx", "txt", "md"], max_upload_size=10, key="computer-cv")

    if st.button("Fill application for my review", type="primary", disabled=bool(st.session_state.get("computer_running"))):
        if upload is None or not job_url.strip() or not full_name.strip() or not email.strip():
            st.error("Provide a job URL, full name, email, and CV.")
        else:
            try:
                custom = json.loads(custom_text)
                custom = validate_custom_answers(custom)
                content = upload.getvalue()
                if not content or upload.size > 10 * 1024 * 1024:
                    raise ValueError("CV must be non-empty and no larger than 10 MB. Scanned PDFs are accepted because the file is attached directly.")
                config = RuleBasedApplyConfig(
                    job_url=job_url.strip(), application_id=str(uuid4()), form_selector=form_selector,
                    full_name=full_name.strip(), email=email.strip(), phone=phone.strip(), location=location.strip(),
                    skills=skills.strip(), links={key: value.strip() for key, value in {"linkedin": linkedin, "github": github, "portfolio": portfolio}.items() if value.strip()},
                    custom_answers=custom, cv_file_bytes=content, cv_file_name=upload.name, cv_required=True,
                    allow_json_submission=allow_json,
                )
                st.session_state.computer_requests = queue.Queue()
                st.session_state.computer_answers = queue.Queue()
                st.session_state.computer_outcomes = queue.Queue()
                st.session_state.computer_running = True
                st.session_state.computer_prompt = None
                st.session_state.computer_result = None
                st.session_state.computer_cancel = threading.Event()
                worker = threading.Thread(target=_execute, args=(config, st.session_state.computer_requests, st.session_state.computer_answers, st.session_state.computer_outcomes, st.session_state.computer_cancel), daemon=True)
                st.session_state.computer_worker = worker
                worker.start()
                st.rerun()
            except Exception as exc:
                st.error(f"Could not start the application: {exc}")

    if st.session_state.get("computer_running"):
        _drain_worker()
        prompt = st.session_state.get("computer_prompt")
        if prompt:
            st.warning("Review the completed form in the visible browser and the values below. Approval submits once.")
            st.json(prompt["details"], expanded=True)
            left, right = st.columns(2)
            if left.button("Approve this submission once", type="primary", key="computer-approve"):
                st.session_state.computer_answers.put(True)
                st.session_state.computer_prompt = None
                st.rerun()
            if right.button("Stop without submitting", key="computer-reject"):
                st.session_state.computer_cancel.set()
                st.session_state.computer_answers.put(False)
                st.session_state.computer_prompt = None
                st.rerun()
        else:
            st.info("Filling the local form. You will review it before submission.")
            if st.button("Stop this run", key="computer-stop-anytime"):
                st.session_state.computer_cancel.set()
                st.session_state.computer_answers.put(False)
                st.rerun()
            time.sleep(1)
            st.rerun()

    result = st.session_state.get("computer_result")
    if result:
        if result["status"] == "submitted":
            st.success(f"Submission received a successful response. Verify it with the employer. Reference: {(result.get('fingerprint') or '')[:12]}")
        elif result["status"] == "submission_unknown":
            st.warning(result["reason"])
        elif result["status"] in {"completed_without_submit", "cancelled", "pending_approval", "pending_consent"}:
            st.info(result["reason"])
        else:
            st.error(f"{result['status']}: {result['reason']}")
