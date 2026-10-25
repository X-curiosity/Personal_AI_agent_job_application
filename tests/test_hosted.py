from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import pytest

from tau_job_application.hosted import (
    MAX_CV_BYTES,
    HostedConfig,
    is_email_confirmation_error,
    is_email_confirmed,
    get_privacy_acceptance,
    request_password_reset,
    complete_password_reset,
    build_data_export,
    add_application,
    add_target,
    delete_application,
    delete_cv,
    delete_target,
    create_cv_download_url,
    list_cvs,
    safe_cv_upload,
    set_application_stage,
    upload_cv,
)


class FakeStorageBucket:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, dict[str, str]]] = []
        self.removed: list[str] = []

    def remove(self, paths: list[str]) -> None:
        self.removed.extend(paths)

    def create_signed_url(self, path: str, expires_in: int) -> dict[str, str]:
        return {"signedURL": f"https://storage.example/signed/{path}?expires={expires_in}"}

    def download(self, path: str) -> bytes:
        return f"file:{path}".encode()

    def upload(self, path: str, content: bytes, options: dict[str, str]) -> None:
        self.uploads.append((path, content, options))


class FakeStorage:
    def __init__(self) -> None:
        self.bucket = FakeStorageBucket()

    def from_(self, bucket: str) -> FakeStorageBucket:
        assert bucket == "private-cvs"
        return self.bucket


class FakeQuery:
    def __init__(self, data: list[dict] | None = None) -> None:
        self.data = data or []
        self.inserted: dict | None = None
        self.updated: dict | None = None
        self.filters: list[tuple[str, object]] = []
        self.return_empty = False
        self.selected: str | None = None

    def select(self, columns: str) -> "FakeQuery":
        self.selected = columns
        return self

    def order(self, _column: str, **_kwargs) -> "FakeQuery":
        return self

    def limit(self, _count: int) -> "FakeQuery":
        return self

    def delete(self) -> "FakeQuery":
        return self

    def insert(self, row: dict) -> "FakeQuery":
        self.inserted = row
        return self

    def update(self, row: dict) -> "FakeQuery":
        self.updated = row
        return self

    def eq(self, key: str, value: object) -> "FakeQuery":
        self.filters.append((key, value))
        return self

    def execute(self) -> SimpleNamespace:
        if self.return_empty:
            return SimpleNamespace(data=[])
        if self.inserted:
            return SimpleNamespace(data=[self.inserted])
        return SimpleNamespace(data=self.data)


class FakeTableClient:
    def __init__(self) -> None:
        self.queries: dict[str, FakeQuery] = {}

    def table(self, name: str) -> FakeQuery:
        return self.queries.setdefault(name, FakeQuery())


class FakeRecoveryAuth:
    def __init__(self) -> None:
        self.reset_email: str | None = None
        self.verified_params: dict | None = None
        self.updated_password: str | None = None
        self.response = SimpleNamespace(
            session=SimpleNamespace(access_token="token"),
            user=SimpleNamespace(email_confirmed_at="2026-10-01T00:00:00Z"),
        )

    def reset_password_for_email(self, email: str) -> None:
        self.reset_email = email

    def verify_otp(self, params: dict) -> SimpleNamespace:
        self.verified_params = params
        return self.response

    def update_user(self, values: dict) -> None:
        self.updated_password = values["password"]


def test_unconfirmed_email_error_is_recognized_by_provider_code() -> None:
    assert is_email_confirmation_error(SimpleNamespace(code="email_not_confirmed"))
    assert not is_email_confirmation_error(SimpleNamespace(code="invalid_credentials"))


def test_email_login_requires_email_confirmation_not_other_confirmation() -> None:
    assert is_email_confirmed(SimpleNamespace(email_confirmed_at="2026-10-01T00:00:00Z"))
    assert not is_email_confirmed(SimpleNamespace(email_confirmed_at=None, confirmed_at=None))
    assert not is_email_confirmed(SimpleNamespace(email_confirmed_at=None, confirmed_at="2026-10-01T00:00:00Z"))


def test_privacy_acceptance_comes_from_read_only_server_receipt() -> None:
    tables = FakeTableClient()
    tables.queries["privacy_notice_acceptances"] = FakeQuery([{
        "notice_version": "v2", "notice_url": "https://example.com/privacy",
        "accepted_at": "2026-10-01T00:00:00Z",
    }])
    client = SimpleNamespace(table=tables.table)
    assert get_privacy_acceptance(client) == {
        "version": "v2", "url": "https://example.com/privacy",
        "acknowledgedAt": "2026-10-01T00:00:00Z",
    }
    tables.queries["privacy_notice_acceptances"] = FakeQuery([])
    assert get_privacy_acceptance(client) is None


