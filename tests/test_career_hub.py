from datetime import UTC, datetime, timedelta

import pytest

from tau_job_application.application_tracker import ApplicationProgress, ApplicationStage, ApplicationTrackerStore
from tau_job_application.career_hub import HubStore, Interests, draft_documents, infer_email, suggested_roles
from tau_job_application.career_inbox import InboxStore, Reply, classify_reply
from tau_job_application.pipeline import analyze_texts
from tau_job_application.role_discovery import CompanyFacts, DiscoveredOpening
from tau_job_application.workspaces import WorkspaceStore


@pytest.fixture
def hub(tmp_path):
    workspaces = WorkspaceStore(tmp_path / "hub.sqlite")
    track = workspaces.create_workspace("Hardware")
    other = workspaces.create_workspace("Finance")
    store = HubStore(workspaces.path)
    thread = store.role_page(workspaces, track, "Hardware Engineer")
    return workspaces, store, track, other, thread


def test_interest_graph_allows_cross_discipline_routes():
    for subfield in ("Electrical engineering", "Computer science & AI", "Neuroscience & Neuro-X", "Economics & statistics"):
        assert "Machine Learning Engineer" in suggested_roles([subfield])
    assert suggested_roles(["Unknown"]) == []
    with pytest.raises(ValueError):
        Interests(roles=[])


def test_hub_persistence_ownership_and_deletion(hub):
    workspaces, store, track, other, thread = hub
    store.save_interests(track, Interests(fields=["Engineering"], subfields=["Electrical engineering"], roles=["Hardware Engineer"]))
    assert HubStore(workspaces.path).interests(track).roles == ["Hardware Engineer"]
    assert store.role_page(workspaces, track, "hardware engineer") == thread
    store.save_documents(track, thread, letter="My reviewed letter", resume="My source CV")
    assert store.documents(track, thread)["letter"] == "My reviewed letter"
    with pytest.raises(ValueError):
        store.documents(other, thread)
    with pytest.raises(ValueError):
        store.save_documents(track, thread, letter="x" * 100_001, resume="")
    workspaces.delete_thread(track, thread)
    assert store.role_page(workspaces, track, "Hardware Engineer") != thread


def test_drafts_preserve_source_facts_and_need_background():
    source = "Name: Alex Example\nSkills: Python\nBuilt a tested prototype."
    resume, letter = draft_documents(source, "Hardware Engineer", "Example", ["Python"])
    assert source in resume
    assert "[Explain why" in letter
    assert "Hardware Engineer" in letter
    with pytest.raises(ValueError):
        draft_documents("", "Engineer", "Example", [])


def test_email_inference_requires_pattern_and_source():
    assert infer_email("Alex Example", "example.com", "first.last", "https://example.com/team") == "alex.example@example.com"
    for domain, source in (("bad/path", "https://example.com"), ("example.com", "javascript:alert(1)")):
        with pytest.raises(ValueError):
            infer_email("Alex Example", domain, "first.last", source)


def test_confirmed_skills_do_not_mutate_raw_cv_or_accept_new_claims():
    cv = "Name: Alex\nSkills: Python, SQL\nExperience: Built services."
    result = analyze_texts(cv, "Required skills: Python, SQL", confirmed_skills=["Python"])
    assert result.candidate.raw_cv == cv
    assert [item.skill for item in result.match.requirements if item.status == "matched"] == ["Python"]
    with pytest.raises(ValueError):
        analyze_texts(cv, "Required skills: Python", confirmed_skills=["Rust"])


@pytest.fixture
def inbox(hub):
    workspaces, _, track, other, thread = hub
    tracker = ApplicationTrackerStore(workspaces.path)
    opening = DiscoveredOpening(title="Hardware Engineer", company=CompanyFacts(name="Example"), source="Ashby", source_url="https://jobs.ashbyhq.com/example/job")
    app = tracker.save(track, thread, opening)
    app = tracker.update(track, app.id, ApplicationProgress(stage="applied", applied_on=datetime.now(UTC).date()))
    store = InboxStore(tracker)
    store.bind(track, app.id, source="gmail", conversation="thread1", sender="recruiter@example.com", auto_update=True)
    return store, tracker, track, other, app


