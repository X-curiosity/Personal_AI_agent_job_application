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
        for name in ("Embedded Systems", "Hardware", "GPU Computing"):
            store.create_workspace(name)
        workspaces = store.list_workspaces()
    labels = {w["id"]: w["name"] for w in workspaces}
    pending = st.session_state.pop("pending_workspace", None)
    if pending in labels:
        st.session_state["workspace_selector"] = pending
    if st.session_state.get("workspace_selector") not in labels:
        st.session_state["workspace_selector"] = workspaces[0]["id"]
    with st.sidebar:
        st.header("Career directions")
        st.caption("Group related roles; keep each target job and conversation separate.")
        wid = st.selectbox("Career direction", list(labels), format_func=labels.get, key="workspace_selector")
        with st.expander("Add a direction"):
            with st.form("create-direction"):
                name = st.text_input("Direction name", placeholder="Robotics, Data Infrastructure…")
                if st.form_submit_button("Create direction"):
                    try:
                        new_id = store.create_workspace(name)
                        st.session_state["pending_workspace"] = new_id
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        threads = store.list_threads(wid)
        if not threads:
            store.create_thread(wid, "First target job")
            threads = store.list_threads(wid)
        names = {t["id"]: t["name"] for t in threads}
        selector = f"thread_selector:{wid}"
        pending_thread = st.session_state.pop(f"pending_thread:{wid}", None)
        if pending_thread in names:
            st.session_state[selector] = pending_thread
        if st.session_state.get(selector) not in names:
            st.session_state[selector] = threads[0]["id"]
        tid = st.selectbox("Job / conversation", list(names), format_func=names.get, key=selector)
        with st.expander("Add a job thread"):
            with st.form(f"create-thread:{wid}"):
                thread_name = st.text_input("Thread name", placeholder="Firmware engineer — company A")
                if st.form_submit_button("Create job thread"):
                    try:
                        new_id = store.create_thread(wid, thread_name)
                        st.session_state[f"pending_thread:{wid}"] = new_id
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        with st.expander("Manage this thread"):
            with st.form(f"rename:{tid}"):
                name = st.text_input("Rename thread", value=names[tid])
                if st.form_submit_button("Rename"):
                    try:
                        store.rename_thread(wid, tid, name)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            destinations = {key: value for key, value in labels.items() if key != wid}
            if destinations:
                destination = st.selectbox("Move thread to direction", list(destinations), format_func=destinations.get, key=f"move-target:{tid}")
                if st.button("Move thread (keep its history)", key=f"move:{tid}"):
                    store.move_thread(wid, tid, destination)
                    st.session_state["pending_workspace"] = destination
                    st.session_state[f"pending_thread:{destination}"] = tid
                    st.rerun()
            delete = st.checkbox("Delete this thread, its inputs, result, and chat", key=f"confirm-delete:{tid}")
            if st.button("Delete thread", disabled=not delete, key=f"delete:{tid}"):
                store.delete_thread(wid, tid)
                st.rerun()
        st.caption("Text inputs, analyses, and chat history are saved locally. The shared profile and approved extraction mappings are separate from threads.")
    scope = (wid, tid)
    if st.session_state.get("active_scope") != scope:
        # Legacy view-state must not leak from one target to another.
        for key in ("analysis", "contact_plan", "interview_transcript", "transcript_display", "contact_company", "contact_title"):
            st.session_state.pop(key, None)
    st.session_state["active_scope"] = scope
    thread = store.thread(*scope)
    st.session_state["analysis"] = thread["analysis"] if not thread["stale"] else None
    return scope


def show_direction(store: WorkspaceStore, workspace_id: str):
    name = next(w["name"] for w in store.list_workspaces() if w["id"] == workspace_id)
    summary = direction_summary(store.list_threads(workspace_id))
    st.subheader(f"{name} — direction overview")
    st.caption("Titles do not restrict which jobs belong here. Compare actual skills and responsibilities; you do not need every skill from every role.")
    if summary["stale_count"]:
        st.warning(f"{summary['stale_count']} old analysis snapshot(s) excluded because inputs or reviewed requirements changed. Rebuild those thread plans.")
    if not summary["jobs"]:
        st.info("Analyze one or more job threads to build a direction-wide view. Use the sidebar to add related titles.")
        return
    st.dataframe([{k: v for k, v in row.items() if k != "id"} for row in summary["jobs"]], hide_index=True)
    st.caption("Scores are per-job skill heuristics, not hiring probabilities. Threads may use different saved profile versions.")
    st.markdown("**Shared foundations and role-specific skills**")
    names = {t["id"]: t["name"] for t in store.list_threads(workspace_id)}
    st.dataframe([{"Skill": e["skill"], "Job threads": len(e["threads"]), "Required in": len(e["required"]),
                   "Preferred in": len(e["preferred"]), "Missing evidence in": len(e["missing"]),
                   "Uncertain in": len(e["uncertain"]), "Where": ", ".join(names[i] for i in e["threads"])}
                  for e in summary["skills"]], hide_index=True)
    st.markdown("**Direction learning priorities**")
    st.caption("Prioritized by missing required coverage, then other missing coverage across current threads—not by job title. These remain template plans.")
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
    with st.expander("Transferable skills across career directions"):
        others = []
        own = {normalize_skill(e["skill"]): e["skill"] for e in summary["skills"]}
        for workspace in store.list_workspaces():
            if workspace["id"] == workspace_id:
                continue
            other = direction_summary(store.list_threads(workspace["id"]))
            shared = sorted(own[normalize_skill(e["skill"])] for e in other["skills"] if normalize_skill(e["skill"]) in own)
            if shared:
                others.append({"Direction": workspace["name"], "Overlapping requirements": ", ".join(shared)})
        if others:
            st.dataframe(others, hide_index=True)
        else:
            st.write("Analyze jobs in another direction to compare requirements. Overlap does not imply equivalent roles or proven competence.")


def show_chat(store: WorkspaceStore, workspace_id: str, thread_id: str):
    thread = store.thread(workspace_id, thread_id)
    st.subheader(f"Conversation — {thread['name']}")
    st.caption("This chat belongs only to this job thread. Direction comparisons use aggregate results, not other threads' conversations.")
    use_model = st.checkbox("Use AI coaching instead of the local report guide", key=f"chat-model:{thread_id}")
    consent = False
    if use_model:
        consent = st.checkbox("Allow sending the displayed context and my question to the configured model provider", key=f"chat-consent:{thread_id}")
        st.caption("Requires OPENAI_API_KEY and MODEL_NAME. Context includes this thread's CV/job analysis, its latest 12 messages, and this direction's job/skill summaries. No other direction or thread conversation is sent. No tools can modify your records.")
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
    question = st.chat_input("Ask about this job or compare roles in this direction", key=f"chat-input:{thread_id}", max_chars=4_000)
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
