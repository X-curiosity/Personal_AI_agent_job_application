"""Passwordless Supabase Auth and optional LinkedIn identity linking."""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

PKCE_STORAGE_KEY = "supabase.auth.token-code-verifier"

EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _email(value: str) -> str:
    value = value.strip()
    if not EMAIL.fullmatch(value) or len(value) > 320:
        raise ValueError("Enter a valid email address.")
    return value


def request_magic_link(client: Any, email: str, *, create_account: bool, redirect_to: str, privacy_version: str = "", privacy_url: str = "") -> None:
    options: dict[str, Any] = {"should_create_user": create_account}
    if redirect_to:
        if not redirect_to.startswith("https://") and not redirect_to.startswith("http://127.0.0.1") and not redirect_to.startswith("http://localhost"):
            raise ValueError("The authentication redirect must use HTTPS.")
        options["email_redirect_to"] = redirect_to.rstrip("/")
    if create_account:
        if not privacy_version:
            raise ValueError("Privacy Notice acknowledgment is required.")
        if not privacy_url.startswith("https://"):
            raise ValueError("A published Privacy Notice URL is required.")
        options["data"] = {"privacy_notice_version": privacy_version, "privacy_notice_url": privacy_url}
    client.auth.sign_in_with_otp({"email": _email(email), "options": options})


def verify_email_code(client: Any, email: str, token: str) -> Any:
    token = token.strip()
    if not re.fullmatch(r"[0-9]{6,10}", token):
        raise ValueError("Enter the numeric code from your email.")
    return client.auth.verify_otp({"email": _email(email), "token": token, "type": "email"})


def exchange_email_token(client: Any, token_hash: str) -> Any:
    if not token_hash.strip() or len(token_hash) > 4096:
        raise ValueError("Invalid email callback.")
    return client.auth.verify_otp({"token_hash": token_hash.strip(), "type": "email"})


def exchange_auth_code(client: Any, code: str) -> Any:
    if not code.strip() or len(code) > 4096:
        raise ValueError("Invalid authentication callback.")
    return client.auth.exchange_code_for_session({"auth_code": code.strip()})


def request_deletion_code(client: Any) -> None:
    client.auth.reauthenticate()


def create_oauth_state(client: Any, user_id: str) -> str:
    state_id = str(uuid4())
    client.table("hosted_oauth_states").insert({"id": state_id, "owner_id": str(UUID(user_id)), "provider": "linkedin_oidc"}).execute()
    return state_id


def save_oauth_verifier(client: Any, state_id: str, verifier: str) -> None:
    if len(verifier) < 32:
        raise ValueError("OAuth verifier was not created.")
    client.table("hosted_oauth_states").update({"code_verifier": verifier}).eq("id", str(UUID(state_id))).execute()


def consume_oauth_verifier(client: Any, state_id: str) -> str:
    response = client.rpc("consume_hosted_oauth_state", {"state_id": str(UUID(state_id))}).execute()
    rows = response.data or []
    verifier = rows[0].get("code_verifier") if isinstance(rows, list) and rows else None
    if not verifier:
        raise ValueError("OAuth state is invalid, used, or expired.")
    return str(verifier)


def begin_linkedin_link(client: Any, redirect_to: str) -> str:
    if not redirect_to.startswith("https://") and not redirect_to.startswith("http://127.0.0.1") and not redirect_to.startswith("http://localhost"):
        raise ValueError("LinkedIn linking requires an HTTPS hosted URL.")
    response = client.auth.link_identity({"provider": "linkedin_oidc", "options": {"redirect_to": redirect_to.rstrip("/"), "scopes": "openid profile email"}})
    if not getattr(response, "url", None):
        raise RuntimeError("LinkedIn did not return a connection URL.")
    return str(response.url)


def unlink_linkedin(client: Any, identity_id: str) -> None:
    response = client.auth.get_user_identities()
    identity = next((item for item in (getattr(response, "identities", None) or []) if str(item.identity_id) == identity_id and str(item.provider) in {"linkedin", "linkedin_oidc"}), None)
    if identity is None:
        raise ValueError("LinkedIn connection not found.")
    client.auth.unlink_identity(identity)


def linkedin_identities(client: Any) -> list[dict[str, str]]:
    response = client.auth.get_user_identities()
    return [
        {"id": str(identity.identity_id), "provider": str(identity.provider), "email": str(getattr(identity, "email", "") or "")}
        for identity in (getattr(response, "identities", None) or [])
        if str(getattr(identity, "provider", "")).casefold() in {"linkedin", "linkedin_oidc"}
    ]
