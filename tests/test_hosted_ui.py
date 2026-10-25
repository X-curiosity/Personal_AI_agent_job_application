from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from streamlit.testing.v1 import AppTest


HOSTED_UI = Path(__file__).resolve().parents[1] / "src/tau_job_application/hosted_ui.py"


class _FakeQuery:
    def __init__(self, table: str, client, rows: list[dict]) -> None:
        self.table_name = table
        self.client = client
        self.data = rows
        self.operation = "select"
        self.filters: list[tuple[str, object]] = []

    def select(self, _columns: str):
        return self

    def order(self, _column: str, **_kwargs):
        return self

    def limit(self, _count: int):
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def insert(self, row: dict):
        self.operation = "insert"
        self.data = [{"id": "44444444-4444-4444-8444-444444444444", **row}]
        self.client.inserted.append((self.table_name, row))
        return self

    def update(self, row: dict):
        self.operation = "update"
        self.data = [row]
        return self

    def eq(self, key: str, value: object):
        self.filters.append((key, value))
        return self

    def execute(self):
        if self.operation == "delete":
            self.client.deleted.append((self.table_name, list(self.filters)))
        return SimpleNamespace(data=self.data)


class _FakeStorageBucket:
    def create_signed_url(self, path: str, expires_in: int):
        return {"signedURL": f"https://storage.example/{path}?expires={expires_in}"}

    def download(self, path: str) -> bytes:
        return f"file:{path}".encode()


class _FakeStorage:
    def from_(self, _bucket: str):
        return _FakeStorageBucket()


class _FakeClient:
    def __init__(self, rows: dict[str, list[dict]] | None = None) -> None:
        self.rows = dict(rows or {})
        self.rows.setdefault("privacy_notice_acceptances", [{
            "notice_version": "policy-v1",
            "notice_url": "https://example.com/privacy",
            "accepted_at": "2026-10-01T00:00:00Z",
        }])
        self.deleted: list[tuple[str, list[tuple[str, object]]]] = []
        self.inserted: list[tuple[str, dict]] = []
        self.storage = _FakeStorage()
        self.function_calls: list[tuple[str, dict]] = []
        self.auth_actions: list[tuple[str, dict]] = []
        self.functions = SimpleNamespace(invoke=lambda name, invoke_options: self.function_calls.append((name, invoke_options)))
        recovery_response = SimpleNamespace(
            session=SimpleNamespace(access_token="access", refresh_token="refresh"),
            user=SimpleNamespace(
                id="11111111-1111-4111-8111-111111111111",
                email="person@example.com",
                email_confirmed_at="2026-10-01T00:00:00Z",
                user_metadata={},
            ),
        )
        self.rpc = lambda _name, _params: SimpleNamespace(execute=lambda: SimpleNamespace(data=[{"code_verifier": "test-verifier-that-is-long-enough-for-pkce"}]))
        self.auth = SimpleNamespace(
            set_session=lambda _access, _refresh: None,
            get_session=lambda: SimpleNamespace(access_token="access", refresh_token="refresh"),
            resend=lambda body: self.auth_actions.append(("resend", body)),
            sign_in_with_otp=lambda body: self.auth_actions.append(("sign_in_with_otp", body)),
            reauthenticate=lambda: self.auth_actions.append(("reauthenticate", {})),
            link_identity=lambda body: (self.auth_actions.append(("link_identity", body)) or SimpleNamespace(url="https://linkedin.example/connect")),
            verify_otp=lambda body: (self.auth_actions.append(("verify_otp", body)) or recovery_response),
            exchange_code_for_session=lambda body: (self.auth_actions.append(("exchange_code", body)) or recovery_response),
            get_user_identities=lambda: SimpleNamespace(identities=[]),
            update_user=lambda body: self.auth_actions.append(("update_user", body)),
            get_user=lambda: SimpleNamespace(user=SimpleNamespace(
                id="11111111-1111-4111-8111-111111111111",
                email="person@example.com",
                email_confirmed_at="2026-10-01T00:00:00Z",
                user_metadata={},
            )),
            sign_out=lambda: None,
        )

    def table(self, name: str):
        return _FakeQuery(name, self, self.rows.get(name, []))


