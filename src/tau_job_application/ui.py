"""Minimalist local Streamlit UI for the evidence-first job-readiness workflow."""

from __future__ import annotations

import os
import hashlib
from pathlib import Path
import tempfile

import streamlit as st

from tau_job_application.career import contact_research_plan, parse_contact_leads
from tau_job_application.interview import build_interview_questions, evaluate_answer, transcribe_openai_audio
from tau_job_application.official_sources import (
    fetch_linkedin_authorized_identity,
    fetch_smartrecruiters_postings,
    fetch_x_recent_posts,
    import_contact_export,
    import_job_export,
)
from tau_job_application.monitoring import JobMonitor
from tau_job_application.parsing import KNOWN_SKILLS, load_document
from tau_job_application.requirement_memory import RequirementMemory, document_key
from tau_job_application.requirements import extract_requirements, save_requirement_review
from tau_job_application.pipeline import analyze_texts, render_markdown
from tau_job_application.sources import enrich_github_profile, fetch_greenhouse_jobs, fetch_lever_jobs, fetch_recruitee_jobs
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import PROFILE_FIELDS, WorkspaceStore
from tau_job_application.workspace_ui import choose_scope, draft_key, show_chat, show_direction


def _project_root() -> Path:
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    return Path.home() / ".job-readiness-agent"


ROOT = _project_root()
STORE = LocalStore(ROOT / ".job_assistant" / "assistant.sqlite")
MONITOR = JobMonitor(ROOT / ".job_assistant" / "assistant.sqlite")
REQUIREMENT_MEMORY = RequirementMemory(ROOT / ".job_assistant" / "assistant.sqlite")
WORKSPACES = WorkspaceStore(ROOT / ".job_assistant" / "assistant.sqlite")


STYLES = """
<style>
.block-container {padding-top: 2rem; padding-bottom: 2rem;}
.metric-card {background: #f8f9fa; border-radius: 12px; padding: 16px; text-align: center; border: 1px solid #e9ecef;}
.metric-label {font-size: 0.85rem; color: #6c757d; margin-bottom: 4px;}
.metric-value {font-size: 2rem; font-weight: 700; color: #212529;}
</style>
"""


def main() -> None:
    st.set_page_config(page_title="Job Readiness Agent", page_icon="🎯", layout="wide")
    st.markdown(STYLES, unsafe_allow_html=True)
    st.title("🎯 Job Readiness Agent")
    st.caption("Explore career directions, compare related roles, and keep a separate plan and conversation for each target job.")
    workspace_id, thread_id = choose_scope(WORKSPACES)
    quickstart, direction, conversation, opportunities, interview = st.tabs([
        "🚀 Quick start", "🧭 Direction overview", "💬 Conversation", "🔎 Opportunities & contacts", "🎙️ Interview practice"])
    with quickstart:
        _quickstart(workspace_id, thread_id)
    with direction:
        show_direction(WORKSPACES, workspace_id)
    with conversation:
        show_chat(WORKSPACES, workspace_id, thread_id)
    with opportunities:
        _opportunities()
    with interview:
        _interview()


