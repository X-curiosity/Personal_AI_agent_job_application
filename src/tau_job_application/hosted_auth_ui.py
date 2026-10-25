"""Streamlit passwordless registration/sign-in UI."""
from __future__ import annotations

import os
from typing import Any, Callable

import streamlit as st

from tau_job_application.hosted import HostedConfig, create_user_client
from tau_job_application.hosted_auth import request_magic_link, verify_email_code


def _redirect() -> str:
    return os.getenv("HOSTED_PUBLIC_URL", "").strip()


def render_auth_screen(config: HostedConfig, capture_session: Callable[[Any], None]) -> None:
    st.title("Hired")
    st.caption("Private career workspace · passwordless hosted preview")
    if st.session_state.pop("hosted_account_deleted", False):
        st.success("Your account and active hosted records were removed. Provider backup retention may still apply.")
    if st.session_state.pop("hosted_auth_message", None) == "sent":
        st.success("Check your email for a secure sign-in link. You can also enter the numeric code below.")
    signup_requested = os.getenv("HOSTED_SIGNUPS_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    privacy_url = os.getenv("HOSTED_PRIVACY_NOTICE_URL", "").strip()
    privacy_version = os.getenv("HOSTED_PRIVACY_NOTICE_VERSION", "").strip()
    signup_enabled = signup_requested and privacy_url.startswith("https://") and bool(privacy_version)
    tabs = st.tabs(["Sign in"] + (["Create account"] if signup_enabled else []))

    with tabs[0]:
        st.markdown("We’ll email you a secure link—no password to remember.")
        with st.form("hosted-magic-login"):
            email = st.text_input("Email address", autocomplete="email", key="hosted-login-email")
            submitted = st.form_submit_button("Email me a sign-in link", type="primary", use_container_width=True)
        if submitted:
            try:
                request_magic_link(create_user_client(config), email, create_account=False, redirect_to=_redirect())
                st.success("If your account exists, a sign-in email is on its way.")
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Could not send a sign-in email. Wait briefly and try again.")
        with st.form("hosted-code-login"):
            code_email = st.text_input("Email for code sign-in", autocomplete="email", key="hosted-code-email")
            code = st.text_input("6-digit email code", autocomplete="one-time-code", max_chars=10)
            verified = st.form_submit_button("Sign in with email code")
        if verified:
            try:
                response = verify_email_code(create_user_client(config), code_email, code)
                capture_session(response)
                if st.session_state.get("hosted_auth"):
                    st.rerun()
                st.error("The code did not establish a confirmed account session.")
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.error("The email code is invalid or expired. Request a new one.")

    if signup_enabled:
        with tabs[1]:
            st.link_button("Read the Privacy Notice", privacy_url)
            with st.form("hosted-magic-signup"):
                email = st.text_input("Email address", autocomplete="email", key="hosted-signup-email")
                acknowledged = st.checkbox("I have read and acknowledge the Privacy Notice.")
                submitted = st.form_submit_button("Create account with email link", type="primary", use_container_width=True)
            if submitted:
                if not acknowledged:
                    st.error("Read and acknowledge the Privacy Notice before creating an account.")
                else:
                    try:
                        request_magic_link(create_user_client(config), email, create_account=True, redirect_to=_redirect(), privacy_version=privacy_version, privacy_url=privacy_url)
                        st.success("Check your email to confirm your address and create your account.")
                    except ValueError as exc:
                        st.error(str(exc))
                    except Exception:
                        st.error("Could not start registration. Check the address or try again later.")
    else:
        st.info("Registration is closed until the published Privacy Notice and email delivery are configured." if signup_requested else "New account registration is temporarily closed.")