def _install_fake_supabase(monkeypatch, client: _FakeClient) -> None:
    module = ModuleType("supabase")
    def create(_url, _key, options=None, **_kwargs):
        if options is not None:
            options.storage.set_item("supabase.auth.token-code-verifier", "test-verifier-that-is-long-enough-for-pkce")
        return client
    module.create_client = create
    from supabase.lib.client_options import SyncClientOptions
    lib = ModuleType("supabase.lib")
    options_module = ModuleType("supabase.lib.client_options")
    options_module.SyncClientOptions = SyncClientOptions
    monkeypatch.setitem(sys.modules, "supabase.lib", lib)
    monkeypatch.setitem(sys.modules, "supabase.lib.client_options", options_module)
    monkeypatch.setitem(sys.modules, "supabase", module)


def test_hosted_entrypoint_fails_closed_without_provider_configuration(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30).run()
    assert not app.exception
    assert any("not configured yet" in item.value for item in app.error)
    assert not app.text_input


def test_authenticated_session_without_server_recorded_acceptance_is_denied(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    client = _FakeClient({"privacy_notice_acceptances": []})
    _install_fake_supabase(monkeypatch, client)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30)
    app.session_state["hosted_auth"] = {
        "access_token": "access", "refresh_token": "refresh",
        "user_id": "11111111-1111-4111-8111-111111111111", "email": "person@example.com",
    }
    app.run()
    assert any("no server-recorded Privacy Notice acknowledgment" in item.value for item in app.error)
    assert not any(tab.label == "CV library" for tab in app.tabs)
    assert not app.exception


def test_duplicate_cv_versions_have_distinct_labels_and_delete_requires_confirmation(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    monkeypatch.setenv("HOSTED_SIGNUPS_ENABLED", "false")
    cv_rows = [
        {"id": "aaaaaaaa-1111-4111-8111-111111111111", "filename": "cv.pdf", "object_path": "11111111-1111-4111-8111-111111111111/a/cv.pdf", "mime_type": "application/pdf", "byte_size": 1024, "created_at": "2026-10-01T10:00:00+00:00"},
        {"id": "bbbbbbbb-2222-4222-8222-222222222222", "filename": "cv.pdf", "object_path": "11111111-1111-4111-8111-111111111111/b/cv.pdf", "mime_type": "application/pdf", "byte_size": 1024, "created_at": "2026-10-02T10:00:00+00:00"},
    ]
    client = _FakeClient({"cv_profiles": cv_rows})
    _install_fake_supabase(monkeypatch, client)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30)
    app.session_state["hosted_auth"] = {
        "access_token": "access", "refresh_token": "refresh",
        "user_id": "11111111-1111-4111-8111-111111111111", "email": "person@example.com",
    }
    app.run()
    labels = [button.label for button in app.button]
    assert "Delete cv.pdf (aaaaaaaa)" in labels
    assert "Delete cv.pdf (bbbbbbbb)" in labels

    next(button for button in app.button if button.label == "Delete cv.pdf (aaaaaaaa)").click().run()
    assert client.deleted == []
    assert any(button.label == "Confirm delete cv.pdf (aaaaaaaa)" for button in app.button)
    assert any(button.label == "Cancel delete cv.pdf (aaaaaaaa)" for button in app.button)


