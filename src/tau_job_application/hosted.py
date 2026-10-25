"""Supabase-backed data access for the isolated hosted MVP.

The module deliberately uses only a user's publishable/anon key plus that
user's access token. Every private table and storage request is therefore
subject to Supabase RLS; a service-role key is never used by the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import io
import json
import os
from pathlib import PurePosixPath
import re
from typing import Any
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile

MAX_CV_BYTES = 10 * 1024 * 1024
MAX_EXPORT_CV_BYTES = 50 * 1024 * 1024
ALLOWED_CV_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
}
CV_BUCKET = "private-cvs"


@dataclass(frozen=True)
class HostedConfig:
    supabase_url: str
    publishable_key: str

    @classmethod
    def from_env(cls) -> "HostedConfig":
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        key = (os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")).strip()
        if not url or not key:
            raise RuntimeError("Hosted authentication is not configured.")
        if not url.startswith("https://"):
            raise RuntimeError("SUPABASE_URL must use HTTPS.")
        return cls(url, key)


def is_email_confirmation_error(error: BaseException) -> bool:
    """Supabase Auth uses this stable code when sign-in precedes confirmation."""
    return getattr(error, "code", None) == "email_not_confirmed"


def is_email_confirmed(user: Any) -> bool:
    """Only an explicit email confirmation satisfies the email-only login policy."""
    return bool(getattr(user, "email_confirmed_at", None))


def get_privacy_acceptance(client: Any) -> dict[str, str] | None:
    """Read the immutable server-recorded notice receipt for the signed-in user."""
    response = client.table("privacy_notice_acceptances").select(
        "notice_version, notice_url, accepted_at"
    ).limit(1).execute()
    rows = response.data or []
    if not rows:
        return None
    row = rows[0]
    return {
        "version": str(row.get("notice_version") or ""),
        "url": str(row.get("notice_url") or ""),
        "acknowledgedAt": str(row.get("accepted_at") or ""),
    }


def request_password_reset(client: Any, email: str) -> None:
    client.auth.reset_password_for_email(email.strip())


def complete_password_reset(client: Any, email: str, token: str, password: str, confirmation: str) -> Any:
    if not email.strip() or not token.strip():
        raise ValueError("Enter the email address and recovery code.")
    if len(password) < 12:
        raise ValueError("The new password must be at least 12 characters.")
    if password != confirmation:
        raise ValueError("The passwords do not match.")
    response = client.auth.verify_otp({"email": email.strip(), "token": token.strip(), "type": "recovery"})
    if not getattr(response, "session", None) or not is_email_confirmed(getattr(response, "user", None)):
        raise ValueError("The recovery code is invalid, expired, or not linked to a confirmed email.")
    client.auth.update_user({"password": password})
    return response


def create_user_client(config: HostedConfig, access_token: str | None = None, refresh_token: str | None = None, auth_storage: Any | None = None) -> Any:
    """Create a fresh client per Streamlit session; never share mutable auth state."""
    try:
        from supabase import create_client
    except ImportError as exc:  # pragma: no cover - exercised in deployment setup
        raise RuntimeError("Install the 'supabase' application dependency.") from exc

    if auth_storage is None:
        client = create_client(config.supabase_url, config.publishable_key)
    else:
        from supabase.lib.client_options import SyncClientOptions
        client = create_client(config.supabase_url, config.publishable_key, options=SyncClientOptions(storage=auth_storage))
    if access_token and refresh_token:
        client.auth.set_session(access_token, refresh_token)
    return client


def safe_cv_upload(client: Any, user_id: str, filename: str, mime_type: str, content: bytes) -> dict[str, Any]:
    """Validate and upload a CV into the user's private object namespace."""
    try:
        owner_id = str(UUID(user_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid account identity.") from exc
    if mime_type not in ALLOWED_CV_TYPES:
        raise ValueError("Upload a PDF, DOCX, TXT, or Markdown CV.")
    if not content or len(content) > MAX_CV_BYTES:
        raise ValueError("CV files must be between 1 byte and 10 MB.")

    basename = PurePosixPath(filename.replace("\\", "/")).name.strip()
    basename = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)[:100].strip("._") or "cv"
    suffix = ALLOWED_CV_TYPES[mime_type]
    if not basename.lower().endswith(suffix):
        basename = f"{basename}{suffix}"
    object_path = f"{owner_id}/{uuid4().hex}/{basename}"
    client.storage.from_(CV_BUCKET).upload(
        object_path,
        content,
        {"content-type": mime_type, "cache-control": "3600", "upsert": "false"},
    )
    return {
        "object_path": object_path,
        "filename": basename,
        "mime_type": mime_type,
        "byte_size": len(content),
    }


def upload_cv(client: Any, user_id: str, filename: str, mime_type: str, content: bytes) -> dict[str, Any]:
    """Upload a private object and its row; compensate if metadata insertion fails."""
    upload = safe_cv_upload(client, user_id, filename, mime_type, content)
    try:
        return save_cv_metadata(client, user_id, upload)
    except Exception:
        try:
            client.storage.from_(CV_BUCKET).remove([upload["object_path"]])
        except Exception:
            # The storage API and Postgres cannot share one transaction. The
            # error is surfaced; an orphaned object may require owner cleanup.
            pass
        raise


def list_cvs(client: Any) -> list[dict[str, Any]]:
    response = client.table("cv_profiles").select(
        "id, filename, object_path, mime_type, byte_size, created_at"
    ).order("created_at", desc=True).execute()
    return response.data or []


def save_cv_metadata(client: Any, user_id: str, upload: dict[str, Any]) -> dict[str, Any]:
    row = {
        "owner_id": str(UUID(user_id)),
        "filename": upload["filename"],
        "object_path": upload["object_path"],
        "mime_type": upload["mime_type"],
        "byte_size": upload["byte_size"],
    }
    response = client.table("cv_profiles").insert(row).execute()
    if not response.data:
        raise RuntimeError("CV metadata was not saved.")
    return response.data[0]


def delete_cv(client: Any, cv: dict[str, Any]) -> None:
    """Delete object first; keep metadata if storage deletion fails."""
    client.storage.from_(CV_BUCKET).remove([cv["object_path"]])
    client.table("cv_profiles").delete().eq("id", cv["id"]).execute()


def create_cv_download_url(client: Any, object_path: str, expires_seconds: int = 300) -> str:
    """Create a short-lived link only on an explicit user action."""
    if not 60 <= expires_seconds <= 600:
        raise ValueError("Download links must expire within 1 to 10 minutes.")
    response = client.storage.from_(CV_BUCKET).create_signed_url(object_path, expires_seconds)
    if isinstance(response, dict):
        url = response.get("signedURL") or response.get("signedUrl") or response.get("signed_url")
    else:
        url = getattr(response, "signedURL", None) or getattr(response, "signed_url", None)
    if not isinstance(url, str) or not url:
        raise RuntimeError("The storage provider did not return a signed download link.")
    return url


def build_data_export(
    client: Any,
    account_email: str = "",
    privacy_acceptance: dict[str, str] | None = None,
    linked_identities: list[dict[str, str]] | None = None,
) -> bytes:
    """Build a user-requested ZIP containing their records and original CVs."""
    cvs = list_cvs(client)
    targets = list_targets(client)
    applications = list_applications(client)
    cv_files: list[tuple[str, bytes]] = []
    total_bytes = 0
    bucket = client.storage.from_(CV_BUCKET)
    for cv in cvs:
        content = bucket.download(cv["object_path"])
        total_bytes += len(content)
        if total_bytes > MAX_EXPORT_CV_BYTES:
            raise ValueError("Your CV files exceed the 50 MB export limit. Download files individually.")
        filename = PurePosixPath(str(cv["filename"]).replace("\\", "/")).name
        cv_files.append((f"cv_files/{cv['id']}-{filename}", content))

    manifest = {
        "schemaVersion": 1,
        "exportedAt": datetime.now(UTC).isoformat(),
        "accountEmail": account_email,
        "privacyNoticeAcceptance": privacy_acceptance or {},
        "linkedIdentities": linked_identities or [],
        "cvProfiles": [
            {key: cv[key] for key in ("id", "filename", "mime_type", "byte_size", "created_at")}
            for cv in cvs
        ],
        "targetCompanies": targets,
        "applications": applications,
    }
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("co-apply-export.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for archive_path, content in cv_files:
            archive.writestr(archive_path, content)
    return output.getvalue()


def list_targets(client: Any) -> list[dict[str, Any]]:
    response = client.table("target_companies").select(
        "id, company_name, company_website, created_at"
    ).order("created_at", desc=True).execute()
    return response.data or []


def add_target(client: Any, user_id: str, name: str, website: str = "") -> dict[str, Any]:
    company_name = " ".join(name.split())
    if not company_name or len(company_name) > 160:
        raise ValueError("Company name must be between 1 and 160 characters.")
    website = website.strip()
    if website and not re.fullmatch(r"https://[^\s]+", website, flags=re.IGNORECASE):
        raise ValueError("Company links must be HTTPS URLs.")
    response = client.table("target_companies").insert({
        "owner_id": str(UUID(user_id)),
        "company_name": company_name,
        "company_website": website or None,
    }).execute()
    if not response.data:
        raise RuntimeError("Company target was not saved.")
    return response.data[0]


def delete_target(client: Any, target_id: str) -> None:
    client.table("target_companies").delete().eq("id", str(UUID(target_id))).execute()


def list_applications(client: Any) -> list[dict[str, Any]]:
    response = client.table("application_queue").select(
        "id, company_name, job_title, job_url, stage, notes, cv_profile_id, created_at"
    ).order("created_at", desc=True).execute()
    return response.data or []


def add_application(
    client: Any,
    user_id: str,
    company_name: str,
    job_title: str,
    job_url: str,
    cv_profile_id: str | None,
    notes: str = "",
) -> dict[str, Any]:
    company_name = " ".join(company_name.split())
    job_title = " ".join(job_title.split())
    if not company_name or len(company_name) > 160:
        raise ValueError("Choose a company name between 1 and 160 characters.")
    if not job_title or len(job_title) > 200:
        raise ValueError("Enter a role title between 1 and 200 characters.")
    if not re.fullmatch(r"https://[^\s]+", job_url.strip(), flags=re.IGNORECASE):
        raise ValueError("Enter a valid HTTPS job URL and verify its source before opening it.")
    if len(notes) > 4000:
        raise ValueError("Notes must be 4,000 characters or fewer.")
    row = {
        "owner_id": str(UUID(user_id)),
        "company_name": company_name,
        "job_title": job_title,
        "job_url": job_url.strip(),
        "cv_profile_id": str(UUID(cv_profile_id)) if cv_profile_id else None,
        "notes": notes.strip(),
        "stage": "saved",
    }
    response = client.table("application_queue").insert(row).execute()
    if not response.data:
        raise RuntimeError("Application was not saved.")
    return response.data[0]


def delete_application(client: Any, application_id: str) -> None:
    client.table("application_queue").delete().eq("id", str(UUID(application_id))).execute()


def set_application_stage(client: Any, application_id: str, stage: str) -> None:
    if stage not in {"saved", "preparing", "ready", "applied"}:
        raise ValueError("Unsupported application stage.")
    client.table("application_queue").update({"stage": stage}).eq("id", str(UUID(application_id))).execute()
