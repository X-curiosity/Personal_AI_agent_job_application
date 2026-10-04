"""Career-direction sidebar, broad skill overview, and independent thread chats."""
from __future__ import annotations

import asyncio

import streamlit as st

from tau_job_application.workspace_chat import chat_context, local_reply, model_reply
from tau_job_application.matching import normalize_skill
from tau_job_application.workspaces import DRAFT_FIELDS, WorkspaceStore, direction_summary


def draft_key(thread_id: str, field: str) -> str:
    return f"thread:{thread_id}:draft:{field}"


def persist_active_inputs(store: WorkspaceStore):
    scope = st.session_state.get("active_scope")
    if not scope:
        return
    try:
        draft = store.thread(*scope)["draft"]
        for field in DRAFT_FIELDS:
            if draft_key(scope[1], field) in st.session_state:
                draft[field] = st.session_state[draft_key(scope[1], field)]
        store.save_draft(*scope, draft)
    except ValueError:
        # The previously active thread may have been explicitly deleted.
        st.session_state.pop("active_scope", None)


def choose_scope(store: WorkspaceStore) -> tuple[str, str]:
    persist_active_inputs(store)
    workspaces = store.list_workspaces()
    if not workspaces:
        # A neutral starting point makes this a personal product rather than a
        # technical demo. Career tracks are optional folders around individual
        # job workspaces, not a prerequisite for using the product.
        store.create_workspace("My applications")
        workspaces = store.list_workspaces()
    labels = {w["id"]: w["name"] for w in workspaces}
    pending = st.session_state.pop("pending_workspace", None)
    if pending in labels:
        st.session_state["workspace_selector"] = pending
    if st.session_state.get("workspace_selector") not in labels:
        st.session_state["workspace_selector"] = workspaces[0]["id"]
    with st.sidebar:
        st.header("Career workspace")
        st.caption("Keep every target role in its own focused room. Career tracks are optional folders for related roles.")
        wid = st.selectbox("Career track", list(labels), format_func=labels.get, key="workspace_selector")
        with st.expander("Add a career track"):
            with st.form("create-direction"):
                name = st.text_input("Career track name", placeholder="Product design, Climate tech, Data platforms…")
                if st.form_submit_button("Create career track"):
                    try:
                        new_id = store.create_workspace(name)
                        st.session_state["pending_workspace"] = new_id
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        threads = store.list_threads(wid)
        if not threads:
            store.create_thread(wid, "New target role")
            threads = store.list_threads(wid)
        names = {t["id"]: t["name"] for t in threads}
        selector = f"thread_selector:{wid}"
        pending_thread = st.session_state.pop(f"pending_thread:{wid}", None)
        if pending_thread in names:
            st.session_state[selector] = pending_thread
        if st.session_state.get(selector) not in names:
            st.session_state[selector] = threads[0]["id"]
        st.markdown("##### Job workspaces")
        tid = st.selectbox("Job workspace", list(names), format_func=names.get, key=selector)
        selected = next(thread for thread in threads if thread["id"] == tid)
        _show_workspace_status(selected)
        with st.expander("Add a job workspace"):
            with st.form(f"create-thread:{wid}"):
                thread_name = st.text_input("Job workspace name", placeholder="Product designer — Northstar")
                if st.form_submit_button("Create job workspace"):
                    try:
                        new_id = store.create_thread(wid, thread_name)
                        st.session_state[f"pending_thread:{wid}"] = new_id
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        with st.expander("Manage this job workspace"):
            with st.form(f"rename:{tid}"):
                name = st.text_input("Rename job workspace", value=names[tid])
                if st.form_submit_button("Rename workspace"):
                    try:
                        store.rename_thread(wid, tid, name)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            destinations = {key: value for key, value in labels.items() if key != wid}
            if destinations:
                destination = st.selectbox("Move to career track", list(destinations), format_func=destinations.get, key=f"move-target:{tid}")
                if st.button("Move workspace (keep its history)", key=f"move:{tid}"):
                    store.move_thread(wid, tid, destination)
                    st.session_state["pending_workspace"] = destination
                    st.session_state[f"pending_thread:{destination}"] = tid
                    st.rerun()
            delete = st.checkbox("Delete this job workspace, its inputs, plan, and practice history", key=f"confirm-delete:{tid}")
            if st.button("Delete job workspace", disabled=not delete, key=f"delete:{tid}"):
                store.delete_thread(wid, tid)
                st.rerun()
        st.caption("Your profile, job analysis, interview practice, and conversations are saved locally. Shared-profile changes never overwrite an existing job workspace.")
    scope = (wid, tid)
    if st.session_state.get("active_scope") != scope:
        # Legacy view-state must not leak from one target to another.
        for key in ("analysis", "contact_plan", "interview_transcript", "transcript_display", "contact_company", "contact_title"):
            st.session_state.pop(key, None)
    st.session_state["active_scope"] = scope
    thread = store.thread(*scope)
    st.session_state["analysis"] = thread["analysis"] if not thread["stale"] else None
    return scope


