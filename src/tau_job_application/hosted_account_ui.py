"""Hosted account, LinkedIn connection, export, and fresh-OTP deletion UI."""
from __future__ import annotations

import os
from typing import Any

import streamlit as st

from tau_job_application.hosted import HostedConfig, build_data_export, create_user_client
from supabase_auth import SyncMemoryStorage

from tau_job_application.hosted_auth import begin_linkedin_link, create_oauth_state, linkedin_identities, request_deletion_code, save_oauth_verifier, unlink_linkedin, verify_email_code


def render_account(client: Any, config: HostedConfig, auth: dict[str, str], capture_session: Any) -> None:
    st.subheader("Account and privacy")
    st.text(f"Signed in as {auth.get('email', '')}")
    privacy_url = os.getenv("HOSTED_PRIVACY_NOTICE_URL", "").strip()
    if privacy_url.startswith("https://"):
        st.link_button("Open Privacy Notice", privacy_url)

    st.markdown("### LinkedIn connection")
    st.caption("Optional official OpenID Connect link. Basic identity only; no scraping, job preferences, messages, or automatic profile import.")
    try:
        identities = linkedin_identities(client)
    except Exception:
        identities = []
        st.error("Could not load LinkedIn connection status.")
    if identities:
        st.success("LinkedIn is connected to this account.")
        if not os.getenv("HOSTED_LINKEDIN_ENABLED", "false").strip().lower() in {"1", "true", "yes"}:
            st.caption("New LinkedIn connections are disabled; existing connections can be removed.")
        for identity in identities:
            if st.button("Disconnect LinkedIn", key=f"unlink-{identity['id']}"):
                try:
                    unlink_linkedin(client, identity["id"])
                    st.success("LinkedIn disconnected. Your email sign-in remains active.")
                    st.rerun()
                except Exception:
                    st.error("Could not disconnect LinkedIn. Email sign-in remains available.")
    elif os.getenv("HOSTED_LINKEDIN_ENABLED", "false").strip().lower() in {"1", "true", "yes"}:
        if st.button("Prepare LinkedIn connection", key="hosted-linkedin-prepare"):
            state_id = None
            try:
                state_id = create_oauth_state(client, auth["user_id"])
                storage = SyncMemoryStorage()
                oauth_client = create_user_client(config, auth["access_token"], auth["refresh_token"], auth_storage=storage)
                base_url = os.getenv("HOSTED_PUBLIC_URL", "").strip().rstrip("/")
                st.session_state.hosted_linkedin_url = begin_linkedin_link(oauth_client, f"{base_url}/?oauth_id={state_id}")
                save_oauth_verifier(client, state_id, storage.get_item("supabase.auth.token-code-verifier") or "")
                st.session_state.hosted_linkedin_pending = True
            except Exception:
                if state_id:
                    client.table("hosted_oauth_states").delete().eq("id", state_id).execute()
                st.error("LinkedIn is not configured. Check the provider and hosted redirect URL.")
        if st.session_state.get("hosted_linkedin_url"):
            st.link_button("Continue to LinkedIn", st.session_state.hosted_linkedin_url)
            st.caption("LinkedIn will return you to Hired to finish the connection.")
    else:
        st.info("LinkedIn connection is disabled until the official LinkedIn provider and redirect are configured.")

    st.markdown("### Export your data")
    if st.button("Prepare my data export", type="primary", key="hosted-prepare-export"):
        try:
            st.session_state.hosted_data_export = build_data_export(client, auth.get("email", ""), {"version": auth.get("privacy_notice_version", ""), "url": auth.get("privacy_notice_url", ""), "acknowledgedAt": auth.get("privacy_notice_acknowledged_at", "")}, identities)
            st.success("Export is ready. Download it, then clear it from this session.")
        except Exception:
            st.error("Could not prepare your export. Try again or download CVs individually.")
    if st.session_state.get("hosted_data_export"):
        st.download_button("Download my data export", data=st.session_state.hosted_data_export, file_name="hired-export.zip", mime="application/zip")
        if st.button("Clear export from this session"):
            st.session_state.pop("hosted_data_export", None)
            st.rerun()

    st.markdown("### Delete account and all hosted data")
    if os.getenv("HOSTED_ACCOUNT_DELETION_ENABLED", "false").strip().lower() not in {"1", "true", "yes"}:
        st.info("Account deletion remains disabled until the fresh-OTP server check is deployed and tested.")
        return
    st.warning("Permanent deletion includes CVs, targets, applications, and linked identity data in the active service. Provider backup retention may apply.")
    if st.button("Email me a fresh deletion code", key="hosted-delete-request"):
        try:
            request_deletion_code(client)
            st.session_state.hosted_delete_code_sent = True
            st.success("Check your email for a fresh security code.")
        except Exception:
            st.error("Could not send a deletion security code. Wait briefly and try again.")
    if st.session_state.get("hosted_delete_code_sent"):
        with st.form("hosted-delete-account"):
            code = st.text_input("Fresh email code", autocomplete="one-time-code", max_chars=10)
            confirmation = st.text_input("Type DELETE to confirm")
            submitted = st.form_submit_button("Verify code and permanently delete account")
        if submitted:
            if confirmation != "DELETE":
                st.error("Type DELETE exactly to confirm.")
            else:
                try:
                    response = verify_email_code(client, auth.get("email", ""), code)
                    capture_session(response)
                    fresh = st.session_state.hosted_auth
                    deletion_client = create_user_client(config, fresh["access_token"], fresh["refresh_token"])
                    deletion_client.functions.invoke("delete-account", invoke_options={"body": {"confirmation": "DELETE"}})
                    st.session_state.clear()
                    st.session_state.hosted_account_deleted = True
                    st.rerun()
                except Exception:
                    st.error("Deletion was not completed. The code may be expired or cleanup may have failed; some files may already have been removed.")