def _quickstart(workspace_id: str, thread_id: str) -> None:
    thread = WORKSPACES.thread(workspace_id, thread_id)
    draft = thread["draft"]
    if st.session_state.pop(f"refresh-profile:{thread_id}", False):
        draft.update(WORKSPACES.shared_profile())
        for field in PROFILE_FIELDS:
            st.session_state[draft_key(thread_id, field)] = draft[field]
        WORKSPACES.save_draft(workspace_id, thread_id, draft)
    st.caption(f"Job thread: {thread['name']}. Text inputs auto-save locally. Each thread retains its own profile snapshot and results.")
    upload_error = False
    with st.container(border=True):
        st.subheader("1. Your profile")
        left, right = st.columns([1, 1])
        with left:
            uploaded = st.file_uploader("Drop your CV here", type=["pdf", "docx", "txt", "md"], help="PDF must have selectable text. Extracted text is editable below.", key=f"cv-upload:{thread_id}")
            if uploaded is not None:
                digest = hashlib.sha256(uploaded.getvalue()).hexdigest()
                if st.session_state.get(f"cv-digest:{thread_id}") != digest:
                    try:
                        st.session_state[draft_key(thread_id, "cv_text")] = _upload_text(uploaded)
                        st.session_state[f"cv-digest:{thread_id}"] = digest
                    except Exception as exc:
                        st.error(str(exc))
                        upload_error = True
            cv_text = st.text_area("Or paste your CV text", value=draft["cv_text"], key=draft_key(thread_id, "cv_text"), height=220, placeholder="Name: Alex\nSkills: Python, SQL\nExperience: Built a data API...")
        with right:
            github = st.text_input("GitHub", value=draft["github"], key=draft_key(thread_id, "github"), placeholder="https://github.com/yourname")
            portfolio = st.text_input("Portfolio / website", value=draft["portfolio"], key=draft_key(thread_id, "portfolio"), placeholder="https://yourname.dev")
            linkedin = st.text_input("LinkedIn", value=draft["linkedin"], key=draft_key(thread_id, "linkedin"), placeholder="https://linkedin.com/in/yourname")
            x_url = st.text_input("X / Twitter", value=draft["x"], key=draft_key(thread_id, "x"), placeholder="https://x.com/yourname")
            enrich = st.checkbox("Inspect public GitHub languages after analysis (unconfirmed)", key=f"enrich:{thread_id}")
        profile = {"cv_text": cv_text, "github": github, "portfolio": portfolio, "linkedin": linkedin, "x": x_url}
        if st.button("Save as shared profile for new threads", disabled=upload_error or not cv_text.strip(), key=f"save-profile:{thread_id}"):
            WORKSPACES.save_shared_profile(profile)
            st.success("New threads will start with this CV and links. Existing threads and old analyses are unchanged.")
        if st.button("Use latest shared profile in this thread", key=f"load-profile:{thread_id}"):
            st.session_state[f"refresh-profile:{thread_id}"] = True
            st.rerun()

    with st.container(border=True):
        st.subheader("2. This target job")
        job_title = st.text_input("Job title", value=draft["job_title"], key=draft_key(thread_id, "job_title"), placeholder="Backend Engineer")
        company = st.text_input("Company", value=draft["company"], key=draft_key(thread_id, "company"), placeholder="Acme")
        job_url = st.text_input("Official job URL", value=draft["job_url"], key=draft_key(thread_id, "job_url"), placeholder="https://careers.example.com/job")
        job_text = st.text_area("Job description", value=draft["job_text"], key=draft_key(thread_id, "job_text"), height=200, placeholder="You are experienced with Python and comfortable building APIs. Projects involving Docker are a plus.\n\nPaste the full description — no special format needed.")
        draft = {**profile, "job_title": job_title, "company": company, "job_url": job_url, "job_text": job_text}
        WORKSPACES.save_draft(workspace_id, thread_id, draft)
        st.caption("Requirements are inferred from wording and context. Review suggestions below; ambiguous mentions are not scored.")
        if job_text.strip():
            _requirement_editor(job_text)

    if st.button("Build my plan", type="primary", use_container_width=True, disabled=upload_error, key=f"build:{thread_id}"):
        try:
            candidate_text = cv_text
            if not candidate_text.strip() or not job_text.strip():
                raise ValueError("Provide both a CV and a job description.")
            links = {"github": github or None, "portfolio": portfolio or None, "linkedin": linkedin or None, "x": x_url or None}
            result = analyze_texts(
                candidate_text, job_text,
                links=links, job_title=job_title or None, company=company or None, job_url=job_url or None,
                requirement_memory=REQUIREMENT_MEMORY,
            )
            if enrich and github:
                candidate = enrich_github_profile(result.candidate)
                result = result.model_copy(update={"candidate": candidate})
            WORKSPACES.save_analysis(workspace_id, thread_id, result)
            st.session_state["analysis"] = result
        except Exception as exc:
            st.error(str(exc))

    current = WORKSPACES.thread(workspace_id, thread_id)
    if current["stale"]:
        st.warning("Saved inputs or reviewed requirements changed. Rebuild this plan; the older snapshot is retained but excluded from comparisons and coaching.")
    result = current["analysis"] if not current["stale"] else None
    st.session_state["analysis"] = result
    if not result:
        return

    st.divider()
    st.subheader("3. Your results")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Role match</div><div class='metric-value'>{result.match.score}%</div></div>", unsafe_allow_html=True)
    with col2:
        cv_score = result.cv_score.score if result.cv_score else "—"
        st.markdown(f"<div class='metric-card'><div class='metric-label'>CV readiness</div><div class='metric-value'>{cv_score}%</div></div>", unsafe_allow_html=True)
    with col3:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Skill gaps</div><div class='metric-value'>{len(result.skill_tree)}</div></div>", unsafe_allow_html=True)
    with col4:
        auth_status = result.authenticity_report.status if result.authenticity_report else "—"
        color = {"ready": "#198754", "needs_review": "#fd7e14", "blocked": "#dc3545"}.get(auth_status, "#6c757d")
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Authenticity</div><div class='metric-value' style='color:{color};'>{auth_status.replace('_', ' ').title()}</div></div>", unsafe_allow_html=True)

    tailored, improvements, roadmap = st.columns(3)
    with tailored:
        st.markdown("#### ✍️ Tailored CV")
        if result.tailored_resume:
            st.markdown(f"**{result.tailored_resume.target_title}**")
            st.markdown(f"*{result.tailored_resume.summary}*")
            st.markdown("**Relevant confirmed skills:** " + ", ".join(result.tailored_resume.relevant_skills or ["—"]))
            for suggestion in result.tailored_resume.suggestions:
                with st.expander(suggestion.section):
                    st.write(suggestion.recommendation)
                    st.info(suggestion.safe_draft)
            st.caption(result.tailored_resume.safety_note)
    with improvements:
        st.markdown("#### 📈 Improvements")
        if result.cv_score:
            for component in result.cv_score.components:
                st.progress(component.score / 100, text=f"{component.name}: {component.score}/{component.weight} weight")
            st.markdown("**Next actions:**")
            for action in result.cv_score.next_actions:
                st.write("- " + action)
        if result.authenticity_report:
            color = {"ready": "green", "needs_review": "orange", "blocked": "red"}.get(result.authenticity_report.status, "gray")
            st.markdown(f"**Authenticity:** :{color}[{result.authenticity_report.status.replace('_', ' ').title()}]")
            st.write(result.authenticity_report.overall_guidance)
            if result.authenticity_report.rewrite_sections:
                with st.expander("Rewrite these sections"):
                    for section in result.authenticity_report.rewrite_sections:
                        st.markdown(f"**{section.section}** — {section.reason}")
                        st.caption(section.candidate_action)
    with roadmap:
        st.markdown("#### 🗺️ Roadmap")
        if result.skill_tree:
            for index, node in enumerate(result.skill_tree, 1):
                with st.expander(f"{index}. {node.skill} ({node.priority})", expanded=index == 1):
                    st.write(node.reason)
                    if node.prerequisites:
                        st.caption("Prerequisites: " + ", ".join(node.prerequisites))
                    st.write("**Resources:**")
                    for resource in node.resources:
                        st.markdown(f"- [{resource.title}]({resource.url})" if resource.url else f"- {resource.title}")
        if result.project_plans:
            st.markdown("**Projects:**")
            for index, plan in enumerate(result.project_plans, 1):
                with st.expander(f"{index}. {plan.title}"):
                    st.write(plan.problem)
                    st.caption(f"Skills: {', '.join(plan.skills_practised)} · ~{plan.estimated_hours} h")
                    st.write("Acceptance:")
                    for test in plan.acceptance_tests:
                        st.write("- " + test)

    st.divider()
    if result.authenticity_report and result.authenticity_report.status == "blocked":
        st.error("Download is disabled while the CV contains unsupported claims. Remove or evidence them first.")
    else:
        report = render_markdown(result)
        st.download_button("Download full report (.md)", report, file_name="job-readiness-plan.md", mime="text/markdown")