def _show_workspace_status(thread: dict) -> None:
    """A compact lifecycle signal for the currently selected Job Workspace."""
    draft = thread["draft"]
    has_profile = bool(draft["cv_text"].strip())
    has_job = bool(draft["job_text"].strip())
    ready = bool(thread["analysis"]) and not thread["stale"]
    completed = sum((has_profile, has_job, ready))
    label = "Plan ready" if ready else "Ready to analyze" if has_profile and has_job else "Set up this workspace"
    st.progress(completed / 3, text=f"{label} · {completed}/3 essentials")


def show_direction(store: WorkspaceStore, workspace_id: str):
    name = next(w["name"] for w in store.list_workspaces() if w["id"] == workspace_id)
    summary = direction_summary(store.list_threads(workspace_id))
    st.subheader(f"{name} — Career track")
    st.caption("This optional view compares related Job Workspaces by evidence, not by title alone. You do not need every skill from every role.")
    if summary["stale_count"]:
        st.warning(f"{summary['stale_count']} old analysis snapshot(s) excluded because inputs or reviewed requirements changed. Rebuild those thread plans.")
    if not summary["jobs"]:
        st.info("Analyze one or more Job Workspaces to build a Career-track view. Use the sidebar to add related target roles.")
        return
    st.dataframe([{"Job workspace" if k == "thread" else k.title(): v for k, v in row.items() if k != "id"} for row in summary["jobs"]], hide_index=True)
    st.caption("Requirement evidence coverage is a per-job heuristic, not a hiring probability. Workspaces may use different saved profile versions.")
    st.markdown("**Shared foundations and role-specific skills**")
    names = {t["id"]: t["name"] for t in store.list_threads(workspace_id)}
    st.dataframe([{"Skill": e["skill"], "Job workspaces": len(e["threads"]), "Required in": len(e["required"]),
                   "Preferred in": len(e["preferred"]), "Missing evidence in": len(e["missing"]),
                   "Uncertain in": len(e["uncertain"]), "Where": ", ".join(names[i] for i in e["threads"])}
                  for e in summary["skills"]], hide_index=True)
    st.markdown("**Career-track learning priorities**")
    st.caption("Prioritized by missing required coverage, then other missing coverage across current workspaces—not by job title. These remain template plans.")
    for node in summary["gaps"]:
        with st.expander(node.skill):
            st.write(node.reason)
            st.write("Prerequisites: " + (", ".join(node.prerequisites) or "None identified"))
            st.write(node.completion_evidence)
    for plan in summary["projects"]:
        with st.expander(plan.title):
            st.write(plan.problem)
            st.write("Targets: " + ", ".join(plan.skills_practised))
            st.write("\n".join("- " + criterion for criterion in plan.acceptance_tests))
    with st.expander("Transferable skills across Career tracks"):
        others = []
        own = {normalize_skill(e["skill"]): e["skill"] for e in summary["skills"]}
        for workspace in store.list_workspaces():
            if workspace["id"] == workspace_id:
                continue
            other = direction_summary(store.list_threads(workspace["id"]))
            shared = sorted(own[normalize_skill(e["skill"])] for e in other["skills"] if normalize_skill(e["skill"]) in own)
            if shared:
                others.append({"Career track": workspace["name"], "Overlapping requirements": ", ".join(shared)})
        if others:
            st.dataframe(others, hide_index=True)
        else:
            st.write("Analyze jobs in another Career track to compare requirements. Overlap does not imply equivalent roles or proven competence.")


def show_chat(store: WorkspaceStore, workspace_id: str, thread_id: str):
    thread = store.thread(workspace_id, thread_id)
    st.subheader(f"Coach — {thread['name']}")
    st.caption("This coaching history belongs only to this Job Workspace. Career-track comparisons use aggregate results, not other workspaces' conversations.")
    use_model = st.checkbox("Use AI coaching instead of the local report guide", key=f"chat-model:{thread_id}")
    consent = False
    if use_model:
        consent = st.checkbox("Allow sending the displayed context and my question to the configured model provider", key=f"chat-consent:{thread_id}")
        st.caption("Requires OPENAI_API_KEY and MODEL_NAME. Context includes this workspace's CV/job analysis, its latest 12 messages, and this Career track's job/skill summaries. No other track or workspace conversation is sent. No tools can modify your records.")
        with st.expander("Preview context sent to AI"):
            st.json(chat_context(store, workspace_id, thread_id))
    else:
        st.caption("Local guide: try 'show skill gaps', 'project roadmap', 'CV suggestions', or 'compare roles'. This mode uses templates, not an LLM.")
    history = store.messages(workspace_id, thread_id)
    for message in history[-40:]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    if history:
        st.download_button("Download this conversation", "\n\n".join(f"{m['role']}: {m['content']}" for m in history),
                           file_name="job-conversation.txt", key=f"chat-download:{thread_id}")
    question = st.chat_input("Ask about this job or compare roles in this Career track", key=f"chat-input:{thread_id}", max_chars=4_000)
    if question:
        try:
            context = chat_context(store, workspace_id, thread_id)
            if use_model:
                with st.spinner("Asking the read-only coach…"):
                    answer = asyncio.run(model_reply(question, context, consent=consent))
            else:
                answer = local_reply(question, context)
            store.save_exchange(workspace_id, thread_id, question, answer, mode="model" if use_model else "local")
            st.rerun()
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("Coaching request failed. No turn was saved; check provider access or use the local guide.")
