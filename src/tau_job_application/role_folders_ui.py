"""Streamlit page for role folders: create, attach CV/letter, run, download PDFs."""
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from tau_job_application.role_folders import (
    COMPANY_TYPES,
    REGIONS,
    RoleFolder,
    RoleFolderStore,
    load_companies,
    load_jobs,
    run_folder,
)
from tau_job_application.project_pdf import render_project_pdf


def _mime(name: str) -> str:
    return {".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain", ".md": "text/markdown"}.get(Path(name).suffix.casefold(), "text/plain")


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.casefold()).strip("-")[:60] or "project"


_MIME = {".ico": "image/x-icon", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}


def _logo_html(logo: str | None, size: int = 34) -> str | None:
    """Render a local logo as an inline image; browsers support .ico, which st.image does not."""
    if not logo:
        return None
    from tau_job_application.role_folders import _project_root
    path = (_project_root() / "vercel-site" / str(logo).lstrip("/")).resolve()
    if not path.is_file() or _project_root() not in path.parents:
        return None
    mime = _MIME.get(path.suffix.casefold(), "image/png")
    data = base64.b64encode(path.read_bytes()).decode()
    return (f'<img src="data:{mime};base64,{data}" alt="" '
            f'style="height:{size}px;width:{size}px;object-fit:contain;background:#fff;'
            f'border-radius:6px;border:1px solid #E6DFD1;padding:2px;">')


def render_role_folders() -> None:
    store = RoleFolderStore()
    st.title("Role folders")
    st.caption("One folder per target search. Run a folder to score its roles against the attached CV and "
               "download a project-description PDF for each match. Coverage is limited to the current public vacancy snapshot.")

    with st.expander("New folder", expanded=not store.list()):
        with st.form("new_role_folder"):
            name = st.text_input("Name", placeholder="ML engineer - Europe - Startup")
            roles = st.text_input("Role keywords (comma-separated)", placeholder="ml engineer, machine learning")
            col1, col2 = st.columns(2)
            region = col1.selectbox("Region", REGIONS)
            company_type = col2.selectbox("Company type", COMPANY_TYPES)
            sector = st.text_input("Sector (optional)", placeholder="tech")
            sub_sector = st.text_input("Sub-sector (optional)", placeholder="mechanical engineering")
            if st.form_submit_button("Create folder"):
                if name.strip():
                    store.create(RoleFolder(name=name.strip(), role_keywords=[k.strip() for k in roles.split(",") if k.strip()],
                                            sector=sector.strip(), sub_sector=sub_sector.strip(),
                                            region=region, company_type=company_type))
                    st.rerun()

    folders = store.list()
    if not folders:
        st.info("Create a folder to start.")
        return

    for folder in folders:
        folder_id = folder["id"]
        with st.expander(f"{folder['name']} — {folder['region']} · {folder['company_type']}", expanded=True):
            col_cv, col_letter = st.columns(2)
            cv_file = col_cv.file_uploader("CV (PDF / DOCX / TXT)", key=f"cv_{folder_id}")
            letter_file = col_letter.file_uploader("Letter of intention (TXT / MD)", key=f"letter_{folder_id}")
            documents = store.documents(folder_id)
            if col_cv.button("Save CV & letter", key=f"save_{folder_id}"):
                cv_bytes = cv_file.getvalue() if cv_file else documents.get("cv_bytes")
                cv_name = cv_file.name if cv_file else documents.get("cv_name")
                cv_mime = _mime(cv_name) if cv_name else documents.get("cv_mime")
                letter_text = letter_file.getvalue().decode("utf-8", "replace") if letter_file else documents.get("letter_text")
                store.set_documents(folder_id, cv_bytes, cv_name, cv_mime, letter_text)
                st.success("Documents saved.")
            if documents.get("cv_name"):
                col_cv.caption(f"Attached: {documents['cv_name']}")
            if col_letter.button("Run folder", key=f"run_{folder_id}"):
                folder_obj = RoleFolder(name=folder["name"], role_keywords=folder["role_keywords"], sector=folder["sector"],
                                        sub_sector=folder["sub_sector"], region=folder["region"],
                                        company_type=folder["company_type"], id=folder_id)
                run_folder(store, folder_obj, load_jobs(), load_companies())
                st.rerun()

            matches = store.list_matches(folder_id)
            if matches:
                st.caption(f"{len(matches)} matching roles, highest score first.")
                for match in matches:
                    logo_html = _logo_html(match.get("logo"))
                    col_logo, col_text = st.columns([0.7, 11.3])
                    if logo_html:
                        col_logo.markdown(logo_html, unsafe_allow_html=True)
                    score = f"{match['score']}%" if match["score"] is not None else "no CV"
                    col_text.markdown(f"**{score}** · {match['title']} @ {match['company']} · {match['area']}")
                    col_text.caption(match["url"])
                    st.download_button(
                        "Download project PDF",
                        render_project_pdf(match, folder["name"], documents.get("letter_text")),
                        file_name=f"{_slug(match['company'])}-{_slug(match['title'])}.pdf",
                        mime="application/pdf", key=f"pdf_{folder_id}_{match['job_id']}",
                    )
            else:
                st.caption("No matches yet. Attach a CV and run the folder.")