def test_password_recovery_uses_otp_and_enforces_confirmation() -> None:
    auth = FakeRecoveryAuth()
    client = SimpleNamespace(auth=auth)
    request_password_reset(client, "  person@example.com ")
    assert auth.reset_email == "person@example.com"
    response = complete_password_reset(client, "person@example.com", "123456", "long-enough-password", "long-enough-password")
    assert response is auth.response
    assert auth.verified_params == {"email": "person@example.com", "token": "123456", "type": "recovery"}
    assert auth.updated_password == "long-enough-password"
    with pytest.raises(ValueError, match="12 characters"):
        complete_password_reset(client, "person@example.com", "123456", "short", "short")
    with pytest.raises(ValueError, match="do not match"):
        complete_password_reset(client, "person@example.com", "123456", "long-enough-password", "different-password")


def test_config_requires_secure_supabase_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://unit-test.supabase.co/")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "public-test-key")
    assert HostedConfig.from_env() == HostedConfig("https://unit-test.supabase.co", "public-test-key")
    monkeypatch.setenv("SUPABASE_URL", "http://unit-test.supabase.co")
    with pytest.raises(RuntimeError, match="HTTPS"):
        HostedConfig.from_env()


def test_upload_scopes_object_path_and_sets_private_file_options() -> None:
    client = SimpleNamespace(storage=FakeStorage())
    owner = str(uuid4())
    saved = safe_cv_upload(client, owner, "../../my cv.pdf", "application/pdf", b"cv bytes")
    path, content, options = client.storage.bucket.uploads[0]
    assert path == saved["object_path"]
    assert path.startswith(f"{owner}/")
    assert ".." not in path.split("/")[-1]
    assert content == b"cv bytes"
    assert options["content-type"] == "application/pdf"
    assert options["upsert"] == "false"
    assert saved["byte_size"] == len(content)


@pytest.mark.parametrize(
    ("user_id", "mime_type", "content", "message"),
    [
        ("not-a-uuid", "application/pdf", b"data", "identity"),
        (str(uuid4()), "image/png", b"data", "PDF"),
        (str(uuid4()), "application/pdf", b"", "between"),
        (str(uuid4()), "application/pdf", b"x" * (MAX_CV_BYTES + 1), "between"),
    ],
)
def test_upload_rejects_invalid_identity_type_or_size(user_id: str, mime_type: str, content: bytes, message: str) -> None:
    client = SimpleNamespace(storage=FakeStorage())
    with pytest.raises(ValueError, match=message):
        safe_cv_upload(client, user_id, "cv.pdf", mime_type, content)
    assert client.storage.bucket.uploads == []


def test_upload_saves_metadata_and_compensates_on_database_failure() -> None:
    owner = str(uuid4())
    storage = FakeStorage()
    tables = FakeTableClient()
    client = SimpleNamespace(storage=storage, table=tables.table)
    row = upload_cv(client, owner, "cv.txt", "text/plain", b"CV")
    assert row["owner_id"] == owner
    assert row["object_path"] == storage.bucket.uploads[0][0]

    broken_tables = FakeTableClient()
    broken_tables.table("cv_profiles").return_empty = True
    broken_client = SimpleNamespace(storage=storage, table=broken_tables.table)
    # An empty insert response simulates an API-side metadata failure.
    with pytest.raises(RuntimeError, match="metadata"):
        upload_cv(broken_client, owner, "other.txt", "text/plain", b"CV")
    assert storage.bucket.removed[-1] == storage.bucket.uploads[-1][0]


def test_signed_cv_download_link_is_short_lived_and_expiry_is_bounded() -> None:
    client = SimpleNamespace(storage=FakeStorage())
    path = f"{uuid4()}/random/cv.pdf"
    assert create_cv_download_url(client, path, 300).endswith("expires=300")
    with pytest.raises(ValueError, match="expire"):
        create_cv_download_url(client, path, 3600)


def test_listed_cv_contains_path_needed_for_signed_download_and_delete() -> None:
    cv = {
        "id": str(uuid4()),
        "filename": "cv.pdf",
        "object_path": f"{uuid4()}/random/cv.pdf",
        "mime_type": "application/pdf",
        "byte_size": 12,
        "created_at": "2026-01-01T00:00:00Z",
    }
    tables = FakeTableClient()
    tables.queries["cv_profiles"] = FakeQuery([cv])
    storage = FakeStorage()
    client = SimpleNamespace(storage=storage, table=tables.table)
    listed = list_cvs(client)
    assert "object_path" in tables.queries["cv_profiles"].selected
    assert create_cv_download_url(client, listed[0]["object_path"]).startswith("https://storage.example/signed/")
    delete_cv(client, listed[0])
    assert storage.bucket.removed == [cv["object_path"]]
    assert tables.queries["cv_profiles"].filters == [("id", cv["id"])]


