"""Small, isolated multi-user Streamlit MVP (not the local SQLite application)."""

from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from supabase_auth import SyncMemoryStorage

from tau_job_application.hosted_auth import PKCE_STORAGE_KEY, consume_oauth_verifier, exchange_auth_code, exchange_email_token
from tau_job_application.hosted_auth_ui import render_auth_screen
from tau_job_application.hosted_account_ui import render_account
from tau_job_application.hosted_matching import filter_jobs, load_public_jobs, match_cv_to_job
from tau_job_application.hosted import (
    ALLOWED_CV_TYPES,
    MAX_CV_BYTES,
    HostedConfig,
    add_application,
    add_target,
    build_data_export,
    create_user_client,
    create_cv_download_url,
    get_privacy_acceptance,
    delete_application,
    delete_cv,
    delete_target,
    list_applications,
    list_cvs,
    list_targets,
    is_email_confirmed,
    upload_cv,
    set_application_stage,
)


st.set_page_config(page_title="Co-Apply GPT · Hosted", page_icon="🧭", layout="wide")


def _capture_session(response: Any) -> None:
    session = getattr(response, "session", None)
    user = getattr(response, "user", None)
    if session is None or user is None or not is_email_confirmed(user):
        st.session_state.pop("hosted_auth", None)
        if user is not None and getattr(user, "email", None):
            st.session_state.hosted_pending_confirmation = user.email
        return
    st.session_state.pop("hosted_pending_confirmation", None)
    st.session_state.hosted_auth = {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user_id": str(user.id),
        "email": user.email or "",
    }


def _restore_client(config: HostedConfig) -> tuple[Any | None, dict[str, str] | None]:
    auth = st.session_state.get("hosted_auth")
    if not isinstance(auth, dict) or not auth.get("access_token") or not auth.get("refresh_token"):
        if auth is not None:
            st.session_state.clear()
        return None, None
    try:
        client = create_user_client(config, auth["access_token"], auth["refresh_token"])
        session = client.auth.get_session()
        if session is None:
            st.session_state.clear()
            return None, None
        user_response = client.auth.get_user()
        user = getattr(user_response, "user", None)
        if user is None or str(user.id) != str(auth.get("user_id")) or not is_email_confirmed(user):
            st.session_state.clear()
            return None, None
        acceptance = get_privacy_acceptance(client)
        if acceptance is None:
            st.error("This account has no server-recorded Privacy Notice acknowledgment. Contact support before accessing hosted data.")
            st.session_state.clear()
            return None, None
        # Supabase may have rotated tokens while restoring a session. Notice
        # metadata comes from the immutable RLS-protected receipt, not Auth user_metadata.
        st.session_state.hosted_auth = {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "user_id": str(user.id),
            "email": user.email or "",
            "privacy_notice_version": acceptance["version"],
            "privacy_notice_url": acceptance["url"],
            "privacy_notice_acknowledged_at": acceptance["acknowledgedAt"],
        }
        return client, st.session_state.hosted_auth
    except Exception:
        # Do not expose SDK/network details or token material to the browser.
        st.error("Could not validate your session. Please sign in again.")
        st.session_state.clear()
        return None, None


@st.cache_data(ttl=3600, show_spinner=False)
def _public_companies() -> list[dict[str, str]]:
    path = Path(__file__).resolve().parents[2] / "vercel-site" / "data" / "companies.json"
    try:
        records = json.loads(path.read_text(encoding="utf-8")).get("companies", [])
    except (OSError, json.JSONDecodeError):
        return []
    return [
        {"name": str(item.get("name") or ""), "website": str(item.get("website") or ""),
         "type": str(item.get("type") or ""), "location": str(item.get("locationLabel") or "")}
        for item in records if item.get("name")
    ]


