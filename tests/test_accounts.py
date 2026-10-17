import pytest

from tau_job_application.accounts import (
    ConnectedAccount,
    ConnectedAccountStore,
    complete_linkedin_signin,
    connect_github,
    linkedin_authorization_url,
    new_oauth_state,
)


def test_github_connect_uses_public_api_and_keeps_no_token():
    calls = []

    def fake_fetcher(url, *, expected_host, **kwargs):
        calls.append((url, expected_host))
        if url.endswith("/repos?per_page=100&sort=updated"):
            return [{"language": "Python"}, {"language": "Rust"}, {"language": None}]
        return {"login": "octocat", "name": "The Octocat", "public_repos": 8,
                "avatar_url": "https://avatars.githubusercontent.com/u/1"}

    account = connect_github("octocat", fetcher=fake_fetcher)
    assert account.provider == "github" and account.subject == "octocat"
    assert account.display_name == "The Octocat"
    assert "8 public repositories" in account.detail
    assert "Python" in account.detail and "Rust" in account.detail
    assert account.avatar_url == "https://avatars.githubusercontent.com/u/1"
    assert all(host == "api.github.com" for _, host in calls)
    assert "token" not in account.detail.casefold()

    with pytest.raises(ValueError):
        connect_github("bad name!", fetcher=fake_fetcher)


def test_linkedin_authorization_url_is_official_oidc():
    url = linkedin_authorization_url(client_id="abc123", redirect_uri="http://127.0.0.1:8506/?view=account", state="state-1")
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert "client_id=abc123" in url and "state=state-1" in url
    assert "openid+profile+email" in url or "openid%20profile%20email" in url
    with pytest.raises(ValueError):
        linkedin_authorization_url(client_id=" ", redirect_uri="http://127.0.0.1/x", state="s")
    with pytest.raises(ValueError):
        linkedin_authorization_url(client_id="abc", redirect_uri="http://evil.example.com/cb", state="s")


def test_linkedin_signin_reads_claims_and_discards_token():
    seen_auth = []

    def fake_poster(url, *, expected_host, method, data, headers):
        assert expected_host == "www.linkedin.com" and method == "POST"
        assert b"grant_type=authorization_code" in data and b"client_secret=secret" in data
        return {"access_token": "token-123", "expires_in": 5184000}

    def fake_fetcher(url, *, expected_host, headers=None, **kwargs):
        assert expected_host == "api.linkedin.com"
        seen_auth.append(headers.get("Authorization"))
        return {"sub": "lnk-42", "name": "Alex Example", "email": "alex@example.com",
                "picture": "https://media.licdn.com/dms/image/alex.png"}

    account = complete_linkedin_signin(
        code="code-1", client_id="abc", client_secret="secret",
        redirect_uri="http://127.0.0.1:8506/?view=account",
        poster=fake_poster, fetcher=fake_fetcher,
    )
    assert account.provider == "linkedin" and account.subject == "lnk-42"
    assert account.display_name == "Alex Example" and account.email == "alex@example.com"
    assert account.avatar_url == "https://media.licdn.com/dms/image/alex.png"
    assert seen_auth == ["Bearer token-123"]
    # The token is not retained anywhere on the stored account.
    assert "token-123" not in account.model_dump_json()
    assert "no API" in account.detail or "OpenID Connect" in account.detail


def test_store_roundtrip_one_row_per_provider(tmp_path):
    store = ConnectedAccountStore(tmp_path / "db.sqlite")
    assert store.all() == []
    account = ConnectedAccount(provider="github", subject="octocat", display_name="The Octocat",
                               connected_at="2026-10-16T00:00:00+00:00")
    store.save(account)
    assert store.get("github").subject == "octocat"
    store.save(account.model_copy(update={"display_name": "Renamed"}))
    assert len(store.all()) == 1 and store.get("github").display_name == "Renamed"
    assert store.get("linkedin") is None
    assert store.remove("github") is True and store.remove("github") is False
    assert store.all() == []


def test_oauth_state_is_random_and_urlsafe():
    first, second = new_oauth_state(), new_oauth_state()
    assert first != second and len(first) > 20 and " " not in first


def test_credential_endpoints_refuse_redirects():
    from tau_job_application.accounts import _NoRedirect as AccountsNoRedirect
    from tau_job_application.official_sources import _NoRedirect as OfficialNoRedirect

    # Returning None makes urllib raise instead of re-sending the bearer token
    # to the redirect target.
    assert AccountsNoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example.com") is None
    assert OfficialNoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example.com") is None


def test_linkedin_authorization_url_supports_pkce_and_nonce():
    url = linkedin_authorization_url(
        client_id="abc123", redirect_uri="http://127.0.0.1:8506/?view=account",
        state="state-1", nonce="nonce-1", code_challenge="challenge-1",
    )
    assert "nonce=nonce-1" in url
    assert "code_challenge=challenge-1" in url
    assert "code_challenge_method=S256" in url


def test_pkce_challenge_matches_rfc7636_appendix_b():
    from tau_job_application.accounts import new_pkce_verifier, pkce_challenge

    assert pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert 43 <= len(new_pkce_verifier()) <= 128


def _id_token(claims: dict) -> str:
    import base64
    import json

    def part(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256', 'typ': 'JWT'})}.{part(claims)}.signature"


def test_linkedin_signin_sends_verifier_and_binds_nonce():
    captured = {}

    def fake_poster(url, *, expected_host, method, data, headers):
        captured["body"] = data.decode()
        return {"access_token": "token-123", "id_token": _id_token({"nonce": "nonce-1", "sub": "lnk-42"})}

    def fake_fetcher(url, *, expected_host, headers=None, **kwargs):
        return {"sub": "lnk-42", "name": "Alex Example"}

    account = complete_linkedin_signin(
        code="code-1", client_id="abc", client_secret="secret",
        redirect_uri="http://127.0.0.1:8506/?view=account",
        code_verifier="verifier-1", nonce="nonce-1",
        poster=fake_poster, fetcher=fake_fetcher,
    )
    assert "code_verifier=verifier-1" in captured["body"]
    assert account.subject == "lnk-42"

    def wrong_nonce_poster(url, *, expected_host, method, data, headers):
        return {"access_token": "token-123", "id_token": _id_token({"nonce": "attacker", "sub": "lnk-42"})}

    with pytest.raises(RuntimeError, match="did not match"):
        complete_linkedin_signin(
            code="code-1", client_id="abc", client_secret="secret",
            redirect_uri="http://127.0.0.1:8506/?view=account",
            code_verifier="verifier-1", nonce="nonce-1",
            poster=wrong_nonce_poster, fetcher=fake_fetcher,
        )