def test_application_progress_and_removal_controls_are_record_labeled_and_confirmed(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    target = {"id": "22222222-2222-4222-8222-222222222222", "company_name": "Example Co", "company_website": None, "created_at": "2026-10-01T00:00:00Z"}
    application = {"id": "33333333-3333-4333-8333-333333333333", "company_name": "Example Co", "job_title": "Data Engineer", "job_url": "https://jobs.example/1", "stage": "saved", "notes": "private", "cv_profile_id": None, "created_at": "2026-10-01T00:00:00Z"}
    client = _FakeClient({"target_companies": [target], "application_queue": [application]})
    _install_fake_supabase(monkeypatch, client)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30)
    app.session_state["hosted_auth"] = {
        "access_token": "access", "refresh_token": "refresh",
        "user_id": "11111111-1111-4111-8111-111111111111", "email": "person@example.com",
    }
    app.run()
    assert any(select.label == "Progress for Data Engineer at Example Co" for select in app.selectbox)
    remove_label = "Remove application for Data Engineer at Example Co"
    next(button for button in app.button if button.label == remove_label).click().run()
    assert client.deleted == []
    assert any(button.label == "Confirm remove application for Data Engineer at Example Co" for button in app.button)
    next(button for button in app.button if button.label == "Cancel remove application for Data Engineer at Example Co").click().run()
    assert client.deleted == []
    next(button for button in app.button if button.label == remove_label).click().run()
    next(button for button in app.button if button.label == "Confirm remove application for Data Engineer at Example Co").click().run()
    assert client.deleted == [("application_queue", [("id", application["id"])])]

    next(button for button in app.button if button.label == "Remove target Example Co").click().run()
    assert any(button.label == "Confirm remove target Example Co" for button in app.button)
    next(button for button in app.button if button.label == "Confirm remove target Example Co").click().run()
    assert client.deleted == [
        ("application_queue", [("id", application["id"])]),
        ("target_companies", [("id", target["id"])]),
    ]


def test_authenticated_user_can_prepare_export_and_signout_clears_export(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    cv = {"id": "aaaaaaaa-1111-4111-8111-111111111111", "filename": "cv.pdf", "object_path": "11111111-1111-4111-8111-111111111111/a/cv.pdf", "mime_type": "application/pdf", "byte_size": 4, "created_at": "2026-10-01T10:00:00Z"}
    client = _FakeClient({"cv_profiles": [cv]})
    _install_fake_supabase(monkeypatch, client)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30)
    app.session_state["hosted_auth"] = {
        "access_token": "access", "refresh_token": "refresh",
        "user_id": "11111111-1111-4111-8111-111111111111", "email": "person@example.com",
    }
    app.run()
    assert app.session_state["hosted_auth"]["privacy_notice_version"] == "policy-v1"
    assert app.session_state["hosted_auth"]["privacy_notice_acknowledged_at"] == "2026-10-01T00:00:00Z"
    next(button for button in app.button if button.label == "Prepare my data export").click().run()
    assert any(button.label == "Download my data export" for button in app.get("download_button"))
    next(button for button in app.button if button.label == "Sign out").click().run()
    assert not app.get("download_button")
    assert any("Sign in" in tab.label for tab in app.tabs)
    assert not app.exception


def test_account_deletion_ui_uses_fresh_otp_and_server_side_verifier(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    monkeypatch.setenv("HOSTED_ACCOUNT_DELETION_ENABLED", "true")
    client = _FakeClient()
    _install_fake_supabase(monkeypatch, client)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30)
    app.session_state["hosted_auth"] = {
        "access_token": "access", "refresh_token": "refresh",
        "user_id": "11111111-1111-4111-8111-111111111111", "email": "person@example.com",
    }
    app.run()
    next(button for button in app.button if button.label == "Email me a fresh deletion code").click().run()
    for item in app.text_input:
        if item.label == "Fresh email code":
            item.set_value("654321")
        elif item.label == "Type DELETE to confirm":
            item.set_value("DELETE")
    next(button for button in app.button if button.label == "Verify code and permanently delete account").click().run()
    assert ("verify_otp", {"email": "person@example.com", "token": "654321", "type": "email"}) in client.auth_actions
    assert client.function_calls == [("delete-account", {"body": {"confirmation": "DELETE"}})]
    assert not app.exception