def _requirement_editor(job_text: str) -> None:
    """Review current-job labels; reuse aliases only through a separate explicit action."""
    scope = st.session_state.get("active_scope")
    key = f"{scope[1] if scope else 'local'}-{document_key(job_text)}"
    requirements, evidence = extract_requirements(job_text, KNOWN_SKILLS, memory=REQUIREMENT_MEMORY)
    quotes = {item.id: item.quote for item in evidence}
    with st.expander("Review inferred requirements / teach the extractor", expanded=not requirements):
        st.caption("English-first, rule-based inference, not a trained semantic model. Edit names or importance, remove false positives, or add a missing skill with an exact quote from the description.")
        if requirements:
            st.dataframe([{"Skill": r.skill, "Importance": r.importance, "Method": r.extraction_method,
                           "Heuristic confidence (not calibrated)": r.confidence, "Needs review": r.needs_review}
                          for r in requirements], hide_index=True)
        rows = [{"keep": True, "skill": r.skill, "importance": r.importance, "quote": quotes[r.evidence_id]}
                for r in requirements]
        edited = st.data_editor(rows or [{"keep": True, "skill": "", "importance": "required", "quote": ""}],
            num_rows="dynamic", key=f"requirements-{key}", hide_index=True,
            column_config={
                "keep": st.column_config.CheckboxColumn("Keep", default=True),
                "skill": st.column_config.TextColumn("Skill / capability", required=True),
                "importance": st.column_config.SelectboxColumn("Importance", options=["required", "preferred", "uncertain"], required=True),
                "quote": st.column_config.TextColumn("Exact source quote", required=True),
            })
        confirmed = st.checkbox("I reviewed these interpretations against the source text", key=f"review-confirm-{key}")
        if st.button("Save corrections for this description", key=f"save-review-{key}", disabled=not confirmed):
            try:
                save_requirement_review(job_text, edited, REQUIREMENT_MEMORY)
                st.session_state.pop("analysis", None)
                WORKSPACES.invalidate_description(job_text)
                st.success("Corrections saved locally. Select Build my plan to use them. Future loads of this exact description will reuse them.")
            except ValueError as exc:
                st.error(str(exc))
        if st.button("Forget corrections for this description", key=f"forget-review-{key}"):
            REQUIREMENT_MEMORY.forget_review(job_text)
            WORKSPACES.invalidate_description(job_text)
            st.session_state.pop(f"requirements-{key}", None)
            st.session_state.pop("analysis", None)
            st.rerun()
        st.markdown("**Teach a reusable phrase → skill mapping**")
        st.caption("Only learn mappings you explicitly approve. Required/preferred importance is inferred afresh in each new job, not copied from this one.")
        phrase = st.text_input("Exact phrase to recognize in future jobs", key=f"alias-phrase-{key}", placeholder="event-driven services")
        skill = st.text_input("Canonical skill name", key=f"alias-skill-{key}", placeholder="Event-driven architecture")
        remember = st.checkbox("Reuse this mapping in future Quick start assessments", key=f"alias-confirm-{key}")
        if st.button("Remember mapping", key=f"alias-save-{key}", disabled=not remember):
            try:
                reviewed = REQUIREMENT_MEMORY.reviewed(job_text)
                if not reviewed:
                    raise ValueError("Save a reviewed description before teaching a reusable mapping")
                confirmed_quotes = {e.id: e.quote for e in reviewed[1]}
                source_quote = next((confirmed_quotes[r.evidence_id] for r in reviewed[0]
                                     if r.skill.casefold() == skill.strip().casefold() and
                                     phrase.strip().casefold() in confirmed_quotes[r.evidence_id].casefold()), None)
                if source_quote is None:
                    raise ValueError("The mapping must agree with a saved skill and its source quote")
                REQUIREMENT_MEMORY.learn_alias(phrase, skill, source_quote=source_quote, user_confirmed=True)
                st.success("Mapping remembered locally. No external model was trained and no CV data was used.")
            except ValueError as exc:
                st.error(str(exc))
        aliases = REQUIREMENT_MEMORY.aliases()
        if aliases:
            st.dataframe([{"Phrase": p, "Skill": s} for p, s in aliases.items()], hide_index=True)
            forgotten = st.selectbox("Mapping to remove", list(aliases), key=f"alias-remove-{key}")
            if st.button("Forget mapping", key=f"alias-delete-{key}"):
                REQUIREMENT_MEMORY.forget_alias(forgotten)
                st.rerun()