def test_user_data_export_includes_records_and_private_cv_file() -> None:
    cv = {"id": str(uuid4()), "filename": "cv.pdf", "object_path": f"{uuid4()}/x/cv.pdf", "mime_type": "application/pdf", "byte_size": 4, "created_at": "2026-01-01T00:00:00Z"}
    target = {"id": str(uuid4()), "company_name": "Example", "company_website": None, "created_at": "2026-01-01T00:00:00Z"}
    application = {"id": str(uuid4()), "company_name": "Example", "job_title": "Engineer", "job_url": "https://jobs.example/1", "stage": "saved", "notes": "Keep this private", "cv_profile_id": cv["id"], "created_at": "2026-01-01T00:00:00Z"}
    tables = FakeTableClient()
    tables.queries["cv_profiles"] = FakeQuery([cv])
    tables.queries["target_companies"] = FakeQuery([target])
    tables.queries["application_queue"] = FakeQuery([application])
    client = SimpleNamespace(storage=FakeStorage(), table=tables.table)
    archive_bytes = build_data_export(
        client,
        "person@example.com",
        {"version": "policy-1", "acknowledgedAt": "2026-01-01T00:00:00Z"},
    )
    with ZipFile(BytesIO(archive_bytes)) as archive:
        manifest = json.loads(archive.read("co-apply-export.json"))
        cv_path = f"cv_files/{cv['id']}-cv.pdf"
        assert archive.read(cv_path) == f"file:{cv['object_path']}".encode()
        assert manifest["accountEmail"] == "person@example.com"
        assert manifest["privacyNoticeAcceptance"]["version"] == "policy-1"
        assert manifest["targetCompanies"][0]["company_name"] == "Example"
        assert manifest["applications"][0]["notes"] == "Keep this private"
        assert "object_path" not in manifest["cvProfiles"][0]


def test_company_target_validates_name_and_https() -> None:
    client = FakeTableClient()
    owner = str(uuid4())
    row = add_target(client, owner, "  Example   Corp ", "https://example.com/careers")
    assert row["company_name"] == "Example Corp"
    assert client.queries["target_companies"].inserted["owner_id"] == owner
    with pytest.raises(ValueError, match="HTTPS"):
        add_target(client, owner, "Example", "http://example.com")


def test_application_requires_official_https_job_link_and_bounded_fields() -> None:
    client = FakeTableClient()
    owner = str(uuid4())
    cv_id = str(uuid4())
    row = add_application(client, owner, "Example Corp", "Engineer", "https://jobs.example.com/123", cv_id)
    assert row["stage"] == "saved"
    assert row["owner_id"] == owner
    assert row["cv_profile_id"] == cv_id
    with pytest.raises(ValueError, match="HTTPS"):
        add_application(client, owner, "Example", "Engineer", "javascript:alert(1)", None)
    with pytest.raises(ValueError, match="title"):
        add_application(client, owner, "Example", " ", "https://jobs.example.com/123", None)


def test_target_and_application_deletion_are_scoped_by_id_and_rls() -> None:
    client = FakeTableClient()
    target_id, application_id = str(uuid4()), str(uuid4())
    delete_target(client, target_id)
    delete_application(client, application_id)
    assert client.queries["target_companies"].filters == [("id", target_id)]
    assert client.queries["application_queue"].filters == [("id", application_id)]


def test_application_progress_has_no_implicit_submit_path() -> None:
    client = FakeTableClient()
    app_id = str(uuid4())
    set_application_stage(client, app_id, "applied")
    query = client.queries["application_queue"]
    assert query.updated == {"stage": "applied"}
    assert query.filters == [("id", app_id)]
    with pytest.raises(ValueError, match="stage"):
        set_application_stage(client, app_id, "submitted-automatically")


def test_schema_uses_owner_rls_and_private_bucket() -> None:
    root = Path(__file__).resolve().parents[1]
    sql = (root / "supabase/migrations/202610270001_hosted_mvp.sql").read_text()
    assert sql.count("enable row level security") == 5
    assert sql.count("owner_id = (select auth.uid())") == 8
    assert "public = false" in sql
    assert "(storage.foldername(name))[1] = (select auth.uid())::text" in sql
    assert "public.hosted_user_is_active()" in sql
    assert "consume_hosted_oauth_state" in sql
    assert "hosted_oauth_states" in sql
    assert "public.hosted_user_has_privacy_acceptance()" in sql
    assert "hosted_privacy_acceptance_after_signup" in sql
    assert "public.privacy_notice_acceptances" in sql
    assert "revoke all on public.hosted_privacy_config, public.privacy_notice_acceptances from PUBLIC, anon, authenticated" in sql
    assert "from auth.users where id = (select auth.uid())" in sql
    assert "revoke all on public.cv_profiles, public.target_companies, public.application_queue from anon" in sql
