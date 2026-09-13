"""Minimalist local Streamlit UI for the evidence-first job-readiness workflow."""

from __future__ import annotations

import os
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
from tau_job_application.parsing import load_document
from tau_job_application.pipeline import analyze_texts, render_markdown
from tau_job_application.sources import enrich_github_profile, fetch_greenhouse_jobs, fetch_lever_jobs, fetch_recruitee_jobs
from tau_job_application.storage import LocalStore


def _project_root() -> Path:
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    return Path.home() / ".job-readiness-agent"


ROOT = _project_root()
STORE = LocalStore(ROOT / ".job_assistant" / "assistant.sqlite")
MONITOR = JobMonitor(ROOT / ".job_assistant" / "assistant.sqlite")


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
    st.caption("Drag in your CV, add your links, paste a job description, and get a tailored CV, improvement plan, and roadmap.")

    quickstart, opportunities, interview = st.tabs(["🚀 Quick start", "🔎 Opportunities & contacts", "🎙️ Interview practice"])
    with quickstart:
        _quickstart()
    with opportunities:
        _opportunities()
    with interview:
        _interview()


def _quickstart() -> None:
    with st.container(border=True):
        st.subheader("1. Your profile")
        left, right = st.columns([1, 1])
        with left:
            uploaded = st.file_uploader("Drop your CV here", type=["pdf", "docx", "txt", "md"], help="PDF must have selectable text.")
            cv_text = st.text_area("Or paste your CV text", height=220, placeholder="Name: Alex\nSkills: Python, SQL\nExperience: Built a data API...")
        with right:
            github = st.text_input("GitHub", placeholder="https://github.com/yourname")
            portfolio = st.text_input("Portfolio / website", placeholder="https://yourname.dev")
            linkedin = st.text_input("LinkedIn", placeholder="https://linkedin.com/in/yourname")
            x_url = st.text_input("X / Twitter", placeholder="https://x.com/yourname")
            enrich = st.checkbox("Inspect public GitHub languages after analysis (unconfirmed)")

    with st.container(border=True):
        st.subheader("2. Target role")
        job_title = st.text_input("Job title", placeholder="Backend Engineer")
        company = st.text_input("Company", placeholder="Acme")
        job_url = st.text_input("Official job URL", placeholder="https://careers.example.com/job")
        job_text = st.text_area("Job description", height=200, placeholder="Required skills: Python, Docker\nPreferred skills: AWS\n\nPaste the full description...")

    if st.button("Build my plan", type="primary", use_container_width=True):
        try:
            candidate_text = _upload_text(uploaded) if uploaded else cv_text
            if not candidate_text.strip() or not job_text.strip():
                raise ValueError("Provide both a CV and a job description.")
            links = {"github": github or None, "portfolio": portfolio or None, "linkedin": linkedin or None, "x": x_url or None}
            result = analyze_texts(
                candidate_text, job_text,
                links=links, job_title=job_title or None, company=company or None, job_url=job_url or None,
            )
            if enrich and github:
                candidate = enrich_github_profile(result.candidate)
                result = result.model_copy(update={"candidate": candidate})
            st.session_state["analysis"] = result
            STORE.save_analysis(result)
        except Exception as exc:
            st.error(str(exc))

    result = st.session_state.get("analysis")
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
    for job in st.session_state.get("source_jobs", [])[:30]:
        st.markdown(f"- **{job.title}** · {job.company} · {job.location or 'Location not listed'}" + (f" · [Official page]({job.url})" if job.url else ""))

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
        for job in st.session_state.get("smart_jobs", [])[:20]:
            st.markdown(f"- **{job.title}** · {job.company}" + (f" · [Official page]({job.url})" if job.url else ""))
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
        for job in st.session_state.get("imported_jobs", [])[:20]:
            st.markdown(f"- **{job.title}** · {job.company}" + (f" · [Source]({job.url})" if job.url else ""))

    st.divider()
    st.subheader("Human-reviewed contact research")
    result = st.session_state.get("analysis")
    default_company = result.job.company if result else ""
    default_title = result.job.title if result else ""
    company = st.text_input("Target company", value=default_company, key="contact_company")
    title = st.text_input("Target role", value=default_title, key="contact_title")
    lead_text = st.text_area("Verified public contacts (one per line: Name | Role | public profile URL | public email if explicitly published)", height=110)
    observed_pattern = st.text_input("Observed company email format (optional; never used to generate addresses)", placeholder="first.last@company.com")
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
    selected = st.selectbox("Question", questions, format_func=lambda question: f"{question.category.title()} — {question.question}")
    st.write("A strong answer should include: " + "; ".join(selected.what_good_evidence_looks_like))
    answer = st.text_area("Your answer (type it, or transcribe an optional recording below)", height=160)
    try:
        audio = st.audio_input("Record an answer (optional)")
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
                    st.session_state["interview_transcript"] = transcript
                except Exception as exc:
                    st.error(f"Transcription failed: {exc}")
    if transcript := st.session_state.get("interview_transcript"):
        st.text_area("Transcript", transcript, height=100, key="transcript_display")
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
