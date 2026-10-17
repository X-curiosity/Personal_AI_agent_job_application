import json
from datetime import UTC, datetime, timedelta

import pytest

from tau_job_application import jev_client


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_URL", raising=False)


def test_disabled_without_key_or_endpoint():
    assert jev_client.jev_available() is False
    assert jev_client.jev_skill_probability("React", "React Native") is None


def test_insecure_or_credentialed_endpoints_are_refused(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "k")
    for url in ("http://api.example.com/decide", "https://user:pass@api.example.com/x", "not-a-url"):
        monkeypatch.setenv("JEV_API_URL", url)
        assert jev_client.jev_api_url() is None
        assert jev_client.jev_available() is False
    monkeypatch.setenv("JEV_API_URL", "https://api.example.com/decide")
    assert jev_client.jev_available() is True


def test_redirects_are_refused(monkeypatch):
    assert jev_client._NoRedirect().redirect_request(
        None, None, 302, "", {}, "https://evil.example.com"
    ) is None


def test_probability_is_cached_and_reused(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "k")
    monkeypatch.setenv("JEV_API_URL", "https://api.example.com/decide")
    calls = []

    def poster(*, left, right, question):
        calls.append((left, right))
        return 0.83

    database = tmp_path / "db.sqlite"
    first = jev_client.jev_skill_probability("React", "React Native", database_path=database, poster=poster)
    second = jev_client.jev_skill_probability("React Native", "React", database_path=database, poster=poster)
    assert first == second == 0.83
    assert len(calls) == 1  # order-insensitive cache key

    expired = datetime.now(UTC) + timedelta(days=31)
    refreshed = jev_client.jev_skill_probability(
        "React", "React Native", database_path=database, poster=poster, now=expired
    )
    assert refreshed == 0.83 and len(calls) == 2


def test_failures_return_none_so_the_caller_keeps_the_local_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "k")
    monkeypatch.setenv("JEV_API_URL", "https://api.example.com/decide")

    def broken(**kwargs):
        raise RuntimeError("network down")

    def garbage(**kwargs):
        return "not a probability"

    assert jev_client.jev_skill_probability("A", "B", poster=broken) is None
    assert jev_client.jev_skill_probability("A", "B", poster=garbage) is None


def test_probability_is_clamped():
    def high(**kwargs):
        return 4.2

    def low(**kwargs):
        return -3

    import os

    os.environ["JEV_API_KEY"] = "k"
    os.environ["JEV_API_URL"] = "https://api.example.com/decide"
    try:
        assert jev_client.jev_skill_probability("A", "B", poster=high) == 1.0
        assert jev_client.jev_skill_probability("A", "C", poster=low) == 0.0
    finally:
        os.environ.pop("JEV_API_KEY", None)
        os.environ.pop("JEV_API_URL", None)


def test_response_extraction_accepts_documented_shapes():
    extract = jev_client._extract_probability
    assert extract({"probability": 0.7}) == 0.7
    assert extract({"output": {"score": 0.2}}) == 0.2
    assert extract({"choice": "yes"}) == 1.0
    assert extract({"verdict": "no"}) == 0.0
    assert extract(True) == 1.0
    assert extract({"unexpected": "shape"}) is None


def test_request_body_contains_only_the_two_skills(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "k")
    monkeypatch.setenv("JEV_API_URL", "https://api.example.com/decide")
    sent = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=-1):
            assert limit == jev_client.MAX_RESPONSE_BYTES + 1
            return json.dumps({"probability": 0.6}).encode()

    def fake_open(request, timeout=None):
        sent["body"] = json.loads(request.data.decode())
        sent["auth"] = request.get_header("Authorization")
        sent["timeout"] = timeout
        return Response()

    monkeypatch.setattr(jev_client._opener, "open", fake_open)
    assert jev_client._post_decision(left="React", right="React Native", question="Same skill?") == 0.6
    assert sent["body"]["context"] == {"left_skill": "React", "right_skill": "React Native"}
    assert sent["auth"] == "Bearer k"
    assert "address" not in json.dumps(sent["body"]).casefold()
    assert sent["timeout"] == jev_client.REQUEST_TIMEOUT_SECONDS
