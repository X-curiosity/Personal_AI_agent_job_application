"""Connected accounts view: link GitHub, LinkedIn, and Gmail to Co-Apply GPT.

Linking an account loads the preferences that legitimately exist there:
GitHub's public profile facts, LinkedIn's OpenID identity claims. Tokens are
never stored. Gmail reply reading stays in each application workspace with
per-conversation consent.
"""
from __future__ import annotations

import os

import streamlit as st

from tau_job_application.accounts import (
    complete_linkedin_signin,
    connect_github,
    linkedin_authorization_url,
    new_oauth_state,
)


_BRAND_LOGOS = {
    "github": ("https://cdn.simpleicons.org/github/173a31", "GH"),
    "linkedin": ("https://cdn.simpleicons.org/linkedin/0a66c2", "in"),
}


def _account_card(provider: str, title: str, account, disconnect_key: str, on_disconnect) -> bool:
    """Render one provider's status with its real brand logo; returns True when connected."""

    logo_url, monogram = _BRAND_LOGOS[provider]
    with st.container(border=True):
        header = st.columns((1, 5, 1))
        if st.session_state.get("account-logos"):
            image = account.avatar_url if account and account.avatar_url else logo_url
            header[0].image(image, width=42)
        else:
            header[0].markdown(
                f'<div style="width:42px;height:42px;border-radius:10px;background:#eef2ea;border:1px solid #dce4d9;'
                f'display:grid;place-items:center;font-weight:800;color:#173a31">{monogram}</div>',
                unsafe_allow_html=True,
            )
        if account:
            header[1].markdown(f"**{title}** · connected")
            header[1].caption(
                " · ".join(part for part in (account.display_name, account.email, f"linked {account.connected_at[:10]}") if part)
            )
            if account.detail:
                header[1].write(account.detail)
            if header[2].button("Unlink", key=disconnect_key):
                on_disconnect()
                st.rerun()
        else:
            header[1].markdown(f"**{title}** · not connected")
    return account is not None


def render_accounts(api, track: str) -> None:
    store = api._account_store()
    st.markdown('<div class="section-kicker">Your identity, your rules</div><h1>Connected accounts</h1>', unsafe_allow_html=True)
    st.write(
        "Link an account once and Co-Apply GPT preloads what legitimately exists there: "
        "public GitHub profile facts and your verified LinkedIn identity. Your interests, residency, "
        "and evidence stay the ones you set here."
    )
    st.caption("No token is ever stored. LinkedIn is used through its official OpenID Connect sign-in only; nothing is scraped or automated.")
    st.checkbox(
        "Load remote avatars and brand logos", key="account-logos",
        help="Off by default: loading a remote image shares your IP address with its host (account avatar or the Simple Icons CDN for brand logos).",
    )

    github = store.get("github")
    linkedin = store.get("linkedin")

    st.subheader("GitHub")
    if not _account_card("github", "GitHub", github, "unlink-github", lambda: store.remove("github")):
        username = st.text_input("GitHub username", placeholder="octocat", max_chars=100, key="github-username")
        if st.button("Connect GitHub", type="primary", key="connect-github"):
            try:
                with st.spinner("Reading the public GitHub profile…"):
                    store.save(connect_github(username))
                st.success("GitHub account linked.")
                st.rerun()
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))
        st.caption("Uses only the public GitHub API; no token and no OAuth needed for public data.")
    else:
        shared = api.WORKSPACES.shared_profile()
        if not shared.get("github", "").strip():
            if st.button(f"Use github.com/{github.subject} as my profile link", key="prefill-github"):
                updated = dict(shared)
                updated["github"] = f"https://github.com/{github.subject}"
                api.WORKSPACES.save_shared_profile(updated)
                st.success("Saved to your shared profile; new workspaces will use it.")

    st.subheader("LinkedIn")
    # Handle the OAuth return before rendering the card.
    params = st.query_params
    code, state = params.get("code", ""), params.get("state", "")
    if code and state:
        expected = st.session_state.get("linkedin-oauth-state")
        client_id = os.environ.get("LINKEDIN_CLIENT_ID", "")
        client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
        redirect_uri = os.environ.get("LINKEDIN_REDIRECT_URI", "")
        st.query_params.clear()
        st.query_params["view"] = "account"
        if not expected or state != expected:
            st.error("The LinkedIn sign-in state did not match; start the connection again.")
        else:
            try:
                with st.spinner("Verifying your LinkedIn identity…"):
                    store.save(complete_linkedin_signin(
                        code=code, client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri,
                    ))
                st.session_state.pop("linkedin-oauth-state", None)
                st.success("LinkedIn identity verified and linked.")
                st.rerun()
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))

    if not _account_card("linkedin", "LinkedIn", linkedin, "unlink-linkedin", lambda: store.remove("linkedin")):
        client_id = os.environ.get("LINKEDIN_CLIENT_ID", "")
        redirect_uri = os.environ.get("LINKEDIN_REDIRECT_URI", "")
        if client_id and os.environ.get("LINKEDIN_CLIENT_SECRET") and redirect_uri:
            state = new_oauth_state()
            st.session_state["linkedin-oauth-state"] = state
            st.link_button(
                "Sign in with LinkedIn",
                linkedin_authorization_url(client_id=client_id, redirect_uri=redirect_uri, state=state),
                type="primary",
            )
            st.caption("Official OpenID Connect sign-in on linkedin.com; you return here automatically.")
        else:
            with st.expander("One-time setup: connect your own LinkedIn app", expanded=True):
                st.markdown(
                    "LinkedIn only allows identity sign-in through an app you register yourself (5 minutes):\n\n"
                    "1. Create an app at [developer.linkedin.com](https://developer.linkedin.com/) → **Auth** → add **Sign In with LinkedIn using OpenID Connect**.\n"
                    "2. Add the redirect URL `http://127.0.0.1:8506/?view=account` to the app's authorized redirect URLs.\n"
                    "3. Restart Co-Apply GPT with:\n\n"
                    "```bash\n"
                    "export LINKEDIN_CLIENT_ID=\"your-client-id\"\n"
                    "export LINKEDIN_CLIENT_SECRET=\"your-client-secret\"\n"
                    "export LINKEDIN_REDIRECT_URI=\"http://127.0.0.1:8506/?view=account\"\n"
                    "./run.sh\n"
                    "```"
                )
                st.caption(
                    "Honest limit: LinkedIn gives regular apps identity claims only (name, email, picture). "
                    "There is no API for your CV or job preferences, and this app will never scrape them. "
                    "Keep your CV and interests here as the source of truth."
                )

    st.subheader("Gmail")
    with st.container(border=True):
        st.markdown("**Gmail** · per-conversation replies")
        st.caption(
            "Gmail works differently by design: inside each application workspace you bind one exact conversation "
            "and expected sender, grant read consent, and provide a token you provision yourself. Clear replies "
            "can then update that application's status automatically (future-only, non-regressive, audited). "
            "There is no whole-inbox access."
        )
        if st.button("Open my applications to bind a conversation", key="gmail-goto"):
            st.query_params.clear()
            st.query_params["view"] = "applications"
            st.session_state.pop("topnav", None)
            st.rerun()