def test_jobs_cv_match_and_prepare_queue(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    cv = {"id": "aaaaaaaa-1111-4111-8111-111111111111", "filename": "cv.txt", "object_path": "user/cv.txt", "mime_type": "text/plain", "byte_size": 20, "created_at": "2026-10-01"}
    client = _FakeClient({"cv_profiles": [cv]})
    _install_fake_supabase(monkeypatch, client)
    from tau_job_application.hosted_matching import load_public_jobs
    job = next(item for item in load_public_jobs() if item["skills"])
    app = AppTest.from_file(HOSTED_UI, default_timeout=30)
    app.session_state["hosted_auth"] = {"access_token": "access", "refresh_token": "refresh", "user_id": "11111111-1111-4111-8111-111111111111", "email": "person@example.com"}
    app.run()
    role_select = next(select for select in app.selectbox if select.label == "Role to review")
    role_select.set_value(f"{job['title']} · {job['company']} · {', '.join(job['locations'])}").run()
    next(button for button in app.button if button.label == "Compare selected CV").click().run()
    assert app.metric
    next(button for button in app.button if button.label == "Prepare reviewed application").click().run()
    assert client.inserted and client.inserted[0][0] == "application_queue"
    assert client.inserted[0][1]["stage"] == "saved"
    assert not app.exception


def test_linkedin_connection_uses_official_identity_link(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    monkeypatch.setenv("HOSTED_LINKEDIN_ENABLED", "true")
    monkeypatch.setenv("HOSTED_PUBLIC_URL", "https://hosted.example")
    client = _FakeClient()
    _install_fake_supabase(monkeypatch, client)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30)
    app.session_state["hosted_auth"] = {"access_token": "access", "refresh_token": "refresh", "user_id": "11111111-1111-4111-8111-111111111111", "email": "person@example.com"}
    app.run()
    next(button for button in app.button if button.label == "Prepare LinkedIn connection").click().run()
    assert client.auth_actions[0][0] == "link_identity"
    assert client.auth_actions[0][1]["provider"] == "linkedin_oidc"
    assert any(item.label == "Continue to LinkedIn" for item in app.get("link_button"))
    assert not app.exception


def test_signups_are_closed_by_default_until_explicitly_enabled(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    monkeypatch.setenv("HOSTED_SIGNUPS_ENABLED", "true")
    monkeypatch.delenv("HOSTED_PRIVACY_NOTICE_URL", raising=False)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30).run()
    assert [tab.label for tab in app.tabs] == ["Sign in"]
    assert any("Registration is closed" in item.value for item in app.info)
    assert not app.exception


def test_passwordless_forms_reject_empty_input_without_network(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    monkeypatch.setenv("HOSTED_SIGNUPS_ENABLED", "false")
    app = AppTest.from_file(HOSTED_UI, default_timeout=30).run()
    next(button for button in app.button if button.label == "Email me a sign-in link").click().run()
    assert any("valid email address" in item.value for item in app.error)
    next(button for button in app.button if button.label == "Sign in with email code").click().run()
    assert any("numeric code" in item.value for item in app.error)
    assert not app.exception


def test_magic_link_and_otp_signin_success(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    client = _FakeClient()
    _install_fake_supabase(monkeypatch, client)

    app = AppTest.from_file(HOSTED_UI, default_timeout=30).run()
    app.text_input[0].set_value("person@example.com")
    next(button for button in app.button if button.label == "Email me a sign-in link").click().run()
    assert ("sign_in_with_otp", {"email": "person@example.com", "options": {"should_create_user": False}}) in client.auth_actions
    app.text_input[1].set_value("person@example.com")
    app.text_input[2].set_value("654321")
    next(button for button in app.button if button.label == "Sign in with email code").click().run()
    assert ("verify_otp", {"email": "person@example.com", "token": "654321", "type": "email"}) in client.auth_actions
    assert [tab.label for tab in app.tabs] == ["Jobs & CV match", "CV library", "Companies", "Applications", "Account & privacy"]
    assert not app.exception


def test_account_deletion_failure_keeps_session_and_reports_partial_cleanup(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    monkeypatch.setenv("HOSTED_ACCOUNT_DELETION_ENABLED", "true")
    client = _FakeClient()
    def fail_invoke(_name, _options):
        raise RuntimeError("provider failure")
    client.functions.invoke = fail_invoke
    _install_fake_supabase(monkeypatch, client)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30)
    app.session_state["hosted_auth"] = {
        "access_token": "access", "refresh_token": "refresh",
        "user_id": "11111111-1111-4111-8111-111111111111", "email": "person@example.com",
    }
    app.run()
    next(button for button in app.button if button.label == "Email me a fresh deletion code").click().run()
    for item in app.text_input:
        if item.label == "Fresh email code":
            item.set_value("654321")
        elif item.label == "Type DELETE to confirm":
            item.set_value("DELETE")
    next(button for button in app.button if button.label == "Verify code and permanently delete account").click().run()
    assert any("some files may already have been removed" in item.value for item in app.error)
    assert app.session_state["hosted_auth"]["user_id"] == "11111111-1111-4111-8111-111111111111"
    assert not app.exception


def test_sign_in_and_sign_up_reject_empty_credentials_without_network(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    monkeypatch.setenv("HOSTED_SIGNUPS_ENABLED", "true")
    monkeypatch.setenv("HOSTED_PRIVACY_NOTICE_URL", "https://example.com/privacy")
    monkeypatch.setenv("HOSTED_PRIVACY_NOTICE_VERSION", "test-1")
    app = AppTest.from_file(HOSTED_UI, default_timeout=30).run()
    next(button for button in app.button if button.label == "Email me a sign-in link").click().run()
    assert any("valid email address" in item.value for item in app.error)
    next(button for button in app.button if button.label == "Create account with email link").click().run()
    assert any("read and acknowledge" in item.value.lower() for item in app.error)
    assert [tab.label for tab in app.tabs] == ["Sign in", "Create account"]


def test_magic_link_token_hash_callback_establishes_session(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    client = _FakeClient()
    _install_fake_supabase(monkeypatch, client)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30)
    app.session_state["hosted_auth"] = {"access_token": "old", "refresh_token": "old", "user_id": "old-user", "email": "old@example.com"}
    app.session_state["hosted_data_export"] = b"old-private-export"
    app.query_params["token_hash"] = "email-token"
    app.run()
    assert ("verify_otp", {"token_hash": "email-token", "type": "email"}) in client.auth_actions
    assert "hosted_data_export" not in app.session_state
    assert app.session_state["hosted_auth"]["user_id"] == "11111111-1111-4111-8111-111111111111"
    assert not app.exception


def test_linkedin_callback_uses_retained_pkce_client_even_when_signed_in(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    client = _FakeClient()
    _install_fake_supabase(monkeypatch, client)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30)
    app.session_state["hosted_auth"] = {"access_token": "access", "refresh_token": "refresh", "user_id": "11111111-1111-4111-8111-111111111111", "email": "person@example.com"}
    app.query_params["code"] = "linkedin-code"
    app.query_params["oauth_id"] = "44444444-4444-4444-8444-444444444444"
    app.run()
    assert ("exchange_code", {"auth_code": "linkedin-code"}) in client.auth_actions
    assert not app.exception


def test_signup_records_published_notice_version_only_after_acknowledgment(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-only-publishable-key")
    monkeypatch.setenv("HOSTED_SIGNUPS_ENABLED", "true")
    monkeypatch.setenv("HOSTED_PRIVACY_NOTICE_URL", "https://example.com/privacy")
    monkeypatch.setenv("HOSTED_PRIVACY_NOTICE_VERSION", "policy-v1")
    client = _FakeClient()
    requests: list[dict] = []

    client.auth.sign_in_with_otp = requests.append
    _install_fake_supabase(monkeypatch, client)
    app = AppTest.from_file(HOSTED_UI, default_timeout=30).run()
    app.text_input[3].set_value("new@example.com")
    next(button for button in app.button if button.label == "Create account with email link").click().run()
    assert requests == []
    assert any("read and acknowledge" in error.value.lower() for error in app.error)

    app.checkbox[0].check().run()
    next(button for button in app.button if button.label == "Create account with email link").click().run()
    assert len(requests) == 1
    data = requests[0]["options"]["data"]
    assert data["privacy_notice_version"] == "policy-v1"
    assert data["privacy_notice_url"] == "https://example.com/privacy"
    assert requests[0]["email"] == "new@example.com"
    assert not app.exception
