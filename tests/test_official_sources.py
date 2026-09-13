import json

from tau_job_application.official_sources import (
    fetch_linkedin_authorized_identity,
    fetch_x_recent_posts,
    import_contact_export,
    import_job_export,
)


def test_official_api_connectors_use_authorized_response_only(monkeypatch) -> None:
    def fake_request(url: str, token: str) -> dict:
        assert token == "secret"
        if "linkedin" in url:
            return {"sub": "member-1", "name": "Alex Example", "email": "alex@example.com"}
        return {"data": [{"id": "1", "text": "We are hiring", "author_id": "9", "created_at": "2026-01-01T00:00:00Z", "public_metrics": {"like_count": 3}}]}

    monkeypatch.setattr("tau_job_application.official_sources._request_json", fake_request)
    identity = fetch_linkedin_authorized_identity("secret")
    posts = fetch_x_recent_posts("hiring", "secret")

    assert identity.subject == "member-1"
    assert posts[0].url == "https://x.com/i/web/status/1"
    assert posts[0].metrics["like_count"] == 3


def test_imports_user_provided_exports_as_reviewable_records() -> None:
    contacts = import_contact_export(
        b"name,role,profile_url,public_email,evidence\nAda,Engineering Manager,https://example.com/ada,ada@example.com,Public company team page\n",
        "contacts.csv",
    )
    jobs = import_job_export(
        json.dumps([{"title": "Engineer", "company": "Acme", "required_skills": "Python, Docker", "url": "https://careers.example/job"}]).encode(),
        "jobs.json",
    )

    assert contacts[0].confidence == "needs_review"
    assert contacts[0].public_email == "ada@example.com"
    assert jobs[0].requirements[0].skill == "Python"
