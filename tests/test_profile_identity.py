import pytest

from tau_job_application.career_hub import draft_documents
from tau_job_application.profile_identity import ProfileIdentity, ProfileIdentityStore


def test_identity_validation():
    record = ProfileIdentity(name="  Alex   Example ", email="ALEX@Example.COM ", updated_at="now")
    assert record.name == "Alex Example"
    assert record.email == "alex@example.com"
    with pytest.raises(ValueError):
        ProfileIdentity(name="Alex", email="not-an-email", updated_at="now")
    with pytest.raises(ValueError):
        ProfileIdentity(name="Alex", email="alex@localhost", updated_at="now")
    with pytest.raises(ValueError):
        ProfileIdentity(name="   ", email="alex@example.com", updated_at="now")


def test_store_roundtrip_and_clear(tmp_path):
    store = ProfileIdentityStore(tmp_path / "db.sqlite")
    assert store.load() is None
    saved = store.save("Alex Example", "alex@example.com")
    assert saved.updated_at
    loaded = store.load()
    assert (loaded.name, loaded.email) == ("Alex Example", "alex@example.com")
    store.save("Renamed", "renamed@example.com")
    assert store.load().name == "Renamed"  # one row, replaced
    assert store.clear() is True and store.clear() is False
    assert store.load() is None


def test_letter_draft_uses_the_saved_name():
    _, letter = draft_documents(
        "Name: Alex\nSkills: Python", "Platform Engineer", "Example Co", ["Python"],
        sender_name="Alex Example",
    )
    assert letter.rstrip().endswith("Alex Example")
    _, fallback = draft_documents("Name: Alex\nSkills: Python", "Platform Engineer", "Example Co", ["Python"])
    assert fallback.rstrip().endswith("[Your name]")
