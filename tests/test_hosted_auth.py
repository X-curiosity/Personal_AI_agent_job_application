from types import SimpleNamespace

import pytest

from tau_job_application.hosted_auth import begin_linkedin_link, exchange_email_token, linkedin_identities, request_magic_link, unlink_linkedin, verify_email_code


class Auth:
    def __init__(self):
        self.calls = []
        self.identities = [SimpleNamespace(identity_id="identity-1", provider="linkedin_oidc", email="person@example.com")]
    def sign_in_with_otp(self, body): self.calls.append(("otp", body))
    def verify_otp(self, body): self.calls.append(("verify", body)); return body
    def link_identity(self, body): self.calls.append(("link", body)); return SimpleNamespace(url="https://linkedin.example/oauth")
    def get_user_identities(self): return SimpleNamespace(identities=self.identities)
    def unlink_identity(self, identity): self.calls.append(("unlink", identity.identity_id))


def test_magic_link_signin_cannot_create_account():
    auth = Auth(); request_magic_link(SimpleNamespace(auth=auth), "person@example.com", create_account=False, redirect_to="https://app.example")
    assert auth.calls[0][1]["options"] == {"should_create_user": False, "email_redirect_to": "https://app.example"}


def test_magic_link_signup_records_notice_but_no_client_timestamp():
    auth = Auth(); request_magic_link(SimpleNamespace(auth=auth), "person@example.com", create_account=True, redirect_to="https://app.example", privacy_version="v2", privacy_url="https://app.example/privacy")
    options = auth.calls[0][1]["options"]
    assert options["should_create_user"] is True
    assert options["data"] == {"privacy_notice_version": "v2", "privacy_notice_url": "https://app.example/privacy"}


def test_passwordless_validation_and_redirect_policy():
    with pytest.raises(ValueError): request_magic_link(SimpleNamespace(auth=Auth()), "bad", create_account=False, redirect_to="")
    with pytest.raises(ValueError): request_magic_link(SimpleNamespace(auth=Auth()), "person@example.com", create_account=False, redirect_to="http://evil.example")
    with pytest.raises(ValueError): verify_email_code(SimpleNamespace(auth=Auth()), "person@example.com", "abc")


def test_email_code_uses_email_otp_type():
    auth = Auth(); verify_email_code(SimpleNamespace(auth=auth), "person@example.com", "123456")
    assert auth.calls[0] == ("verify", {"email": "person@example.com", "token": "123456", "type": "email"})


def test_magic_link_callback_uses_server_readable_token_hash():
    auth = Auth(); exchange_email_token(SimpleNamespace(auth=auth), "token-hash")
    assert auth.calls[-1] == ("verify", {"token_hash": "token-hash", "type": "email"})


def test_linkedin_is_explicit_oidc_identity_link_and_can_disconnect():
    auth = Auth(); client = SimpleNamespace(auth=auth)
    assert begin_linkedin_link(client, "https://app.example") == "https://linkedin.example/oauth"
    assert auth.calls[0][1]["provider"] == "linkedin_oidc"
    assert linkedin_identities(client)[0]["provider"] == "linkedin_oidc"
    unlink_linkedin(client, "identity-1")
    assert auth.calls[-1] == ("unlink", "identity-1")
    with pytest.raises(ValueError): unlink_linkedin(client, "other")
