import json

import pytest

from tau_job_application.pipeline import analyze_texts
from tau_job_application.workspace_chat import chat_context, local_reply, model_reply
from tau_job_application.workspaces import WorkspaceStore, direction_summary


def analyzed(store, workspace, name, skills):
    draft = {"cv_text": "Name: Alex\nSkills: C++, Python", "job_text": f"Required skills: {skills}", "job_title": name, "company": "Example"}
    tid = store.create_thread(workspace, name, draft)
    result = analyze_texts(draft["cv_text"], draft["job_text"], job_title=name, company="Example")
    store.save_analysis(workspace, tid, result)
    return tid


def test_persistence_isolation_and_broad_title_grouping(tmp_path):
    store = WorkspaceStore(tmp_path / "local.sqlite")
    embedded = store.create_workspace("Embedded Systems")
    gpu = store.create_workspace("GPU Computing")
    firmware = analyzed(store, embedded, "Firmware Developer", "C++, Linux")
    systems = analyzed(store, embedded, "Systems Software Engineer", "C++, RTOS")
    kernel = analyzed(store, gpu, "Kernel Performance Engineer", "C++, CUDA")
    store.save_exchange(embedded, firmware, "firmware-private", "firmware-answer")
    store.save_exchange(gpu, kernel, "gpu-private", "gpu-answer")
    restarted = WorkspaceStore(store.path)
    assert restarted.thread(embedded, firmware)["analysis"].job.title == "Firmware Developer"
    assert restarted.messages(embedded, firmware)[0]["content"] == "firmware-private"
    assert restarted.messages(embedded, systems) == []
    summary = direction_summary(restarted.list_threads(embedded))
    assert len(summary["jobs"]) == 2
    shared = next(e for e in summary["skills"] if e["skill"] == "C++")
    assert set(shared["threads"]) == {firmware, systems}
    assert {e["skill"] for e in summary["skills"]} == {"C++", "Linux", "RTOS"}
    assert {g.skill for g in summary["gaps"]} == {"Linux", "RTOS"}
    store.save_exchange(embedded, systems, "other-thread-secret", "keep this separate")
    context = chat_context(store, embedded, firmware)
    serialized = json.dumps(context)
    assert "other-thread-secret" not in serialized
    assert "gpu-private" not in serialized
    assert "CUDA" not in serialized
    assert "firmware-private" in serialized
    assert "C++" in local_reply("compare roles", context)


def test_wrong_workspace_cannot_read_or_write_thread(tmp_path):
    store = WorkspaceStore(tmp_path / "local.sqlite")
    one, two = store.create_workspace("One"), store.create_workspace("Two")
    tid = analyzed(store, one, "Target", "Python")
    for operation in (
        lambda: store.thread(two, tid), lambda: store.messages(two, tid),
        lambda: store.save_draft(two, tid, {}), lambda: store.save_exchange(two, tid, "x", "y"),
        lambda: store.delete_thread(two, tid), lambda: store.rename_thread(two, tid, "Changed"),
    ):
        with pytest.raises(ValueError):
            operation()
    assert store.thread(one, tid)["name"] == "Target"
    assert store.messages(one, tid) == []


def test_shared_profile_seeds_new_threads_without_overwriting_old(tmp_path):
    store = WorkspaceStore(tmp_path / "local.sqlite")
    wid = store.create_workspace("Hardware")
    store.save_shared_profile({"cv_text": "Version one", "github": "https://github.com/example"})
    old = store.create_thread(wid, "Old")
    store.save_shared_profile({"cv_text": "Version two"})
    new = store.create_thread(wid, "New")
    assert store.thread(wid, old)["draft"]["cv_text"] == "Version one"
    assert store.thread(wid, new)["draft"]["cv_text"] == "Version two"
    assert store.thread(wid, old)["draft"]["job_text"] == ""


def test_stale_snapshots_excluded_and_review_invalidates_matching_jobs(tmp_path):
    store = WorkspaceStore(tmp_path / "local.sqlite")
    wid = store.create_workspace("Hardware")
    tid = analyzed(store, wid, "Role", "Python, FPGA")
    draft = store.thread(wid, tid)["draft"]
    draft["company"] = "Different company"
    store.save_draft(wid, tid, draft)
    assert store.thread(wid, tid)["stale"]
    assert direction_summary(store.list_threads(wid))["jobs"] == []
    assert chat_context(store, wid, tid)["current_analysis"] is None
    result = analyze_texts(draft["cv_text"], draft["job_text"], job_title=draft["job_title"], company=draft["company"])
    store.save_analysis(wid, tid, result)
    assert not store.thread(wid, tid)["stale"]
    store.invalidate_description(draft["job_text"])
    assert store.thread(wid, tid)["stale"]
    assert store.thread(wid, tid)["analysis"] is not None  # Snapshot retained, not discarded.


def test_deletion_cascades_chat_only_in_selected_thread(tmp_path):
    store = WorkspaceStore(tmp_path / "local.sqlite")
    wid = store.create_workspace("Hardware")
    a, b = store.create_thread(wid, "A"), store.create_thread(wid, "B")
    store.save_exchange(wid, a, "q", "a")
    store.save_exchange(wid, b, "keep", "me")
    store.delete_thread(wid, a)
    assert len(store.messages(wid, b)) == 2
    with store._connect() as db:
        assert db.execute("SELECT count(*) FROM career_messages WHERE thread_id=?", (a,)).fetchone()[0] == 0
    with pytest.raises(ValueError):
        store.thread(wid, a)


def test_move_preserves_thread_and_chat_but_changes_scope(tmp_path):
    store = WorkspaceStore(tmp_path / "local.sqlite")
    source, destination = store.create_workspace("Hardware"), store.create_workspace("Hardware and Embedded")
    tid = analyzed(store, source, "Firmware Engineer", "C++, Linux")
    store.save_exchange(source, tid, "Original question", "Original answer")
    store.move_thread(source, tid, destination)
    assert not store.list_threads(source)
    assert store.thread(destination, tid)["analysis"].job.title == "Firmware Engineer"
    assert store.messages(destination, tid)[0]["content"] == "Original question"
    with pytest.raises(ValueError):
        store.thread(source, tid)


def test_duplicate_directions_and_invalid_analysis_rejected(tmp_path):
    store = WorkspaceStore(tmp_path / "local.sqlite")
    wid = store.create_workspace("GPU")
    with pytest.raises(ValueError):
        store.create_workspace("gpu")
    tid = store.create_thread(wid, "New")
    wrong = analyze_texts("Name: Alex\nSkills: Python", "Required skills: Python")
    with pytest.raises(ValueError):
        store.save_analysis(wid, tid, wrong)


@pytest.mark.asyncio
async def test_optional_chat_requires_consent_and_has_no_tools():
    from tau_ai import FakeProvider
    from tau_ai.events import AssistantDoneEvent
    from tau_agent.messages import AssistantMessage, TextContent, ThinkingContent

    response = AssistantMessage(content=[ThinkingContent(thinking="Not for display"), TextContent(text="Review the source evidence.")])
    provider = FakeProvider([[AssistantDoneEvent(reason="stop", message=response)]])
    with pytest.raises(ValueError):
        await model_reply("Help", {}, consent=False, provider=provider, model="fake")
    assert provider.calls == []
    reply = await model_reply("Help", {"direction": "Embedded Systems"}, consent=True, provider=provider, model="fake")
    assert reply == "Review the source evidence."
    assert provider.calls[0][3] == []
    assert "Embedded Systems" in provider.calls[0][2][0].text