def _open_job_thread(job, key: str) -> None:
    if st.button("Open in a new job thread", key=key):
        wid = st.session_state["active_scope"][0]
        draft = {**WORKSPACES.shared_profile(), "job_title": job.title, "company": job.company,
                 "job_url": job.url or "", "job_text": job.description or ""}
        tid = WORKSPACES.create_thread(wid, f"{job.title} — {job.company}"[:100], draft)
        st.session_state[f"pending_thread:{wid}"] = tid
        st.rerun()


def _opportunities() -> None:
    st.subheader("Permitted job discovery")
    st.caption("User-triggered refreshes of public career-board APIs. No scraping, no stored credentials.")
    source, identifier = st.columns(2)
    with source:
        source_kind = st.selectbox("Public source", ["Greenhouse", "Lever", "Recruitee"])
    with identifier:
        token = st.text_input("Board identifier", help="Greenhouse board token, Lever site handle, or Recruitee company slug.")
    if st.button("Fetch and monitor public job postings"):
        try:
            if source_kind == "Greenhouse":
                jobs = fetch_greenhouse_jobs(token)
            elif source_kind == "Lever":
                jobs = fetch_lever_jobs(token)
            else:
                jobs = fetch_recruitee_jobs(token)
            new_jobs = MONITOR.refresh(source=source_kind, identifier=token, jobs=jobs)
            st.session_state["source_jobs"] = jobs
            st.session_state["new_source_jobs"] = new_jobs
            STORE.record_event("public_job_fetch", {"source": source_kind, "identifier": token, "count": len(jobs), "new_count": len(new_jobs)})
        except Exception as exc:
            st.error(str(exc))
    if "new_source_jobs" in st.session_state:
        st.info(f"{len(st.session_state['new_source_jobs'])} newly observed job(s) on the latest user-triggered refresh.")
    for index, job in enumerate(st.session_state.get("source_jobs", [])[:30]):
        st.markdown(f"- **{job.title}** · {job.company} · {job.location or 'Location not listed'}" + (f" · [Official page]({job.url})" if job.url else ""))
        _open_job_thread(job, f"open-source:{index}")

    st.divider()
    st.subheader("Official-platform connectors")
    st.caption("Tokens are used for this request only and are never saved. No profile scraping, messaging, or posting.")
    official_tab, import_tab = st.tabs(["Official APIs", "Import your lawful export"])
    with official_tab:
        linkedin_token = st.text_input("LinkedIn OAuth access token", value=os.environ.get("LINKEDIN_ACCESS_TOKEN", ""), type="password", help="Requires a LinkedIn app and OIDC permissions. Verifies the connected account only.")
        if st.button("Verify authorized LinkedIn identity"):
            try:
                identity = fetch_linkedin_authorized_identity(linkedin_token)
                st.session_state["linkedin_identity"] = identity
                STORE.record_event("linkedin_authorized_identity", {"subject": identity.subject})
            except Exception as exc:
                st.error(str(exc))
        if identity := st.session_state.get("linkedin_identity"):
            st.success(f"Authorized LinkedIn identity: {identity.name or identity.subject}")
        smart_company = st.text_input("SmartRecruiters company identifier")
        smart_token = st.text_input("SmartRecruiters Posting API token", type="password")
        if st.button("Fetch SmartRecruiters postings through the official API"):
            try:
                smart_jobs = fetch_smartrecruiters_postings(smart_company, smart_token)
                new_smart_jobs = MONITOR.refresh(source="SmartRecruiters", identifier=smart_company, jobs=smart_jobs)
                st.session_state["smart_jobs"] = smart_jobs
                st.success(f"Fetched {len(smart_jobs)} role(s), including {len(new_smart_jobs)} newly observed.")
                STORE.record_event("smartrecruiters_official_fetch", {"identifier": smart_company, "count": len(smart_jobs), "new_count": len(new_smart_jobs)})
            except Exception as exc:
                st.error(str(exc))
        for index, job in enumerate(st.session_state.get("smart_jobs", [])[:20]):
            st.markdown(f"- **{job.title}** · {job.company}" + (f" · [Official page]({job.url})" if job.url else ""))
            _open_job_thread(job, f"open-smart:{index}")
        x_query = st.text_input("X API v2 recent-search query", placeholder='("hiring" OR "we are hiring") (AI OR software) lang:en')
        x_token = st.text_input("X API v2 bearer token", value=os.environ.get("X_BEARER_TOKEN", ""), type="password")
        x_count = st.slider("Maximum posts", min_value=10, max_value=100, value=10)
        if st.button("Search recent X posts through the official API"):
            try:
                signals = fetch_x_recent_posts(x_query, x_token, x_count)
                st.session_state["x_signals"] = signals
                STORE.record_event("x_official_recent_search", {"query": x_query, "count": len(signals)})
            except Exception as exc:
                st.error(str(exc))
        for signal in st.session_state.get("x_signals", []):
            st.markdown(f"- {signal.text}" + (f" · [Open source post]({signal.url})" if signal.url else ""))
    with import_tab:
        st.caption("Upload CSV or JSON that you personally exported or obtained with permission. Up to 500 records/5 MB; imported facts remain reviewable.")
        contact_export = st.file_uploader("Contact export (.csv or .json)", type=["csv", "json"], key="contact_export")
        if contact_export and st.button("Import contact export"):
            try:
                leads = import_contact_export(contact_export.getvalue(), contact_export.name)
                st.session_state["imported_leads"] = leads
                STORE.record_event("contact_export_import", {"filename": contact_export.name, "count": len(leads)})
                st.success(f"Imported {len(leads)} contacts for review.")
            except Exception as exc:
                st.error(str(exc))
        job_export = st.file_uploader("Job export (.csv or .json)", type=["csv", "json"], key="job_export")
        if job_export and st.button("Import job export"):
            try:
                jobs = import_job_export(job_export.getvalue(), job_export.name)
                st.session_state["imported_jobs"] = jobs
                STORE.record_event("job_export_import", {"filename": job_export.name, "count": len(jobs)})
                st.success(f"Imported {len(jobs)} evidence-ready job records.")
            except Exception as exc:
                st.error(str(exc))
        for index, job in enumerate(st.session_state.get("imported_jobs", [])[:20]):
            st.markdown(f"- **{job.title}** · {job.company}" + (f" · [Source]({job.url})" if job.url else ""))
            _open_job_thread(job, f"open-import:{index}")

    st.divider()
    st.subheader("Human-reviewed contact research")
    result = st.session_state.get("analysis")
    default_company = result.job.company if result else ""
    default_title = result.job.title if result else ""
    company = st.text_input("Target company", value=default_company, key="contact_company")
    title = st.text_input("Target role", value=default_title, key="contact_title")
    contact_scope = st.session_state.get("active_scope", ("", "local"))[1]
    lead_text = st.text_area("Verified public contacts (one per line: Name | Role | public profile URL | public email if explicitly published)", height=110, key=f"contacts:{contact_scope}")
    observed_pattern = st.text_input("Observed company email format (optional; never used to generate addresses)", placeholder="first.last@company.com", key=f"email-pattern:{contact_scope}")
    if st.button("Create research checklist"):
        leads = [*st.session_state.get("imported_leads", []), *parse_contact_leads(lead_text)]
        plan = contact_research_plan(company, title, leads, observed_pattern or None)
        st.session_state["contact_plan"] = plan
        STORE.record_event("contact_research_plan", {"company": company, "lead_count": len(plan.leads)})
    plan = st.session_state.get("contact_plan")
    if plan:
        st.warning(plan.safety_note)
        st.write("**Prioritize:** " + " → ".join(plan.target_roles))
        st.write("**Manual search queries:**")
        st.code("\n".join(plan.search_queries))
        if plan.leads:
            st.dataframe([lead.model_dump() for lead in plan.leads], use_container_width=True, hide_index=True)
        if plan.email_pattern:
            st.caption(f"Observed format recorded: {plan.email_pattern}. This is not an individual email address and must not be used to guess one.")
    with st.expander("Local monitoring registry"):
        st.caption("Monitoring is user-triggered only. Source identifiers are retained locally; credentials are never stored.")
        watches = MONITOR.watches()
        if watches:
            st.dataframe(watches, use_container_width=True, hide_index=True)
        else:
            st.write("No source has been refreshed yet.")