def _render_cvs(client: Any, user_id: str) -> None:
    st.subheader("CV library")
    st.caption("Upload separate CV versions. Files stay in a private bucket and are not published.")
    upload = st.file_uploader(
        "Upload a CV", type=["pdf", "docx", "txt", "md"], max_upload_size=10,
        help="PDF, DOCX, TXT or Markdown; maximum 10 MB.", key="hosted-cv-upload",
    )
    if upload and st.button("Save CV", type="primary", key="hosted-save-cv"):
        if upload.size > MAX_CV_BYTES:
            st.error("This file is larger than 10 MB.")
        else:
            mime_type = upload.type or ""
            if mime_type == "application/octet-stream":
                mime_type = next((kind for kind, suffix in ALLOWED_CV_TYPES.items() if upload.name.lower().endswith(suffix)), "")
            try:
                upload_cv(client, user_id, upload.name, mime_type, upload.getvalue())
                st.success("CV uploaded privately.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.error("The CV could not be saved. Check the storage setup and try again.")

    try:
        cvs = list_cvs(client)
    except Exception:
        st.error("Could not load your CV library.")
        return
    if not cvs:
        st.info("No CVs yet. Upload one to link it to an application.")
        return
    for cv in cvs:
        cv_version = str(cv["id"])[:8]
        uploaded_at = str(cv.get("created_at", ""))
        label = f"{cv['filename']} · version {cv_version} · {round(int(cv['byte_size']) / 1024)} KB · uploaded {uploaded_at}"
        with st.container(border=True):
            left, download_col, delete_col = st.columns([6, 1.5, 1])
            left.write(label)
            link_key = f"hosted-cv-download-{cv['id']}"
            if download_col.button(f"Create download link for {cv['filename']} ({cv_version})", key=f"create-download-{cv['id']}"):
                try:
                    st.session_state[link_key] = create_cv_download_url(client, cv["object_path"], 300)
                except Exception:
                    st.error(f"Could not create a download link for {cv['filename']}.")
            if st.session_state.get(link_key):
                st.link_button(f"Download {cv['filename']} ({cv_version}, temporary)", st.session_state[link_key])
                st.caption("This private download link expires in 5 minutes.")

            confirm_key = f"hosted-cv-confirm-delete-{cv['id']}"
            if not st.session_state.get(confirm_key):
                if delete_col.button(f"Delete {cv['filename']} ({cv_version})", key=f"delete-{cv['id']}"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                st.warning(f"Delete CV {cv['filename']} version {cv_version}? Applications linked to it will remain, without a CV attached.")
                confirm_col, cancel_col = st.columns(2)
                if confirm_col.button(f"Confirm delete {cv['filename']} ({cv_version})", key=f"confirm-delete-{cv['id']}"):
                    try:
                        delete_cv(client, cv)
                        st.session_state.pop(link_key, None)
                        st.session_state.pop(confirm_key, None)
                        st.success(f"Deleted CV {cv['filename']} version {cv_version}.")
                        st.rerun()
                    except Exception:
                        st.error(f"Could not delete {cv['filename']}. Its record was left unchanged.")
                if cancel_col.button(f"Cancel delete {cv['filename']} ({cv_version})", key=f"cancel-delete-{cv['id']}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()


def _render_companies(client: Any, user_id: str) -> None:
    st.subheader("Target companies")
    st.caption("Search the public company catalogue or enter another employer. Saved targets are private to you.")
    companies = _public_companies()
    query = st.text_input("Search company catalogue", placeholder="Company name")
    candidates = [item for item in companies if query.strip().casefold() in item["name"].casefold()][:30] if query.strip() else []
    selected: dict[str, str] | None = None
    if candidates:
        options = [f"{item['name']} · {item['location']}".strip(" ·") for item in candidates]
        chosen = st.selectbox("Matching public companies", options, key="hosted-company-choice")
        selected = candidates[options.index(chosen)]
    elif query.strip():
        st.caption("No catalogue match shown. You can still add this company manually.")

    with st.form("hosted-add-company"):
        name = st.text_input("Company", value=(selected or {}).get("name", query.strip()))
        website = st.text_input("Company website (optional; verify before opening)", value=(selected or {}).get("website", ""), placeholder="https://example.com")
        submitted = st.form_submit_button("Add to my targets", type="primary")
    if submitted:
        try:
            add_target(client, user_id, name, website)
            st.success("Company added to your private target list.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("Could not add this company. It may already be in your target list.")

    try:
        targets = list_targets(client)
    except Exception:
        st.error("Could not load your target companies.")
        return
    if not targets:
        st.info("Your target list is empty.")
    else:
        for target in targets:
            with st.container(border=True):
                left, right = st.columns([5, 1])
                left.markdown(f"**{escape(target['company_name'])}**")
                if target.get("company_website"):
                    left.link_button(f"Open supplied link · {target['company_name']}", target["company_website"])
                target_confirm_key = f"confirm-remove-target-{target['id']}"
                if not st.session_state.get(target_confirm_key):
                    if right.button(f"Remove target {target['company_name']}", key=f"remove-target-{target['id']}"):
                        st.session_state[target_confirm_key] = True
                        st.rerun()
                else:
                    st.warning(f"Remove {target['company_name']} from your target list? Existing applications will remain.")
                    confirm_col, cancel_col = st.columns(2)
                    if confirm_col.button(f"Confirm remove target {target['company_name']}", key=f"confirm-target-{target['id']}"):
                        try:
                            delete_target(client, target["id"])
                            st.session_state.pop(target_confirm_key, None)
                            st.success("Target removed. Existing applications are unchanged.")
                            st.rerun()
                        except Exception:
                            st.error(f"Could not remove target {target['company_name']}.")
                    if cancel_col.button(f"Cancel remove target {target['company_name']}", key=f"cancel-target-{target['id']}"):
                        st.session_state.pop(target_confirm_key, None)
                        st.rerun()


@st.cache_data(ttl=3600, show_spinner=False)
def _hosted_jobs() -> list[dict]:
    return load_public_jobs()


def _render_jobs(client: Any, user_id: str) -> None:
    st.subheader("European jobs & CV match")
    st.caption("Official-board snapshot · deterministic comparison, not a hiring probability")
    try:
        jobs = _hosted_jobs()
        cvs = list_cvs(client)
    except Exception:
        st.error("Could not load jobs or your CV library.")
        return
    if not jobs:
        st.info("No public vacancy snapshot is configured.")
        return
    query = st.text_input("Search hosted jobs", placeholder="Role, company, skill or place")
    areas = ["All role areas", *sorted({job["area"] for job in jobs})]
    area = st.selectbox("Role area", areas)
    matches = filter_jobs(jobs, query, "" if area == "All role areas" else area)
    st.write(f"{len(matches)} matching roles")
    if not matches:
        st.info("Try a broader search.")
        return
    options = [f"{job['title']} · {job['company']} · {', '.join(job['locations'])}" for job in matches[:50]]
    selected = matches[options.index(st.selectbox("Role to review", options))]
    st.link_button("Open official vacancy", selected["url"])
    st.write(selected["description"] or "Open the official advert for details.")
    if not cvs:
        st.info("Upload a CV before using private matching.")
        return
    cv_options = [f"{cv['filename']} ({cv['id'][:8]})" for cv in cvs]
    cv = cvs[cv_options.index(st.selectbox("CV for this role", cv_options, key="hosted-match-cv"))]
    if st.button("Compare selected CV", key="hosted-match-run"):
        try:
            content = client.storage.from_("private-cvs").download(cv["object_path"])
            result = match_cv_to_job(content, cv["mime_type"], selected)
            st.session_state.hosted_job_match = {"job_id": selected["id"], "cv_id": cv["id"], "skills": tuple(selected["skills"]), "matched": result.matched, "missing": result.missing, "coverage": result.coverage}
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("Could not compare this CV. The file and job snapshot were not changed.")
    result = st.session_state.get("hosted_job_match")
    result_current = result and result.get("job_id") == selected["id"] and result.get("cv_id") == cv["id"] and result.get("skills") == tuple(selected["skills"])
    if result_current:
        if result["coverage"] is None:
            st.info("No skill terms were extracted from this advert; no coverage score is shown.")
        else:
            st.metric("Advert terms evidenced in CV", f"{result['coverage']}%")
        st.write("Matched:", ", ".join(result["matched"]) or "None detected")
        st.write("Not detected:", ", ".join(result["missing"]) or "None")
        st.caption("Absence is not proof of missing experience. Review the original CV and advert.")
    if st.button("Prepare reviewed application", type="primary", key="hosted-prepare-job"):
        try:
            notes = ""
            if result_current:
                notes = "Deterministic CV overlap: " + (", ".join(result["matched"]) or "none detected")
            add_application(client, user_id, selected["company"], selected["title"], selected["url"], cv["id"], notes)
            st.success("Added to your review queue. Nothing was submitted.")
        except Exception:
            st.error("Could not add this role to the review queue.")


def _render_applications(client: Any, user_id: str) -> None:
    st.subheader("Application queue")
    st.caption("Save job links you provide, choose a CV version, and track progress. Links are not verified; submission remains your decision.")
    try:
        targets = list_targets(client)
        cvs = list_cvs(client)
    except Exception:
        st.error("Could not load your application choices.")
        return
    if not targets:
        st.info("Add at least one target company first.")
        return
    target_names = [item["company_name"] for item in targets]
    cv_names = ["No CV selected"] + [f"{item['filename']} ({item['id'][:8]})" for item in cvs]
    with st.form("hosted-add-application"):
        company = st.selectbox("Target company", target_names)
        title = st.text_input("Job title")
        url = st.text_input("Job URL (HTTPS; verify the employer source)", placeholder="https://jobs.example.com/role")
        cv_label = st.selectbox("CV version", cv_names)
        notes = st.text_area("Private notes", max_chars=4000)
        submitted = st.form_submit_button("Add to application queue", type="primary")
    if submitted:
        cv_id = None
        if cv_label != "No CV selected":
            index = cv_names.index(cv_label) - 1
            cv_id = cvs[index]["id"]
        try:
            add_application(client, user_id, company, title, url, cv_id, notes)
            st.success("Saved for review. This does not submit an application.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("Could not save this application. Check your connection and try again.")

    try:
        applications = list_applications(client)
    except Exception:
        st.error("Could not load your application queue.")
        return
    if not applications:
        st.info("No saved applications yet.")
        return
    stage_labels = {"saved": "Saved", "preparing": "Preparing", "ready": "Ready for your review", "applied": "Applied (you confirmed)"}
    cv_by_id = {item["id"]: item["filename"] for item in cvs}
    for application in applications:
        with st.container(border=True):
            st.markdown(f"**{escape(application['job_title'])} · {escape(application['company_name'])}**")
            st.link_button(f"Open supplied job link · {application['company_name']}", application["job_url"])
            st.caption(f"Stage: {stage_labels.get(application['stage'], application['stage'])} · CV: {cv_by_id.get(application.get('cv_profile_id'), 'None')}")
            if application.get("notes"):
                st.text(application["notes"])
            stages = ["saved", "preparing", "ready", "applied"]
            current = application.get("stage", "saved")
            record_label = f"{application['job_title']} at {application['company_name']}"
            new_stage = st.selectbox(
                f"Progress for {record_label}", stages, index=stages.index(current) if current in stages else 0,
                format_func=lambda value: stage_labels[value], key=f"stage-{application['id']}",
            )
            action_col, remove_col = st.columns([3, 1])
            if new_stage != current and action_col.button(f"Save progress for {record_label}", key=f"save-stage-{application['id']}"):
                try:
                    set_application_stage(client, application["id"], new_stage)
                    st.success("Progress updated.")
                    st.rerun()
                except Exception:
                    st.error(f"Could not update progress for {record_label}.")

            confirm_key = f"confirm-remove-application-{application['id']}"
            if not st.session_state.get(confirm_key):
                if remove_col.button(f"Remove application for {record_label}", key=f"remove-application-{application['id']}"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                st.warning(f"Remove {record_label} and its private notes/progress? This cannot be undone.")
                confirm_col, cancel_col = st.columns(2)
                if confirm_col.button(f"Confirm remove application for {record_label}", key=f"confirm-application-{application['id']}"):
                    try:
                        delete_application(client, application["id"])
                        st.session_state.pop(confirm_key, None)
                        st.success(f"Removed application for {record_label}.")
                        st.rerun()
                    except Exception:
                        st.error(f"Could not remove application for {record_label}.")
                if cancel_col.button(f"Cancel remove application for {record_label}", key=f"cancel-application-{application['id']}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()


def main() -> None:
    try:
        config = HostedConfig.from_env()
    except RuntimeError:
        st.title("Co-Apply GPT · Hosted preview")
        st.error("Hosted sign-in is not configured yet. The owner must connect Supabase before launch.")
        st.stop()

    callback_code = st.query_params.get("code")
    token_hash = st.query_params.get("token_hash")
    try:
        if token_hash:
            response = exchange_email_token(create_user_client(config), str(token_hash))
            st.session_state.clear()
            _capture_session(response)
            st.query_params.clear()
            st.rerun()
        if callback_code and st.query_params.get("oauth_id"):
            verifier = consume_oauth_verifier(create_user_client(config), str(st.query_params["oauth_id"]))
            storage = SyncMemoryStorage()
            storage.set_item(PKCE_STORAGE_KEY, verifier)
            oauth_client = create_user_client(config, auth_storage=storage)
            response = exchange_auth_code(oauth_client, str(callback_code))
            st.session_state.clear()
            _capture_session(response)
            st.query_params.clear()
            st.rerun()
        if callback_code:
            st.query_params.clear()
            st.error("The sign-in link is invalid or expired. Request a new email link.")
    except Exception:
        st.query_params.clear()
        st.error("The sign-in link is invalid or expired. Request a new email link.")

    client, auth = _restore_client(config)
    if client is None or auth is None:
        render_auth_screen(config, _capture_session)
        return

    st.title("Co-Apply GPT")
    st.caption("Hosted preview · private account workspace")
    with st.sidebar:
        st.write(auth.get("email", "Signed in"))
        if st.button("Sign out", use_container_width=True):
            try:
                client.auth.sign_out()
            finally:
                st.session_state.clear()
                st.rerun()
        st.caption("Your account sees only its own CVs, targets, and applications.")

    jobs_tab, cv_tab, company_tab, application_tab, account_tab = st.tabs(["Jobs & CV match", "CV library", "Companies", "Applications", "Account & privacy"])
    with jobs_tab:
        _render_jobs(client, auth["user_id"])
    with cv_tab:
        _render_cvs(client, auth["user_id"])
    with company_tab:
        _render_companies(client, auth["user_id"])
    with application_tab:
        _render_applications(client, auth["user_id"])
    with account_tab:
        render_account(client, config, auth, _capture_session)


if __name__ == "__main__":
    main()