def reply(**updates):
    values = dict(source="gmail", conversation="thread1", message_id="message1", sender="recruiter@example.com",
                  text="We invite you to interview for this role.", received_at=datetime.now(UTC))
    return Reply(**(values | updates))


def test_classification_is_conservative():
    assert classify_reply("We are pleased to offer you the position") is ApplicationStage.OFFER
    assert classify_reply("You accepted our newsletter") is None
    assert classify_reply("This is not an offer. We invite you to interview.") is None
    assert classify_reply("We invite you to interview but will not be moving forward") is None
    assert classify_reply("Application status changed") is None
    assert classify_reply("We are not pleased to offer you the position") is None
    assert classify_reply("We won't invite you to interview") is None


def test_exact_reply_binding_auto_updates_and_deduplicates(inbox):
    store, tracker, track, other, app = inbox
    assert store.ingest(track, app.id, reply(sender="another@example.com"), trusted_connector=True) == "unmatched"
    message = reply()
    assert store.ingest(track, app.id, message, trusted_connector=True) == "updated"
    assert tracker.get(track, app.id).progress.stage is ApplicationStage.INTERVIEW
    assert store.ingest(track, app.id, message, trusted_connector=True) == "duplicate"
    assert tracker.history(track, app.id)[0].action == "reply_status_update"
    with pytest.raises(ValueError):
        store.events(other, app.id)


def test_imported_and_old_replies_need_review(inbox):
    store, tracker, track, _, app = inbox
    assert store.ingest(track, app.id, reply()) == "review"
    assert tracker.get(track, app.id).progress.stage is ApplicationStage.APPLIED
    old = reply(message_id="old", received_at=datetime.now(UTC) - timedelta(days=20))
    assert store.ingest(track, app.id, old, trusted_connector=True) == "review"
    event = store.events(track, app.id)[0]
    store.apply(track, app.id, event["id"])
    with pytest.raises(ValueError):
        store.apply(track, app.id, event["id"])


def test_offer_is_not_acceptance_and_status_never_regresses_automatically(inbox):
    store, tracker, track, _, app = inbox
    assert store.ingest(track, app.id, reply(text="We are pleased to offer you the position."), trusted_connector=True) == "updated"
    assert tracker.get(track, app.id).progress.stage is ApplicationStage.OFFER
    assert store.ingest(track, app.id, reply(message_id="later", text="Thank you for applying"), trusted_connector=True) == "review"
    assert tracker.get(track, app.id).progress.stage is ApplicationStage.OFFER


def test_same_conversation_cannot_silently_update_two_applications(inbox, hub):
    store, tracker, track, _, app = inbox
    _, _, _, _, thread = hub
    opening = DiscoveredOpening(title="Other Engineer", company=CompanyFacts(name="Example"), source="Ashby", source_url="https://jobs.ashbyhq.com/example/other-job")
    other = tracker.save(track, thread, opening)
    with pytest.raises(ValueError, match="already bound"):
        store.bind(track, other.id, source="gmail", conversation="thread1", sender="recruiter@example.com")
    assert store.binding(track, other.id) is None


def test_connectors_use_exact_ids_and_read_only_requests(monkeypatch):
    from tau_job_application import career_inbox
    calls = []
    def fake_get(url, token):
        calls.append(url)
        if "gmail.googleapis.com" in url:
            return {"messages": [{"id": "m1", "threadId": "thread1", "labelIds": ["INBOX"], "internalDate": "1792000000000", "snippet": "We invite you to interview", "payload": {"headers": [{"name": "From", "value": "Recruiter <recruiter@example.com>"}]}}]}
        return {"ok": True, "messages": [{"ts": "1792000000.0", "user": "U1234567", "text": "Thank you for applying"}]}
    monkeypatch.setattr(career_inbox, "_get", fake_get)
    assert career_inbox.read_gmail("test-token", "thread1")[0].sender == "recruiter@example.com"
    assert career_inbox.read_slack("test-token", "C1234567")[0].source == "slack"
    assert len(calls) == 2
    with pytest.raises(ValueError):
        career_inbox.read_gmail("test-token", "../secrets")
    assert len(calls) == 2