def _interview() -> None:
    result = st.session_state.get("analysis")
    if not result:
        st.info("Complete a Quick start assessment first; it supplies evidence-aware, role-specific questions.")
        return
    questions = build_interview_questions(result.candidate, result.job)
    thread_id = st.session_state.get("active_scope", ("", "local"))[1]
    selected = st.selectbox("Question", questions, format_func=lambda question: f"{question.category.title()} — {question.question}", key=f"interview-question:{thread_id}")
    scope = f"{thread_id}:{selected.id}"
    st.write("A strong answer should include: " + "; ".join(selected.what_good_evidence_looks_like))
    answer = st.text_area("Your answer (type it, or transcribe an optional recording below)", height=160, key=f"interview-answer:{scope}")
    try:
        audio = st.audio_input("Record an answer (optional)", key=f"interview-audio:{scope}")
    except AttributeError:
        audio = None
        st.caption("Upgrade Streamlit to use in-app audio recording; typed answers work now.")
    if audio is not None:
        st.audio(audio)
        if st.button("Transcribe recording with OpenAI"):
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                st.error("Set OPENAI_API_KEY to use optional transcription. Audio is not sent otherwise.")
            else:
                try:
                    transcript = transcribe_openai_audio(audio.getvalue(), getattr(audio, "name", "answer.wav"), key)
                    st.session_state[f"interview-transcript:{scope}"] = transcript
                except Exception as exc:
                    st.error(f"Transcription failed: {exc}")
    if transcript := st.session_state.get(f"interview-transcript:{scope}"):
        transcript = st.text_area("Transcript", transcript, height=100, key=f"transcript-display:{scope}")
        answer = answer or transcript
    if st.button("Get structured feedback", type="primary"):
        feedback = evaluate_answer(selected, answer)
        st.metric("Practice evidence score", f"{feedback.score}/100", help="Checks answer structure, not technical correctness.")
        st.write("**Strengths:** " + (" ".join(feedback.strengths) or "Not enough evidence yet."))
        st.write("**Improve:** " + " ".join(feedback.missing))
        st.info("Follow-up: " + feedback.follow_up)


def _upload_text(uploaded) -> str:
    suffix = Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
        temporary.write(uploaded.getvalue())
        path = Path(temporary.name)
    try:
        return load_document(path)
    finally:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
