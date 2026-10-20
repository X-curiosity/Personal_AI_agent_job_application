"""Minimalist local Streamlit UI for the evidence-first job-readiness workflow."""

from __future__ import annotations

import os
import sys
import hashlib
from datetime import UTC, datetime
from html import escape
from pathlib import Path
import tempfile
from typing import Callable
from urllib.parse import quote_plus

import pydeck as pdk
import streamlit as st

from tau_job_application.application_tracker import ApplicationTrackerStore
from tau_job_application.application_tracker_ui import render_application_tracker
from tau_job_application.career_hub import HubStore
from tau_job_application.career_hub_ui import render_portal, render_onboarding
from tau_job_application.career_hub_ui import go as _hub_go
from tau_job_application.accounts import ConnectedAccountStore
from tau_job_application.accounts_ui import render_accounts
from tau_job_application.agents_ui import render_agents_console
from tau_job_application.company_branding import CompanyBrandStore, validate_public_https_logo_url
from tau_job_application.company_catalog import CompanyCatalogStore
from tau_job_application.eligibility import ResidencyStore
from tau_job_application.eligibility_ui import render_eligibility
from tau_job_application.company_explorer import COMPANY_PINS, company_footprint, detected_profile_skills, recommend_companies
from tau_job_application.evidence_match_store import EvidenceMatchStore
from tau_job_application.hiring_index import HiringIndexStore
from tau_job_application.hiring_match import (
    ProjectProof,
    ProjectProofKind,
    ProjectStatus,
    calculate_evidence_match,
)
from tau_job_application.interview import (
    LEVEL_NAMES,
    MAX_LEVEL,
    build_interview_questions,
    difficulty_level,
    evaluate_answer,
    level_progress,
    transcribe_openai_audio,
)
from tau_job_application.job_pages import fetch_job_url
from tau_job_application.landing_page import (
    LandingOpportunity,
    build_landing_page_data,
    render_landing_page,
)
from tau_job_application.official_sources import (
    fetch_smartrecruiters_postings,
    import_job_export,
)
from tau_job_application.monitoring import JobMonitor
from tau_job_application.matching import normalize_skill
from tau_job_application.parsing import KNOWN_SKILLS, infer_profile_links, load_document
from tau_job_application.planning import build_project_plans
from tau_job_application.requirement_memory import RequirementMemory, document_key
from tau_job_application.requirements import extract_requirements, save_requirement_review
from tau_job_application.role_discovery import (
    DEFAULT_VETTED_COMPANY_BOARDS,
    DiscoveredOpening,
    RoleDiscoveryStore,
    RoleQuery,
    SourceSnapshot,
    canonicalize_url,
    opening_matches_filters,
    opening_matches_period,
    opening_sources,
    openings_from_board,
    PERIOD_CHOICES,
    rank_openings,
    suggest_role_aliases,
)
from tau_job_application.role_market_state import (
    RoleMarketState,
    RoleMarketStateStore,
    RoleMarketStatus,
    opening_key,
)
from tau_job_application.pipeline import analyze_texts, render_markdown
from tau_job_application.sources import (
    enrich_github_profile,
    fetch_greenhouse_jobs,
    fetch_lever_jobs,
    fetch_public_board_openings,
    fetch_recruitee_jobs,
)
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import PROFILE_FIELDS, WorkspaceStore
from tau_job_application.workspace_ui import choose_scope, draft_key, show_chat, show_direction
from tau_job_application.capital_atlas import AtlasStore
from tau_job_application.yc_directory import YCDirectoryStore


def _project_root() -> Path:
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    return Path.home() / ".job-readiness-agent"


ROOT = _project_root()
STORE = LocalStore(ROOT / ".job_assistant" / "assistant.sqlite")
MONITOR = JobMonitor(ROOT / ".job_assistant" / "assistant.sqlite")
REQUIREMENT_MEMORY = RequirementMemory(ROOT / ".job_assistant" / "assistant.sqlite")
WORKSPACES = WorkspaceStore(ROOT / ".job_assistant" / "assistant.sqlite")
ROLE_DISCOVERY = RoleDiscoveryStore(ROOT / ".job_assistant" / "assistant.sqlite")
EVIDENCE_MATCHES = EvidenceMatchStore(ROOT / ".job_assistant" / "assistant.sqlite")
ROLE_MARKET_STATES = RoleMarketStateStore(ROOT / ".job_assistant" / "assistant.sqlite")
COMPANY_BRANDS = CompanyBrandStore(ROOT / ".job_assistant" / "assistant.sqlite")
APPLICATIONS = ApplicationTrackerStore(ROOT / ".job_assistant" / "assistant.sqlite")
COMPANY_CATALOG = CompanyCatalogStore(ROOT / ".job_assistant" / "assistant.sqlite")
YC_DIRECTORY = YCDirectoryStore(ROOT / ".job_assistant" / "assistant.sqlite")
ATLAS = AtlasStore(ROOT / ".job_assistant" / "assistant.sqlite")
RESIDENCY = ResidencyStore(ROOT / ".job_assistant" / "assistant.sqlite")
HIRING_INDEX = HiringIndexStore(ROOT / ".job_assistant" / "assistant.sqlite")
ACCOUNTS = ConnectedAccountStore(ROOT / ".job_assistant" / "assistant.sqlite")


def _application_store() -> ApplicationTrackerStore:
    return APPLICATIONS if APPLICATIONS.path == WORKSPACES.path else ApplicationTrackerStore(WORKSPACES.path)


def _evidence_store() -> EvidenceMatchStore:
    """Use the current workspace database in UI tests as well as in the app."""

    return EVIDENCE_MATCHES if EVIDENCE_MATCHES.path == WORKSPACES.path else EvidenceMatchStore(WORKSPACES.path)


def _role_market_state_store() -> RoleMarketStateStore:
    """Use the active workspace database in tests as well as the local app."""

    return (
        ROLE_MARKET_STATES
        if ROLE_MARKET_STATES.path == WORKSPACES.path
        else RoleMarketStateStore(WORKSPACES.path)
    )


def _company_brand_store() -> CompanyBrandStore:
    """Use the active workspace database in UI tests as well as in the app."""

    return (
        COMPANY_BRANDS
        if COMPANY_BRANDS.path == WORKSPACES.path
        else CompanyBrandStore(WORKSPACES.path)
    )


def _company_catalog_store() -> CompanyCatalogStore:
    """Use the active workspace database in UI tests as well as in the app."""
    return (
        COMPANY_CATALOG
        if COMPANY_CATALOG.path == WORKSPACES.path
        else CompanyCatalogStore(WORKSPACES.path)
    )


def _yc_directory_store() -> YCDirectoryStore:
    """Use the active workspace database in UI tests as well as in the app."""
    return (
        YC_DIRECTORY
        if YC_DIRECTORY.path == WORKSPACES.path
        else YCDirectoryStore(WORKSPACES.path)
    )


def _residency_store() -> ResidencyStore:
    """Use the active workspace database in UI tests as well as in the app."""
    return (
        RESIDENCY
        if RESIDENCY.path == WORKSPACES.path
        else ResidencyStore(WORKSPACES.path)
    )


def _atlas_store() -> AtlasStore:
    """Use the active workspace database in UI tests as well as in the app."""
    return (
        ATLAS
        if ATLAS.path == WORKSPACES.path
        else AtlasStore(WORKSPACES.path)
    )


def _hiring_index_store() -> HiringIndexStore:
    """Use the active workspace database in UI tests as well as in the app."""
    return (
        HIRING_INDEX
        if HIRING_INDEX.path == WORKSPACES.path
        else HiringIndexStore(WORKSPACES.path)
    )


def _account_store() -> ConnectedAccountStore:
    """Use the active workspace database in UI tests as well as in the app."""
    return (
        ACCOUNTS
        if ACCOUNTS.path == WORKSPACES.path
        else ConnectedAccountStore(WORKSPACES.path)
    )


def _evidence_match_for(result, workspace_id: str, thread_id: str):
    return calculate_evidence_match(
        result.candidate,
        result.job,
        _evidence_store().list_projects(workspace_id, thread_id),
    )


def _standout_plans(result, assessment):
    """Recommend a build only for gaps not already backed by eligible project proof."""

    covered_skills = [
        support.skill
        for support in assessment.requirement_supports
        if support.support > 0
    ]
    return build_project_plans(result.skill_tree, covered_skills=covered_skills)


STYLES = """
<style>
:root {
    --ink: #1F1B16;
    --forest: #1F1B16;
    --sage: #736A5E;
    --paper: #F5F1E9;
    --mist: #F1ECE3;
    --line: #E6DFD1;
    --clay: #1F1B16;
}
.stApp, [data-testid="stAppViewContainer"] {background: #F5F1E9; color: var(--ink); color-scheme: light;}
/* Hide the default Streamlit chrome: the white header bar and its colored top line.
   The sidebar collapse control stays usable; the bar itself is transparent. */
[data-testid="stDecoration"] {display: none;}
[data-testid="stHeader"] {background: transparent; box-shadow: none; backdrop-filter: none;}
[data-testid="stHeader"] [data-testid="stToolbar"] {background: transparent;}
.block-container {padding-top: 1.35rem; padding-bottom: 3rem; max-width: 1440px;}
div[data-testid="stSidebar"] {background: #1F1B16;}
div[data-testid="stSidebar"] * {color: #FFFAF3;}
div[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {color: #E6DFD1;}
div[data-testid="stSidebar"] [data-testid="stProgress"] > div > div > div > div {background-color: #C9BC9C;}
div[data-testid="stTextInput"] label, div[data-testid="stTextArea"] label, div[data-testid="stFileUploader"] label, div[data-testid="stCheckbox"] label, div[data-testid="stSelectbox"] label {color: #1F1B16 !important; font-weight: 620;}
div[data-baseweb="input"] > div, div[data-baseweb="textarea"] {background-color: #FFFEFB !important; border-color: #E6DFD1 !important; color: #1F1B16 !important;}
div[data-baseweb="input"] input, div[data-baseweb="textarea"] textarea {background-color: transparent !important; color: #1F1B16 !important; caret-color: #1F1B16 !important;}
div[data-testid="stTextInput"] input, div[data-testid="stTextArea"] textarea {background-color: #FFFEFB !important; color: #1F1B16 !important; caret-color: #1F1B16 !important; border: 1px solid #E6DFD1 !important;}
div[data-testid="stTextInput"] input::placeholder, div[data-testid="stTextArea"] textarea::placeholder {color: #736A5E !important; opacity: 1 !important;}
div[data-testid="stFileUploader"] section {background: #FFFEFB !important; border-color: #E6DFD1 !important; color: #1F1B16 !important;}
div[data-testid="stFileUploader"] small, div[data-testid="stFileUploader"] span {color: #655D52 !important;}
button[data-testid="stBaseButton-primary"] {background: #1F1B16 !important; border-color: #1F1B16 !important; color: #FFFAF3 !important;}
button[data-testid="stBaseButton-primary"]:hover {background: #1F1B16 !important; border-color: #1F1B16 !important;}
button[data-testid="stBaseButton-secondary"] {background: #FFFEFB !important; border-color: #E6DFD1 !important; color: #1F1B16 !important;}
button[data-testid="stBaseButton-secondary"] *, button[data-testid="stBaseButton-secondary"] {color: #1F1B16 !important;}
button[data-testid="stBaseButton-secondary"]:hover {background: #F3EEE6 !important; border-color: #736A5E !important;}
a[data-testid="stBaseLinkButton-primary"] {background: #1F1B16 !important; border-color: #1F1B16 !important; color: #FFFAF3 !important;}
a[data-testid="stBaseLinkButton-primary"] * {color: #FFFAF3 !important;}
a[data-testid="stBaseLinkButton-primary"]:hover {background: #1F1B16 !important; border-color: #1F1B16 !important;}
a[data-testid="stBaseLinkButton-secondary"] {background: #FFFEFB !important; border-color: #E6DFD1 !important; color: #1F1B16 !important;}
a[data-testid="stBaseLinkButton-secondary"] * {color: #1F1B16 !important;}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] *, [data-testid="stMetricValue"], [data-testid="stMetricValue"] * {color: #1F1B16 !important;}
.workspace-hero {background: radial-gradient(circle at 86% 18%, rgba(31, 27, 22, .36), transparent 24%), linear-gradient(120deg, #1F1B16 0%, #2E2820 66%, #4A4238 100%); border-radius: 18px; color: #FFFAF3; padding: 2rem 2.15rem 1.7rem; box-shadow: 0 16px 35px rgba(31, 27, 22, .14); margin-bottom: 1.3rem;}
.workspace-hero .eyebrow {font-size: .74rem; text-transform: uppercase; letter-spacing: .13em; font-weight: 700; color: #E6DFD1; margin-bottom: .55rem;}
.workspace-hero h1 {color: #FFFAF3; font-size: clamp(1.65rem, 3.1vw, 2.8rem); line-height: 1.1; margin: 0 0 .45rem;}
.workspace-hero p {color: #E6DFD1; max-width: 760px; margin: 0; font-size: 1rem;}
.workspace-hero .job-chip {display: inline-block; margin-top: 1rem; border: 1px solid rgba(255,255,255,.4); border-radius: 999px; padding: .35rem .72rem; color: #FFFAF3; font-size: .82rem;}
.metric-card {background: rgba(255, 255, 252, .86); border-radius: 14px; padding: 17px 14px; min-height: 110px; border: 1px solid var(--line); box-shadow: 0 5px 15px rgba(31, 27, 22, .045);}
.metric-label {font-size: .75rem; letter-spacing: .055em; text-transform: uppercase; color: #736A5E; margin-bottom: 6px; font-weight: 700;}
.metric-value {font-size: 1.8rem; font-weight: 760; color: var(--ink); line-height: 1.05;}
.metric-note {font-size: .78rem; color: #736A5E; margin-top: .35rem;}
.section-kicker {font-size: .76rem; letter-spacing: .11em; text-transform: uppercase; color: #655D52; font-weight: 750; margin-bottom: .25rem;}
.quiet-panel {background: rgba(255,255,252,.72); border: 1px solid var(--line); border-radius: 14px; padding: 1.1rem 1.2rem; margin: .45rem 0 1rem;}
.next-action {background: #F6F2EA; border-left: 4px solid #1F1B16; border-radius: 5px 12px 12px 5px; padding: 1rem 1.1rem;}
.path-card {background: rgba(255,255,252,.8); border: 1px solid var(--line); border-radius: 12px; padding: .9rem 1rem; min-height: 105px;}
.path-step {font-size: .72rem; text-transform: uppercase; letter-spacing: .09em; color: #736A5E; font-weight: 800;}
.path-card h4 {margin: .3rem 0; color: var(--ink);}
.path-card p {font-size: .86rem; color: #736A5E; margin: 0;}
div[data-testid="stTabs"] [role="tab"], div[data-testid="stTabs"] [role="tab"] * {font-weight: 650 !important; color: #655D52 !important; opacity: 1 !important;}
div[data-testid="stTabs"] [role="tab"][aria-selected="true"], div[data-testid="stTabs"] [role="tab"][aria-selected="true"] * {color: #1F1B16 !important;}
div[data-testid="stExpander"] {background: rgba(255,255,252,.66); border: 1px solid var(--line); border-radius: 10px;}
.role-feed-avatar {position:relative; overflow:hidden; width: 46px; height: 46px; display: grid; place-items: center; border-radius: 12px; background: linear-gradient(145deg, #F3EEE6, #E6DFD1); border: 1px solid #E6DFD1; color: #1F1B16; font-size: .84rem; font-weight: 800; letter-spacing: .045em; margin-top: .25rem;}
.role-feed-avatar .role-feed-monogram {display:grid; place-items:center; width:100%; height:100%;}
.role-feed-avatar img {position:absolute; inset:0; width:100%; height:100%; object-fit:contain; padding:5px;}
.role-feed-title {font-size: 1.02rem; line-height: 1.25; font-weight: 760; color: #1F1B16; margin: .05rem 0 .22rem;}
.role-feed-company {font-size: .88rem; color: #655D52; margin: 0 0 .3rem;}
.role-feed-meta {display: flex; gap: .35rem; flex-wrap: wrap; margin: .1rem 0 .35rem;}
.role-feed-pill {display: inline-block; border-radius: 999px; padding: .19rem .5rem; background: #F1ECE3; border: 1px solid #E6DFD1; color: #655D52; font-size: .72rem; line-height: 1.2;}
.role-feed-pill.source {background: #F6F2EA; border-color: #E6DFD1; color: #655D52;}
.role-feed-pill.state {background: #F1ECE3; border-color: #E6DFD1; color: #1F1B16; font-weight: 700;}
.role-feed-relevance {background: #1F1B16; color: #FFFAF3; border-radius: 12px; padding: .68rem .52rem; text-align: center; margin-top: .12rem;}
.role-feed-relevance b {display: block; color: #FFFAF3; font-size: 1.16rem; line-height: 1.05;}
.role-feed-relevance span {display: block; color: #E6DFD1; font-size: .66rem; letter-spacing: .04em; text-transform: uppercase; margin-top: .23rem;}
.role-feed-reason {font-size: .8rem; color: #655D52; margin: .15rem 0 0;}
.role-market-note {background: #F6F2EA; border-left: 3px solid #B49B57; border-radius: 5px 10px 10px 5px; color: #655D52; padding: .68rem .85rem; font-size: .84rem; margin: .6rem 0 .9rem;}
/* Sticky top app bar, the usual browser-app navigation format. */
div[data-testid="stHorizontalBlock"]:has(.topnav-brand-mark) {
    position: sticky; top: 0; z-index: 999;
    background: linear-gradient(120deg, #1F1B16 0%, #2E2820 90%);
    margin: -1.3rem -1rem 1.15rem; padding: .45rem 1.2rem;
    border-radius: 0 0 16px 16px; box-shadow: 0 8px 22px rgba(31,27,22,.16);
    align-items: center; row-gap: 0;
}
.topnav-brand-mark {display: none;}
/* Brand button: looks like a wordmark, acts like a link home. */
div[data-testid="stColumn"]:has(.topnav-brand-mark) button {
    background: transparent !important; border: none !important; box-shadow: none !important;
    color: #FFFAF3 !important; font-size: 1.16rem; font-weight: 800; letter-spacing: .02em;
    padding: .1rem 0 !important; white-space: nowrap; text-align: left; min-height: 0;
}
div[data-testid="stColumn"]:has(.topnav-brand-mark) button * {color: #FFFAF3 !important; white-space: nowrap;}
div[data-testid="stColumn"]:has(.topnav-brand-mark) button:hover,
div[data-testid="stColumn"]:has(.topnav-brand-mark) button:hover * {color: #C9BC9C !important;}
/* Nav pills: never wrap or clip; scroll sideways instead. */
div[data-testid="stHorizontalBlock"]:has(.topnav-brand-mark) [data-testid="stSegmentedControl"] {justify-content: flex-end; overflow-x: auto;}
div[data-testid="stHorizontalBlock"]:has(.topnav-brand-mark) [data-testid="stSegmentedControl"] > div,
div[data-testid="stHorizontalBlock"]:has(.topnav-brand-mark) [data-testid="stSegmentedControl"] [role="radiogroup"] {
    background: transparent; border: none; gap: .2rem; flex-wrap: nowrap; overflow-x: auto;
}
div[data-testid="stHorizontalBlock"]:has(.topnav-brand-mark) [data-testid="stSegmentedControl"] label {
    background: transparent !important; border: none !important; box-shadow: none !important;
    border-radius: 999px !important; font-weight: 650 !important; white-space: nowrap;
}
div[data-testid="stHorizontalBlock"]:has(.topnav-brand-mark) [data-testid="stSegmentedControl"] label * {color: #E6DFD1 !important;}
div[data-testid="stHorizontalBlock"]:has(.topnav-brand-mark) [data-testid="stSegmentedControl"] label:hover * {color: #FFFAF3 !important;}
div[data-testid="stHorizontalBlock"]:has(.topnav-brand-mark) [data-testid="stSegmentedControl"] label:has(input:checked) {background: #C9BC9C !important;}
div[data-testid="stHorizontalBlock"]:has(.topnav-brand-mark) [data-testid="stSegmentedControl"] label:has(input:checked) * {color: #1F1B16 !important;}
/* Streamlit Cloud chrome has no place in this local app. */
[data-testid="stToolbar"] {display: none;}
</style>
"""


_NAV_ITEMS = {
    "Home": "landing",
    "Workspace": "",
    "Role pages": "career",
    "Applications": "applications",
    "Companies": "companies",
    "Eligibility": "eligibility",
    "Agent team": "agents",
    "Accounts": "account",
}


def _top_nav() -> None:
    """The sticky top app bar used across every view (usual browser-app format)."""

    current = _route_value("view")
    labels = list(_NAV_ITEMS)
    view_aliases = {
        "career": "Role pages", "onboarding": "Role pages", "role": "Role pages",
        "application": "Applications", "applications": "Applications",
        "companies": "Companies", "eligibility": "Eligibility", "agents": "Agent team",
        "account": "Accounts",
    }
    current_label = view_aliases.get(current, "Workspace")
    bar = st.columns((2.1, 5.9))
    bar[0].markdown('<span class="topnav-brand-mark"></span>', unsafe_allow_html=True)
    if bar[0].button("◒ Co-Apply GPT", key="topnav-brand", help="Back to the product home"):
        _navigate(view="landing")
    bar[1].segmented_control(
        "Navigate", labels, default=current_label,
        label_visibility="collapsed", key="topnav", on_change=_on_nav_change,
    )


def _on_nav_change() -> None:
    """Navigate only on a genuine user pick; programmatic routing just re-syncs the pill."""

    choice = st.session_state.get("topnav")
    if choice in _NAV_ITEMS:
        _navigate(view=_NAV_ITEMS[choice] or None)


def main() -> None:
    st.set_page_config(page_title="Co-Apply GPT", page_icon="◒", layout="wide")
    st.markdown(STYLES, unsafe_allow_html=True)
    if _route_value("view") == "landing":
        _product_landing()
        return

    workspace_id, thread_id = choose_scope(WORKSPACES, compact=_route_value("view") in {"career", "onboarding", "role", "application", "companies", "match", "eligibility", "agents", "account"})
    _top_nav()
    with st.sidebar:
        st.caption("Your career track and job workspace live here. Everything else is in the top bar.")
    if _route_value("view") in {"career", "onboarding", "role", "application", "companies", "match"}:
        render_portal(sys.modules[__name__], workspace_id, _route_value("view"))
        return
    if _route_value("view") == "eligibility":
        render_eligibility(sys.modules[__name__], workspace_id)
        return
    if _route_value("view") == "agents":
        render_agents_console(sys.modules[__name__], workspace_id)
        return
    if _route_value("view") == "account":
        render_accounts(sys.modules[__name__], workspace_id)
        return
    if _route_value("view") == "applications":
        _my_applications(workspace_id)
        return
    if HubStore(WORKSPACES.path).interests(workspace_id) is None:
        with st.expander("Start here: choose your interests", expanded=True):
            render_onboarding(sys.modules[__name__], workspace_id, standalone=False)
    _workspace_hero(WORKSPACES.thread(workspace_id, thread_id))
    tab_labels = [
        "Overview", "Job brief", "CV studio", "Proof projects",
        "Career track", "Role market", "Coach",
    ]
    focus = _route_value("focus")
    # Redirects for tabs that moved: Evidence match merged into Proof projects
    # and Interview lab moved into each application workspace.
    legacy_focus = {"Evidence match": "Proof projects"}
    if focus in legacy_focus:
        focus = legacy_focus[focus]
    elif focus == "Interview lab":
        st.info("Interview practice now lives in each application workspace, beside the job status. Open My applications.")
        focus = None
    if focus in tab_labels:
        tab_labels = [focus, *(label for label in tab_labels if label != focus)]
    tabs = dict(zip(tab_labels, st.tabs(tab_labels), strict=True))
    with tabs["Overview"]:
        _job_workspace_dashboard(workspace_id, thread_id)
    with tabs["Job brief"]:
        _quickstart(workspace_id, thread_id)
    with tabs["CV studio"]:
        _cv_studio(workspace_id, thread_id)
    with tabs["Proof projects"]:
        _project_studio(workspace_id, thread_id)
        _project_evidence(workspace_id, thread_id)
    with tabs["Career track"]:
        show_direction(WORKSPACES, workspace_id)
    with tabs["Role market"]:
        _opportunities(workspace_id, thread_id)
    with tabs["Coach"]:
        show_chat(WORKSPACES, workspace_id, thread_id)


def _route_value(name: str) -> str:
    """Read one optional query value without letting repeated values affect routing."""

    value = st.query_params.get(name, "")
    if isinstance(value, list):
        value = value[-1] if value else ""
    return value.strip() if isinstance(value, str) else ""


def _navigate(*, view: str | None = None, focus: str | None = None) -> None:
    """Move between the product home and workspace without retaining stale routing."""

    st.query_params.clear()
    if view:
        st.query_params["view"] = view
    if focus:
        st.query_params["focus"] = focus
    st.session_state.pop("topnav", None)
    st.rerun()


def _product_landing() -> None:
    """Render the separate, local-data-driven product landing route."""

    render_landing_page(
        _landing_page_data(),
        on_enter_workspace=lambda: _navigate(view="career"),
        on_open_role_market=lambda: _navigate(focus="Role market"),
    )
    if st.button("My applications", key="landing-application-tracker"):
        _navigate(view="applications")
    st.checkbox(
        "Load remote company logos", key="remote-logos-opt-in",
        help="Off by default: loading a remote image shares your IP address with its host.",
    )
    with st.expander("What this page does and does not do", expanded=False):
        st.write(
            "This product home reads only your local workspace and latest saved public-board snapshots. "
            "It does not refresh a job board, upload your CV, submit an application, or contact anyone."
        )
        st.write(
            "Openings remain observations from their official sources. Use Co-Apply GPT to inspect "
            "provenance, prepare a role, and choose the next action yourself."
        )


def _landing_page_data():
    """Derive a concise, factual landing snapshot from local Role Market state."""

    role_pages = 0
    newest: tuple[str, str, str, object] | None = None
    for career_track in WORKSPACES.list_workspaces():
        career_track_id = career_track["id"]
        for thread in WORKSPACES.list_threads(career_track_id):
            role_pages += 1
            run = ROLE_DISCOVERY.latest_run(
                career_track_id=career_track_id,
                workspace_id=thread["id"],
            )
            if run is None:
                continue
            candidate = (run.created_at, career_track_id, thread["id"], run)
            if newest is None or candidate[0] > newest[0]:
                newest = candidate

    if newest is None:
        return build_landing_page_data(
            role_pages=role_pages,
            official_openings=0,
            shortlisted_openings=0,
            companies=0,
        )

    _, career_track_id, thread_id, run = newest
    state_by_opening_key = {
        state.opening_key: state
        for state in _role_market_state_store().list_states(career_track_id, thread_id)
    }
    visible_matches = [
        match
        for match in run.matches
        if (
            (state := _role_market_state_for(match.opening, state_by_opening_key)) is None
            or state.status is not RoleMarketStatus.HIDDEN
        )
    ]
    shortlisted = sum(
        state.status in {RoleMarketStatus.SAVED, RoleMarketStatus.TRACKING}
        for state in state_by_opening_key.values()
    )
    logo_store = _company_brand_store()
    allow_remote_logos = _remote_logos_allowed()
    opportunities = tuple(
        LandingOpportunity(
            title=match.opening.title,
            company=match.opening.company.name,
            location=" · ".join(match.role_locations) or None,
            workplace_type=match.opening.workplace_type,
            source_label=(
                "Official " + " / ".join(opening_sources(match.opening)) + " listing"
                if opening_sources(match.opening)
                else "Official listing"
            ),
            relevance=match.score,
            logo_url=logo_store.logo_for(match.opening.company.name) if allow_remote_logos else None,
        )
        for match in visible_matches[:6]
    )
    return build_landing_page_data(
        role_pages=role_pages,
        official_openings=len(visible_matches),
        shortlisted_openings=shortlisted,
        companies=len({match.opening.company.name for match in visible_matches}),
        latest_role_title=run.query.title,
        latest_refreshed_at=run.created_at,
        opportunities=opportunities,
    )


def _workspace_hero(thread: dict) -> None:
    """Make the selected target role visibly feel like its own Job Workspace."""
    draft = thread["draft"]
    title = draft["job_title"].strip() or thread["name"]
    company = draft["company"].strip()
    job_label = f"{title} · {company}" if company else title
    is_ready = bool(thread["analysis"]) and not thread["stale"]
    state = "Preparation plan ready" if is_ready else "Set up this job workspace"
    st.markdown(
        f"""<section class=\"workspace-hero\">
        <div class=\"eyebrow\">Job workspace · {escape(state)}</div>
        <h1>{escape(job_label)}</h1>
        <p>Turn this particular role into a focused preparation space: find the proof you already have, sharpen your CV guidance, build the missing evidence, and rehearse the conversation.</p>
        <span class=\"job-chip\">{escape(thread['name'])}</span>
        </section>""",
        unsafe_allow_html=True,
    )


def _advisory_skill_refinement(result) -> None:
    """Advisory skill-match decisions from the local model, optionally Jev.

    The canonical score above stays deterministic and unchanged; this block only
    reports what a typed decision model concludes about skill equivalence, with
    ambiguous pairs optionally escalated to Jev when the user has configured it.
    """

    requirements = [item for item in result.job.requirements if item.importance != "uncertain"]
    skills = list(result.candidate.skills)
    if not requirements or not skills:
        return
    from tau_job_application.jev_client import jev_available, jev_resolver
    from tau_job_application.skill_decision import refine_requirement_matches

    with st.expander("Advisory: decision-model skill matching", expanded=False):
        st.caption(
            "A typed decision model compares each requirement with your CV skills and reports how sure it is "
            "that two labels mean the same capability (for example k8s and Kubernetes). Advisory only: the "
            "match score above remains deterministic evidence coverage."
        )
        use_jev = st.checkbox(
            "Ask Jev about ambiguous skill pairs",
            key="jev-skill-decisions",
            disabled=not jev_available(),
            help=(
                "Opt-in. Only the two skill labels and a fixed question leave this machine; no CV text, "
                "adverts, or account data. Requires JEV_API_KEY and JEV_API_URL (docs/JEV_NOTES.md)."
                if jev_available() else
                "Set JEV_API_KEY and JEV_API_URL to enable. The local decision model is used until then."
            ),
        )
        resolver = jev_resolver(WORKSPACES.path) if (use_jev and jev_available()) else None
        refinement = refine_requirement_matches(skills, requirements, resolver=resolver)
        delta = refinement.refined_score - result.match.score
        cols = st.columns(3)
        cols[0].metric("Canonical coverage", f"{result.match.score}%")
        cols[1].metric("Decision-model coverage", f"{refinement.refined_score}%", delta=f"{delta:+d}" if delta else None)
        cols[2].metric("Ambiguous pairs", len(refinement.ambiguous_skills))
        if refinement.changed_requirements:
            st.write("Recognised as the same skill beyond exact spelling: " + " · ".join(refinement.changed_requirements[:8]))
        if refinement.ambiguous_skills:
            st.write("Undecided (needs your review): " + " · ".join(refinement.ambiguous_skills[:8]))
            if not jev_available():
                st.caption("Jev can settle these pairs once configured; your review is the fallback.")
        with st.expander("Every decision and its reason", expanded=False):
            st.dataframe(
                [
                    {"Requirement": item.left, "Best CV skill": item.right,
                     "Probability": item.probability, "Verdict": item.verdict,
                     "Method": item.method, "Why": item.explanation}
                    for item in refinement.decisions
                ],
                hide_index=True, use_container_width=True,
            )
        st.caption(
            f"Decision source: {'Jev (with local fallback)' if refinement.source == 'jev' else 'local deterministic model'} "
            f"· {refinement.escalated_to_jev} pair(s) escalated to Jev."
        )


def _metric_link(column, *, key: str, label: str, value: str, note: str, focus: str | None = None,
                 view: str | None = None, go: Callable[[], None] | None = None) -> None:
    """A metric that navigates to its page when clicked."""

    with column:
        if st.button(f"**{value}** {label}", key=key, use_container_width=True, help=note):
            if go:
                go()
            elif view:
                _navigate(view=view)
            else:
                _navigate(focus=focus)
        st.caption(note)


def _job_workspace_dashboard(workspace_id: str, thread_id: str) -> None:
    """The role-specific landing view; all downstream work belongs to this thread."""
    thread = WORKSPACES.thread(workspace_id, thread_id)
    draft = thread["draft"]
    result = thread["analysis"] if not thread["stale"] else None
    attempts = WORKSPACES.interview_attempts(workspace_id, thread_id)

    if thread["stale"]:
        st.warning("This workspace's job brief or profile changed after its last analysis. Refresh it in Job brief before relying on the plan.")
    if not result:
        _empty_workspace_dashboard(draft)
        return

    matched = [item.skill for item in result.match.requirements if item.status == "matched"]
    missing = [item.skill for item in result.match.requirements if item.status == "missing"]
    practice_average = round(sum(item["score"] for item in attempts) / len(attempts)) if attempts else None
    evidence_match = _evidence_match_for(result, workspace_id, thread_id)
    standout_plans = _standout_plans(result, evidence_match)
    project_backed = {
        normalize_skill(support.skill)
        for support in evidence_match.requirement_supports
        if support.support > 0
    }
    missing_to_build = [skill for skill in missing if normalize_skill(skill) not in project_backed]

    match_score = evidence_match.score if evidence_match.score is not None else result.match.score
    project_note = (
        f"completed-project proof {evidence_match.project_coverage}%"
        if evidence_match.project_coverage is not None
        else "no completed project proof yet"
    )
    st.markdown("<div class='section-kicker'>Your match for this role · tap a number to open its page</div>", unsafe_allow_html=True)
    st.progress(match_score / 100, text=f"{match_score}% match")
    chips = st.columns(3)
    if chips[0].button(f"Skills coverage {result.match.score}%", key="match-chip-skills", use_container_width=True,
                       help="Open the Job brief with the requirement evidence"):
        _navigate(focus="Job brief")
    if chips[1].button(f"CV readiness {result.cv_score.score if result.cv_score else 'n/a'}%", key="match-chip-cv", use_container_width=True,
                       help="Open the CV studio"):
        _navigate(focus="CV studio")
    if chips[2].button(f"Project proof {evidence_match.project_coverage if evidence_match.project_coverage is not None else 'n/a'}%", key="match-chip-projects", use_container_width=True,
                       help="Open your completed project evidence"):
        _navigate(focus="Proof projects")
    st.caption(
        "Deterministic evidence coverage on a 100 scale, not a hiring prediction. It rises as you load your CV, "
        "verify GitHub signals, and mark projects completed with proof. Planned work never counts."
    )
    _advisory_skill_refinement(result)

    coverage_note = f"{len(matched)} CV shown · {len(missing_to_build)} to build"
    cards = st.columns(4)
    _metric_link(cards[0], key="metric-coverage", label="Requirement evidence coverage", value=f"{result.match.score}%", note=coverage_note, focus="Job brief")
    _metric_link(cards[1], key="metric-cv", label="CV guidance", value=f"{result.cv_score.score if result.cv_score else 'n/a'}%", note="Document readiness, not a hiring prediction", focus="CV studio")
    application = next(iter(_application_store().list_records(workspace_id, thread_id=thread_id)), None)
    if application:
        _metric_link(
            cards[2], key="metric-interview", label="Interview practice",
            value=f"{practice_average if practice_average is not None else 'n/a'}",
            note=f"{len(attempts)} saved rehearsal{'s' if len(attempts) != 1 else ''} · opens this role's application workspace",
            go=lambda: _open_application(workspace_id, application.id),
        )
    else:
        _metric_link(
            cards[2], key="metric-interview", label="Interview practice",
            value=f"{practice_average if practice_average is not None else 'n/a'}",
            note="Track this role in My applications to unlock interview practice beside its status",
            view="applications",
        )
    _metric_link(cards[3], key="metric-gaps", label="Proof gaps", value=str(len(missing_to_build)), note="Requirements without CV or eligible project proof", focus="Proof projects")

    st.markdown("<div class='section-kicker'>Your next best move</div>", unsafe_allow_html=True)
    next_action, destination, reason = _next_action(result, attempts, standout_plans)
    st.markdown(
        f"<div class='next-action'><strong>{escape(next_action)}</strong><br><span>{escape(reason)} Open <strong>{escape(destination)}</strong> to work on it.</span></div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='section-kicker' style='margin-top:1.4rem'>A focused route to this role</div>", unsafe_allow_html=True)
    route = st.columns(4)
    _path_card(route[0], "01 · Map", "Job evidence", f"{len(result.job.requirements)} requirements reviewed from this role.")
    _path_card(route[1], "02 · Strengthen", "CV guidance", "Truthful edits tied to the experience you already show.")
    _path_card(route[2], "03 · Prove", "Standout project", _project_summary(standout_plans))
    _path_card(route[3], "04 · Rehearse", "Interview stories", _practice_summary(attempts))

    left, right = st.columns([1.13, 0.87], gap="large")
    with left:
        st.markdown("<div class='section-kicker'>Evidence already visible</div>", unsafe_allow_html=True)
        with st.container(border=True):
            if matched:
                st.write(" · ".join(matched[:8]))
                if len(matched) > 8:
                    st.caption(f"Plus {len(matched) - 8} more requirement matches in this job brief.")
            else:
                st.write("No confirmed requirement evidence yet. Add your CV or review the job brief before making claims.")
        st.markdown("<div class='section-kicker' style='margin-top:1rem'>Proof to build</div>", unsafe_allow_html=True)
        with st.container(border=True):
            if missing_to_build:
                st.write(" · ".join(missing_to_build[:8]))
                st.caption("These are gaps in the available evidence, not a judgment of your ability or a prediction of hiring.")
            elif missing:
                st.write("Your completed project proof covers the remaining CV evidence gap(s).")
            else:
                st.write("No missing scored requirement evidence was found in the current job brief.")
    with right:
        st.markdown("<div class='section-kicker'>This week's preparation plan</div>", unsafe_allow_html=True)
        with st.container(border=True):
            for index, action in enumerate(_weekly_actions(result, attempts, standout_plans), 1):
                st.markdown(f"**{index}.** {action}")
            st.caption("These are recommendations for this selected role; they do not submit applications or invent experience.")


def _empty_workspace_dashboard(draft: dict[str, str]) -> None:
    has_cv = bool(draft["cv_text"].strip())
    has_job = bool(draft["job_text"].strip())
    has_github = bool(draft["github"].strip())
    has_portfolio = bool(draft["portfolio"].strip())
    st.markdown("<div class='section-kicker'>Make this a real preparation room</div>", unsafe_allow_html=True)
    st.markdown("#### Every target role gets its own evidence, plan, projects, and rehearsal history.")
    route = st.columns(3)
    profile_note = "CV added" if has_cv else "Upload or paste the CV you want this role assessed against."
    if has_cv and not (has_github or has_portfolio):
        profile_note += " Add GitHub and/or a portfolio to make your profile easier to explore."
    _path_card(route[0], "01", "Add your profile", profile_note)
    _path_card(route[1], "02", "Add the job brief", "Done" if has_job else "Paste the role description or read it from the official job URL.")
    _path_card(route[2], "03", "Analyze this job", "Unlocks CV guidance, proof projects, and interview questions.")
    if not has_cv:
        st.info("Start in Job brief with your CV. We will also ask for your GitHub profile and/or portfolio if you have them; those links are optional and never verified automatically.")
    elif not (has_github or has_portfolio):
        st.info("Your CV is ready. Add your GitHub profile and/or portfolio in Job brief to make your profile more useful to review and explore.")
    if has_cv and has_job:
        st.success("This workspace is ready. Open Job brief and choose Analyze this job.")
    else:
        st.info("Start in Job brief. Nothing is sent anywhere when you add your CV or a job description.")


def _metric_card(column, label: str, value: str, note: str) -> None:
    column.markdown(
        f"<div class='metric-card'><div class='metric-label'>{escape(label)}</div><div class='metric-value'>{escape(value)}</div><div class='metric-note'>{escape(note)}</div></div>",
        unsafe_allow_html=True,
    )


def _path_card(column, step: str, title: str, detail: str) -> None:
    column.markdown(
        f"<div class='path-card'><div class='path-step'>{escape(step)}</div><h4>{escape(title)}</h4><p>{escape(detail)}</p></div>",
        unsafe_allow_html=True,
    )


def _next_action(result, attempts: list[dict], standout_plans) -> tuple[str, str, str]:
    if result.authenticity_report and result.authenticity_report.status == "blocked":
        return ("Resolve unsupported CV claims first.", "CV studio", "The workspace cannot safely turn unsupported claims into application language.")
    if standout_plans:
        plan = standout_plans[0]
        return (f"Build standout evidence: {plan.title}.", "Proof projects", f"It is the clearest next chance to build evidence for {', '.join(plan.skills_practised[:2])}.")
    if not attempts:
        return ("Complete your first role-specific rehearsal.", "My applications", "Interview practice lives beside the job status in this role's application workspace, grounded in its current requirements.")
    if result.cv_score and result.cv_score.next_actions:
        return (result.cv_score.next_actions[0], "CV studio", "Review the evidence-aware guidance before changing your CV.")
    return ("Review your evidence and choose one thing to strengthen.", "CV studio", "Keep every claim grounded in work you can explain and support.")


def _project_summary(standout_plans) -> str:
    if not standout_plans:
        return "No standout project is needed from the current evidence gaps."
    plan = standout_plans[0]
    return f"Standout: {plan.title} · about {plan.estimated_hours} hours."


def _practice_summary(attempts: list[dict]) -> str:
    if not attempts:
        return "Start with one saved answer for this exact role."
    categories = sorted({attempt["category"] for attempt in attempts})
    return f"{len(attempts)} saved rehearsal{'s' if len(attempts) != 1 else ''} across {', '.join(categories)}."


def _weekly_actions(result, attempts: list[dict], standout_plans) -> list[str]:
    actions: list[str] = []
    if result.cv_score:
        actions.extend(result.cv_score.next_actions[:1])
    if standout_plans:
        plan = standout_plans[0]
        actions.append(f"Choose the first milestone for “{plan.title}” and define its proof of completion.")
    if not attempts:
        actions.append("Practice one job-specific interview question and save the feedback in the application workspace's Interview practice tab.")
    else:
        actions.append("Rehearse a different question category than your last saved attempt.")
    return actions[:3]


def _quickstart(workspace_id: str, thread_id: str) -> None:
    thread = WORKSPACES.thread(workspace_id, thread_id)
    draft = thread["draft"]
    if loaded_job := st.session_state.pop(f"loaded-job:{thread_id}", None):
        draft.update(loaded_job)
        for field, value in loaded_job.items():
            st.session_state[draft_key(thread_id, field)] = value
        WORKSPACES.save_draft(workspace_id, thread_id, draft)
    if st.session_state.pop(f"refresh-profile:{thread_id}", False):
        draft.update(WORKSPACES.shared_profile())
        for field in PROFILE_FIELDS:
            st.session_state[draft_key(thread_id, field)] = draft[field]
        WORKSPACES.save_draft(workspace_id, thread_id, draft)
    st.caption(f"Job workspace: {thread['name']}. Text inputs auto-save locally. This role keeps its own profile snapshot, analysis, interview practice, and coaching history.")
    upload_error = False
    with st.container(border=True):
        st.subheader("1. Your profile: CV, GitHub / Portfolio")
        st.caption("Your CV is needed for role-specific guidance. Add your GitHub profile and/or portfolio when available; they are optional, remain local, and are never assumed to prove skills or ownership.")
        left, right = st.columns([1, 1])
        with left:
            uploaded = st.file_uploader("Drop your CV here", type=["pdf", "docx", "txt", "md"], help="PDF must have selectable text. Extracted text is editable below.", key=f"cv-upload:{thread_id}")
            if uploaded is not None:
                digest = hashlib.sha256(uploaded.getvalue()).hexdigest()
                if st.session_state.get(f"cv-digest:{thread_id}") != digest:
                    try:
                        st.session_state[draft_key(thread_id, "cv_text")] = _upload_text(uploaded)
                        st.session_state[f"cv-digest:{thread_id}"] = digest
                    except Exception as exc:
                        st.error(str(exc))
                        upload_error = True
            cv_text = st.text_area("Or paste your CV text", value=draft["cv_text"], key=draft_key(thread_id, "cv_text"), height=220, placeholder="Name: Alex\nSkills: Python, SQL\nExperience: Built a data API...")
        inferred_links = infer_profile_links(cv_text)
        if inferred_links:
            st.success("Detected from CV: " + ", ".join(f"{key} ({value})" for key, value in inferred_links.items()) + ". Please verify or edit them.")
            for field, value in inferred_links.items():
                if not draft[field]:
                    st.session_state.setdefault(draft_key(thread_id, field), value)
                    draft[field] = value
        with right:
            github = st.text_input("GitHub profile (recommended when available)", value=draft["github"], key=draft_key(thread_id, "github"), placeholder="https://github.com/yourname")
            portfolio = st.text_input("Portfolio / personal website (recommended when available)", value=draft["portfolio"], key=draft_key(thread_id, "portfolio"), placeholder="https://yourname.dev")
            linkedin = st.text_input("LinkedIn", value=draft["linkedin"], key=draft_key(thread_id, "linkedin"), placeholder="https://linkedin.com/in/yourname")
            x_url = st.text_input("X / Twitter", value=draft["x"], key=draft_key(thread_id, "x"), placeholder="https://x.com/yourname")
            enrich = st.checkbox("Inspect public GitHub languages after analysis (unconfirmed)", key=f"enrich:{thread_id}")
        profile = {"cv_text": cv_text, "github": github, "portfolio": portfolio, "linkedin": linkedin, "x": x_url}
        if st.button("Save as shared profile for new Job Workspaces", disabled=upload_error or not cv_text.strip(), key=f"save-profile:{thread_id}"):
            WORKSPACES.save_shared_profile(profile)
            st.success("New Job Workspaces will start with this CV and links. Existing workspaces and old analyses are unchanged.")
        if st.button("Use latest shared profile in this Job Workspace", key=f"load-profile:{thread_id}"):
            st.session_state[f"refresh-profile:{thread_id}"] = True
            st.rerun()

    with st.container(border=True):
        st.subheader("2. This target role")
        job_title = st.text_input("Job title", value=draft["job_title"], key=draft_key(thread_id, "job_title"), placeholder="Backend Engineer")
        company = st.text_input("Company", value=draft["company"], key=draft_key(thread_id, "company"), placeholder="Acme")
        job_url = st.text_input("Job description URL", value=draft["job_url"], key=draft_key(thread_id, "job_url"), placeholder="https://careers.example.com/job")
        if st.button("Read job URL", key=f"read-job:{thread_id}", disabled=not job_url.strip()):
            try:
                page_job = fetch_job_url(job_url)
                loaded = {"job_title": page_job.title, "company": page_job.company,
                          "job_url": page_job.url or job_url, "job_text": page_job.description or ""}
                st.session_state[f"loaded-job:{thread_id}"] = loaded
                st.success("Job title, company, description, and source URL inferred. Review the extracted text, then analyze this job.")
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
        job_text = st.text_area("Job description", value=draft["job_text"], key=draft_key(thread_id, "job_text"), height=200, placeholder="Or paste the description: you are experienced with Python and comfortable building APIs…")
        draft = {**profile, "job_title": job_title, "company": company, "job_url": job_url, "job_text": job_text}
        WORKSPACES.save_draft(workspace_id, thread_id, draft)
        st.caption("Requirements are inferred from wording and context. Optional review appears below; ambiguous mentions are not scored.")
        if job_text.strip():
            _requirement_editor(job_text)

    existing = WORKSPACES.thread(workspace_id, thread_id)
    analysis_label = "Refresh this job workspace" if existing["analysis"] else "Analyze this job"
    if st.button(analysis_label, type="primary", use_container_width=True, disabled=upload_error, key=f"build:{thread_id}"):
        try:
            candidate_text = cv_text
            if not candidate_text.strip() or not job_text.strip():
                raise ValueError("Provide both a CV and a job description.")
            links = {"github": github or None, "portfolio": portfolio or None, "linkedin": linkedin or None, "x": x_url or None}
            result = analyze_texts(
                candidate_text, job_text,
                links=links, job_title=job_title or None, company=company or None, job_url=job_url or None,
                requirement_memory=REQUIREMENT_MEMORY,
            )
            if enrich and github:
                candidate = enrich_github_profile(result.candidate)
                result = result.model_copy(update={"candidate": candidate})
            WORKSPACES.save_analysis(workspace_id, thread_id, result)
            st.session_state["analysis"] = result
        except Exception as exc:
            st.error(str(exc))

    current = WORKSPACES.thread(workspace_id, thread_id)
    if current["stale"]:
        st.warning("Saved inputs or reviewed requirements changed. Rebuild this plan; the older snapshot is retained but excluded from comparisons and coaching.")
    result = current["analysis"] if not current["stale"] else None
    st.session_state["analysis"] = result
    if not result:
        return

    st.success("This job workspace is ready. Use CV studio, Proof projects, and Interview practice in the application workspace to act on the plan for this exact role.")
    with st.expander("Review the role evidence used in this plan"):
        evidence = {item.id: item for item in result.job.evidence}
        for requirement in result.job.requirements:
            source = evidence.get(requirement.evidence_id)
            label = "required" if requirement.required else "preferred"
            st.markdown(f"**{requirement.skill}** · {label}")
            if source:
                st.caption(f"“{source.quote}”")

    if result.authenticity_report and result.authenticity_report.status == "blocked":
        st.error("Download is disabled while the CV contains unsupported claims. Remove or evidence them first.")
    else:
        report = render_markdown(result)
        st.download_button("Download this job workspace plan (.md)", report, file_name="job-workspace-plan.md", mime="text/markdown")


def _cv_studio(workspace_id: str, thread_id: str) -> None:
    """Evidence-aware CV guidance, kept separate for every target role."""
    thread = WORKSPACES.thread(workspace_id, thread_id)
    result = thread["analysis"] if not thread["stale"] else None
    st.subheader("CV studio")
    st.caption("Refine your narrative for this role without inventing employers, skills, dates, or outcomes. This workspace currently provides guidance, not a finished CV editor.")
    if thread["stale"]:
        st.warning("Refresh the Job brief first. CV guidance is held back while its underlying evidence is stale.")
        return
    if not result:
        st.info("Analyze this job in Job brief to receive role-specific CV guidance.")
        return

    left, right = st.columns([0.93, 1.07], gap="large")
    with left:
        st.markdown("<div class='section-kicker'>Document readiness</div>", unsafe_allow_html=True)
        if result.cv_score:
            _metric_card(st, "CV guidance", f"{result.cv_score.score}%", "Clarity and evidence readiness, not a hiring prediction")
            for component in result.cv_score.components:
                st.progress(component.score / 100, text=f"{component.name}: {component.score}/100")
            if result.cv_score.next_actions:
                st.markdown("**Prioritized improvements**")
                for action in result.cv_score.next_actions:
                    st.markdown(f"- {action}")
        matched = [item.skill for item in result.match.requirements if item.status == "matched"]
        with st.container(border=True):
            st.markdown("**Requirement evidence you can emphasize**")
            st.write(" · ".join(matched) if matched else "No confirmed requirement evidence in the current CV yet.")
            st.caption("Only emphasize claims you can explain, substantiate, and stand behind in an interview.")
    with right:
        st.markdown("<div class='section-kicker'>Role-specific safe edits</div>", unsafe_allow_html=True)
        if result.tailored_resume:
            st.markdown(f"#### {result.tailored_resume.target_title}")
            st.write(result.tailored_resume.summary)
            st.caption(result.tailored_resume.safety_note)
            candidate_evidence = {item.id: item for item in result.candidate.evidence}
            for index, suggestion in enumerate(result.tailored_resume.suggestions, 1):
                with st.expander(f"{index}. {suggestion.section}", expanded=index == 1):
                    st.write(suggestion.recommendation)
                    st.markdown("**Copy-ready draft to review**")
                    st.code(suggestion.safe_draft, language="markdown")
                    sources = [candidate_evidence[source_id] for source_id in suggestion.evidence_ids if source_id in candidate_evidence]
                    if sources:
                        st.markdown("**Grounded in your supplied evidence**")
                        for source in sources:
                            st.caption(f"• {source.quote}")
        else:
            st.info("No tailored CV suggestions are available for this job yet.")

    if result.authenticity_report:
        report = result.authenticity_report
        st.markdown("<div class='section-kicker' style='margin-top:1rem'>Claim safety check</div>", unsafe_allow_html=True)
        status_color = {"ready": "green", "needs_review": "orange", "blocked": "red"}[report.status]
        st.markdown(f"**Status:** :{status_color}[{report.status.replace('_', ' ').title()}]")
        st.write(report.overall_guidance)
        for section in report.rewrite_sections:
            with st.expander(f"Review {section.section}"):
                st.write(section.reason)
                st.caption(section.candidate_action)


def _project_evidence(workspace_id: str, thread_id: str) -> None:
    """Candidate-owned completed project proof; the score itself lives in the Overview match bar."""
    thread = WORKSPACES.thread(workspace_id, thread_id)
    result = thread["analysis"] if not thread["stale"] else None
    st.divider()
    st.subheader("Your completed project evidence")
    st.caption(
        "Not a hiring prediction. This compares the published role requirements with the "
        "confirmed CV and completed project evidence you choose. It does not search employee "
        "profiles, infer who was hired, or scrape LinkedIn."
    )
    if thread["stale"]:
        st.warning("Refresh the Job brief first. Project evidence is held back while the role evidence is stale.")
        return
    if not result:
        st.info("Analyze this job in Job brief to compare its sourced requirements with your completed project evidence.")
        return

    evidence_store = _evidence_store()
    projects = evidence_store.list_projects(workspace_id, thread_id)
    assessment = calculate_evidence_match(result.candidate, result.job, projects)
    if assessment.project_status == "not_provided":
        st.info("Add a completed, verifiable project below to raise the project-proof component of your match bar.")
    elif assessment.project_status == "no_eligible_projects":
        st.warning("Saved project records need a completed status, your confirmation, a proof reference, and an observable outcome/test before they can contribute.")
    elif assessment.project_status == "no_matching_project_evidence":
        st.info("Your completed projects are saved, but none explicitly demonstrates a currently scored role requirement. They are not used to lower the evidence score.")
    elif assessment.project_status == "insufficient_role_evidence":
        st.info("This role currently has no scored required/preferred requirements to compare with project evidence.")

    if assessment.requirement_supports:
        st.markdown("#### How completed projects support this role")
        st.dataframe(
            [
                {
                    "Role requirement": item.skill,
                    "Importance": "Required" if item.required else "Preferred",
                    "Project support": f"{round(item.support * 100)}%",
                    "Completed project": " · ".join(item.project_titles),
                    "Reason": item.explanation,
                }
                for item in assessment.requirement_supports
            ],
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("#### Add completed work")
    st.caption(
        "Add only work you have completed and can explain. Use a public or otherwise non-confidential "
        "reference; this app stores the reference locally and does not fetch it. Planned briefs in Proof projects never count here."
    )
    with st.form(f"project-evidence-form:{thread_id}", clear_on_submit=True):
        title = st.text_input("Completed project title", placeholder="For example: Incident analytics API")
        contribution = st.text_area(
            "Your concrete contribution",
            placeholder="What you personally designed, built, or validated, not a team-wide claim.",
        )
        skills = st.text_input("Skills demonstrated", placeholder="For example: Python, Docker, PostgreSQL")
        proof_kind = st.selectbox(
            "Proof type",
            [kind.value for kind in ProjectProofKind],
            format_func=lambda value: value.replace("_", " ").title(),
        )
        proof_reference = st.text_input(
            "Proof link or source reference",
            placeholder="https://… or a precise portfolio/CV reference",
        )
        outcome_or_test = st.text_area(
            "Observable outcome or test",
            placeholder="For example: deployed demo, passing integration test, or reproducible benchmark.",
        )
        confirmed = st.checkbox("I confirm this is completed work, my contribution is accurate, and I can discuss the proof.")
        submitted = st.form_submit_button("Save completed project evidence", type="primary")
    if submitted:
        try:
            if not confirmed:
                raise ValueError("Confirm the project before saving it as completed evidence")
            saved = evidence_store.create_project(
                workspace_id,
                thread_id,
                title=title,
                contribution=contribution,
                skills=tuple(part.strip() for part in skills.split(",") if part.strip()),
                proofs=(ProjectProof(kind=ProjectProofKind(proof_kind), reference=proof_reference, confirmed=True),),
                outcome_or_test=outcome_or_test,
                status=ProjectStatus.COMPLETED,
                candidate_confirmed=True,
            )
            STORE.record_event("completed_project_evidence_saved", {"project_id": saved.id, "skill_count": len(saved.skills)})
            st.success("Completed project evidence saved locally for this Job Workspace.")
            st.rerun()
        except (TypeError, ValueError) as exc:
            st.error(str(exc))

    if projects:
        for project in projects:
            with st.expander(f"{project.title} · {project.status.value.replace('_', ' ')}", expanded=False):
                st.write(project.contribution)
                st.caption("Skills: " + " · ".join(project.skills))
                st.caption("Outcome/test: " + (project.outcome_or_test or "Not supplied"))
                for proof in project.proofs:
                    confirmation = "confirmed" if proof.confirmed else "not confirmed"
                    st.caption(f"{proof.kind.value.replace('_', ' ').title()} ({confirmation}): {proof.reference}")
                if st.button("Remove this project evidence", key=f"remove-project-evidence:{thread_id}:{project.id}"):
                    evidence_store.delete_project(workspace_id, thread_id, project.id)
                    STORE.record_event("completed_project_evidence_deleted", {"project_id": project.id})
                    st.rerun()

    st.markdown("#### Company hiring-pattern alignment")
    st.info(
        f"Unavailable for {result.job.company}. This app will not build a score from people who work there, "
        "public profiles, or inferred hiring history. A future component can use only an employer-authorized, "
        "anonymous, role-specific capability benchmark with dated provenance."
    )
    with st.expander("What would make a company benchmark eligible?", expanded=False):
        st.markdown(
            "It must be an employer-authorized or licensed aggregate rubric for this company and role, include "
            "its source and validity dates, attest data rights and anonymisation, and contain capability criteria "
            "rather than employee profiles, CVs, or historic-hire records."
        )
    with st.expander("Evidence-match limits", expanded=False):
        for limitation in assessment.limitations:
            st.markdown(f"- {limitation}")


def _project_studio(workspace_id: str, thread_id: str) -> None:
    """Turn evidence gaps into an honest, role-specific portfolio build brief."""
    thread = WORKSPACES.thread(workspace_id, thread_id)
    result = thread["analysis"] if not thread["stale"] else None
    st.subheader("Proof projects")
    st.caption("When the role needs stronger evidence, we recommend one focused project and, only when useful, one flagship integration project. A project is not work experience until you have actually completed it.")
    if thread["stale"]:
        st.warning("Refresh the Job brief first. Project recommendations are held back while the role evidence is stale.")
        return
    if not result:
        st.info("Analyze this job in Job brief to generate projects tied to its evidence gaps.")
        return
    projects = _evidence_store().list_projects(workspace_id, thread_id)
    assessment = calculate_evidence_match(result.candidate, result.job, projects)
    st.markdown("#### Your completed project evidence")
    st.caption("Only completed, candidate-confirmed projects with a proof reference and observable outcome can support the evidence score. Add or edit them here in Proof projects.")
    if projects:
        for project in projects:
            project_skills = " · ".join(project.skills)
            eligible_note = "eligible for review" if project.title in assessment.matched_project_titles else "not currently mapped to a scored role requirement"
            with st.container(border=True):
                st.markdown(f"**{project.title}** · {eligible_note}")
                st.caption(f"Skills: {project_skills}")
                st.write(project.contribution)
                st.caption("Outcome/test: " + (project.outcome_or_test or "Not supplied"))
        if assessment.project_coverage is not None:
            st.success(f"Completed-project proof coverage for this role: {assessment.project_coverage}%.")
        elif assessment.project_status == "no_matching_project_evidence":
            st.info("These completed projects are retained as your evidence inventory, but none is being used for this role's score.")
    else:
        st.info("No completed project evidence has been added for this Job Workspace. Add real, finished work here in Proof projects; planned briefs below do not count.")
    standout_plans = _standout_plans(result, assessment)
    if not standout_plans:
        st.success("The current job analysis did not identify an evidence gap that needs a standout project.")
        return

    st.markdown("#### Standout projects to build")
    missing_by_skill = {
        normalize_skill(item.skill): item.skill
        for item in result.match.requirements
        if item.status == "missing"
    }
    requirement_by_skill = {
        normalize_skill(requirement.skill): requirement
        for requirement in result.job.requirements
    }
    evidence_by_id = {item.id: item for item in result.job.evidence}
    count_note = "One focused project is enough for this role." if len(standout_plans) == 1 else "Build these in sequence; the second turns the first project's proof into a stronger end-to-end portfolio case."
    st.markdown(f"<div class='quiet-panel'><strong>{escape(count_note)}</strong><br>We only surface these because the current role has unproven requirements. A standout project should solve a credible problem, make the relevant skills visible, include a working proof, and explain trade-offs and limitations.</div>", unsafe_allow_html=True)
    for index, plan in enumerate(standout_plans, 1):
        addressed = [
            (skill, missing_by_skill[normalize_skill(skill)])
            for skill in plan.skills_practised
            if normalize_skill(skill) in missing_by_skill
        ]
        project_kind = "Focused proof" if index == 1 else "Flagship integration"
        with st.expander(f"{index}. {project_kind}: {plan.title} · about {plan.estimated_hours} hours", expanded=index == 1):
            st.markdown(f"**Why this helps:** {plan.problem}")
            if addressed:
                st.markdown("**Evidence gaps it can help you address:** " + ", ".join(actual_skill for _, actual_skill in addressed))
                for plan_skill, actual_skill in addressed:
                    requirement = requirement_by_skill.get(normalize_skill(plan_skill))
                    source = evidence_by_id.get(requirement.evidence_id) if requirement else None
                    if source:
                        st.caption(f"{actual_skill} in this job brief: “{source.quote}”")
            else:
                st.caption("This is a supporting project idea; it is not being presented as proof of a missing requirement.")
            milestones, proof = st.columns(2)
            with milestones:
                st.markdown("**Build sequence**")
                for number, milestone in enumerate(plan.milestones, 1):
                    st.markdown(f"{number}. {milestone}")
            with proof:
                st.markdown("**Publishable proof**")
                for item in [*plan.deliverables, *plan.acceptance_tests]:
                    st.markdown(f"- {item}")
            if plan.readme_outline:
                st.markdown("**README outline**")
                st.write(" → ".join(plan.readme_outline))
            st.info("When it is complete, describe it accurately as a personal project and be ready to explain your exact contribution.")


def _requirement_editor(job_text: str) -> None:
    """Review current-job labels; reuse aliases only through a separate explicit action."""
    scope = st.session_state.get("active_scope")
    key = f"{scope[1] if scope else 'local'}-{document_key(job_text)}"
    requirements, evidence = extract_requirements(job_text, KNOWN_SKILLS, memory=REQUIREMENT_MEMORY)
    quotes = {item.id: item.quote for item in evidence}
    with st.expander("Review inferred requirements / leave parsing feedback (optional)", expanded=False):
        st.caption("English-first, rule-based inference, not a trained semantic model. Edit names or importance, remove false positives, or add a missing skill with an exact quote from the description.")
        if requirements:
            st.dataframe([{"Skill": r.skill, "Importance": r.importance, "Method": r.extraction_method,
                           "Heuristic confidence (not calibrated)": r.confidence, "Needs review": r.needs_review}
                          for r in requirements], hide_index=True)
        else:
            st.warning("No requirements were inferred yet. Add a source quote and capability manually below, or paste more job context.")
        rating = st.selectbox("Was this extraction useful?", ["useful", "partly useful", "not useful"], key=f"feedback-rating-{key}")
        feedback_comment = st.text_area("Feedback for the parser (optional)", key=f"feedback-comment-{key}", placeholder="For example: 'Treat comfortable with X as preferred in this kind of role.'")
        if st.button("Save extraction feedback", key=f"feedback-save-{key}"):
            try:
                REQUIREMENT_MEMORY.save_feedback(job_text, rating, feedback_comment)
                st.success("Feedback saved locally. It will be reviewed as product data; it does not silently retrain the model.")
            except ValueError as exc:
                st.error(str(exc))
        rows = [{"keep": True, "skill": r.skill, "importance": r.importance, "quote": quotes[r.evidence_id]}
                for r in requirements]
        edited = st.data_editor(rows or [{"keep": True, "skill": "", "importance": "required", "quote": ""}],
            num_rows="dynamic", key=f"requirements-{key}", hide_index=True,
            column_config={
                "keep": st.column_config.CheckboxColumn("Keep", default=True),
                "skill": st.column_config.TextColumn("Skill / capability", required=True),
                "importance": st.column_config.SelectboxColumn("Importance", options=["required", "preferred", "uncertain"], required=True),
                "quote": st.column_config.TextColumn("Exact source quote", required=True),
            })
        confirmed = st.checkbox("I reviewed these interpretations against the source text", key=f"review-confirm-{key}")
        if st.button("Save corrections for this description", key=f"save-review-{key}", disabled=not confirmed):
            try:
                save_requirement_review(job_text, edited, REQUIREMENT_MEMORY)
                st.session_state.pop("analysis", None)
                WORKSPACES.invalidate_description(job_text)
                st.success("Corrections saved locally. Select Refresh this job workspace to use them. Future loads of this exact description will reuse them.")
            except ValueError as exc:
                st.error(str(exc))
        if st.button("Forget corrections for this description", key=f"forget-review-{key}"):
            REQUIREMENT_MEMORY.forget_review(job_text)
            WORKSPACES.invalidate_description(job_text)
            st.session_state.pop(f"requirements-{key}", None)
            st.session_state.pop("analysis", None)
            st.rerun()
        st.markdown("**Teach a reusable phrase → skill mapping**")
        st.caption("Only learn mappings you explicitly approve. Required/preferred importance is inferred afresh in each new job, not copied from this one.")
        phrase = st.text_input("Exact phrase to recognize in future jobs", key=f"alias-phrase-{key}", placeholder="event-driven services")
        skill = st.text_input("Canonical skill name", key=f"alias-skill-{key}", placeholder="Event-driven architecture")
        remember = st.checkbox("Reuse this mapping in future job-workspace assessments", key=f"alias-confirm-{key}")
        if st.button("Remember mapping", key=f"alias-save-{key}", disabled=not remember):
            try:
                reviewed = REQUIREMENT_MEMORY.reviewed(job_text)
                if not reviewed:
                    raise ValueError("Save a reviewed description before teaching a reusable mapping")
                confirmed_quotes = {e.id: e.quote for e in reviewed[1]}
                source_quote = next((confirmed_quotes[r.evidence_id] for r in reviewed[0]
                                     if r.skill.casefold() == skill.strip().casefold() and
                                     phrase.strip().casefold() in confirmed_quotes[r.evidence_id].casefold()), None)
                if source_quote is None:
                    raise ValueError("The mapping must agree with a saved skill and its source quote")
                REQUIREMENT_MEMORY.learn_alias(phrase, skill, source_quote=source_quote, user_confirmed=True)
                st.success("Mapping remembered locally. No external model was trained and no CV data was used.")
            except ValueError as exc:
                st.error(str(exc))
        aliases = REQUIREMENT_MEMORY.aliases()
        if aliases:
            st.dataframe([{"Phrase": p, "Skill": s} for p, s in aliases.items()], hide_index=True)
            forgotten = st.selectbox("Mapping to remove", list(aliases), key=f"alias-remove-{key}")
            if st.button("Forget mapping", key=f"alias-delete-{key}"):
                REQUIREMENT_MEMORY.forget_alias(forgotten)
                st.rerun()


def _open_job_thread(job, key: str) -> None:
    if st.button("Create job workspace", key=key):
        wid = st.session_state["active_scope"][0]
        draft = {**WORKSPACES.shared_profile(), "job_title": job.title, "company": job.company,
                 "job_url": job.url or "", "job_text": job.description or ""}
        tid = WORKSPACES.create_thread(wid, f"{job.title} · {job.company}"[:100], draft)
        st.session_state[f"pending_thread:{wid}"] = tid
        st.rerun()


def _opportunities(workspace_id: str, thread_id: str) -> None:
    """Role-first discovery, separate company research, and advanced data paths."""
    if st.button("My applications", key=f"market-application-tracker:{thread_id}"):
        _navigate(view="applications")
    role_tab, company_tab, sources_tab = st.tabs([
        "Role discovery", "Company research", "Bring a lawful source",
    ])
    with role_tab:
        _role_discovery(workspace_id, thread_id)
    with company_tab:
        _company_explorer(workspace_id, thread_id)
    with sources_tab:
        _permitted_sources()


def _role_discovery(workspace_id: str, thread_id: str) -> None:
    """Collect and render a role market from a small vetted employer-board set."""
    thread = WORKSPACES.thread(workspace_id, thread_id)
    run = ROLE_DISCOVERY.latest_run(career_track_id=workspace_id, workspace_id=thread_id)
    refresh_notice = st.session_state.get(f"role-market-refresh-notice:{thread_id}")
    saved_query = run.query if run else None
    default_title = (saved_query.title if saved_query else thread["draft"]["job_title"].strip())
    default_aliases = (
        ", ".join(saved_query.aliases)
        if saved_query and saved_query.aliases
        else ", ".join(suggest_role_aliases(default_title)) if default_title else ""
    )
    profile = thread["draft"]
    links = {field: profile[field] for field in PROFILE_FIELDS if field != "cv_text" and profile[field].strip()}
    profile_skills = detected_profile_skills(profile["cv_text"], links)

    st.subheader("Build a role market")
    st.caption("Create a market page for one role. The backend collects only registered, public employer career feeds after you choose to refresh; it never scrapes LinkedIn or sends your CV text to a job board.")
    if refresh_notice:
        st.warning(refresh_notice)
    role_title = st.text_input(
        "Role to explore",
        value=default_title,
        placeholder="Machine Learning Engineer",
        key=f"role-market-title:{thread_id}",
    )
    suggested = suggest_role_aliases(role_title) if role_title.strip() else ()
    if suggested:
        st.caption("Suggested lookalike family: " + " · ".join(suggested) + ". Edit the list before refreshing if needed.")
    aliases = st.text_input(
        "Lookalike role titles (comma-separated)",
        value=default_aliases,
        placeholder="Applied Scientist, AI Engineer, Platform Engineer",
        key=f"role-market-aliases:{thread_id}",
    )
    if profile_skills:
        st.caption("Local profile-skill ranking: " + " · ".join(profile_skills[:12]) + (f" · +{len(profile_skills) - 12} more" if len(profile_skills) > 12 else "") + ". These skills stay on this device.")
    else:
        st.caption("Add a CV in Job brief to add local profile-skill ranking. A role title alone can still be explored.")

    market_companies = {board.company.name for board in DEFAULT_VETTED_COMPANY_BOARDS}
    if run:
        market_companies.update(match.opening.company.name for match in run.matches)
    _company_mark_manager(market_companies, thread_id)

    catalog_sources = sorted({board.source for board in DEFAULT_VETTED_COMPANY_BOARDS})
    enabled_sources = st.multiselect(
        "Registered public feeds to refresh",
        catalog_sources,
        default=catalog_sources,
        key=f"role-market-sources:{thread_id}",
        help="The current registry is small and vetted. Add an authorized or licensed source in the separate Bring a lawful source panel; this is not an internet-wide crawler.",
    )
    if st.button("Discover matching openings", type="primary", key=f"role-market-refresh:{thread_id}"):
        if not role_title.strip():
            st.error("Enter the role you want to explore first.")
        elif not enabled_sources:
            st.error("Select at least one registered public feed to refresh.")
        else:
            with st.spinner("Collecting registered employer openings and matching role families…"):
                _refresh_role_market(
                    workspace_id,
                    thread_id,
                    role_title=role_title,
                    aliases=aliases,
                    profile_skills=profile_skills,
                    enabled_sources=tuple(enabled_sources),
                )
            st.rerun()

    linkedin_target = quote_plus(role_title.strip() or "job openings")
    st.link_button(
        "Search this role on LinkedIn",
        f"https://www.linkedin.com/jobs/search/?keywords={linkedin_target}",
        type="secondary",
    )
    st.caption("This opens LinkedIn for you; it does not import LinkedIn listings. A LinkedIn job feed requires an approved partner or licensed-data integration.")

    if run is None:
        st.info("Choose a role and refresh to build its first local opportunity board. The visible results will be role-like openings only, not raw feed records.")
        return
    if role_title.strip() and role_title.casefold() != run.query.title.casefold():
        st.warning(f"The saved opportunity board is for “{run.query.title}”. Refresh to replace it with “{role_title.strip()}”.")

    st.divider()
    st.markdown(f"### {run.query.title} opportunity board")
    st.caption(f"Last refreshed locally: {run.created_at}. Results may have changed at the source since then.")
    _role_discovery_filters(run, workspace_id, thread_id)


def _company_mark_manager(company_names: set[str], thread_id: str) -> None:
    """Let the candidate transparently manage browser-rendered company marks."""

    store = _company_brand_store()
    local_brands = store.list_brands()
    known_companies = sorted(
        {*company_names, *(brand.company_name for brand in local_brands)},
        key=str.casefold,
    )
    with st.expander("Manage company marks", expanded=False):
        st.caption(
            "Cards use a small visual catalog for supported companies, a local initials fallback elsewhere, "
            "or a logo image you explicitly add below. Your mapping stays on this device."
        )
        st.caption(
            "Logo images load directly in your browser, not through this app's server. "
            "Use only a public HTTPS image URL you trust and are allowed to display."
        )
        choice = st.selectbox(
            "Company to manage",
            ["Add another company", *known_companies],
            key=f"brand-company-choice:{thread_id}",
        )
        custom_company = ""
        if choice == "Add another company":
            custom_company = st.text_input(
                "Company name",
                placeholder="Example company",
                key=f"brand-company-custom:{thread_id}",
            )
        company_name = custom_company if choice == "Add another company" else choice
        saved = None
        if company_name.strip():
            try:
                saved = store.get(company_name)
            except ValueError:
                saved = None
        form_token = hashlib.sha256(company_name.strip().casefold().encode("utf-8")).hexdigest()[:12]
        with st.form(f"company-brand-form:{thread_id}:{form_token}"):
            logo_url = st.text_input(
                "Public HTTPS logo image URL",
                value=saved.logo_url if saved and saved.logo_url else "",
                placeholder="https://assets.example.com/company-mark.svg",
                help="Leave empty and save to choose initials for this company.",
                key=f"brand-url:{thread_id}:{form_token}",
            )
            source = st.text_input(
                "Source / note",
                value=saved.source if saved else "candidate-provided",
                help="For example: 'company press kit, checked 6 Oct 2026'.",
                key=f"brand-source:{thread_id}:{form_token}",
            )
            actions = st.columns(3)
            with actions[0]:
                save = st.form_submit_button("Save mark", type="primary", use_container_width=True)
            with actions[1]:
                initials = st.form_submit_button("Use initials", use_container_width=True)
            with actions[2]:
                remove = st.form_submit_button(
                    "Remove override",
                    disabled=saved is None,
                    use_container_width=True,
                )
        if save or initials or remove:
            if not company_name.strip():
                st.error("Enter a company name before changing a company mark.")
            elif remove:
                store.delete(company_name)
                st.success("Local company-mark override removed. The card now uses its catalog mark or initials.")
                st.rerun()
            elif initials:
                try:
                    store.upsert(company_name, None, source="candidate chose initials")
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success("This company will use initials locally.")
                    st.rerun()
            else:
                try:
                    checked_url = validate_public_https_logo_url(logo_url)
                    store.upsert(
                        company_name,
                        checked_url,
                        source=source or "candidate-provided",
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    if checked_url:
                        st.success("Company mark saved locally.")
                    else:
                        st.success("This company will use initials locally.")
                    st.rerun()

        st.markdown("**Local overrides**")
        if local_brands:
            st.dataframe(
                [
                    {
                        "Company": brand.company_name,
                        "Display": "Custom HTTPS image" if brand.logo_url else "Initials",
                        "Source": brand.source,
                        "Changed": brand.updated_at,
                    }
                    for brand in local_brands
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("No local overrides yet. The role cards use a catalog mark where available and initials otherwise.")
        st.caption(
            "Catalog marks come from Simple Icons and can be replaced or suppressed above. "
            "They are visual identifiers, not endorsements or proof of affiliation."
        )


def _role_discovery_filters(run, career_track_id: str, thread_id: str) -> None:
    """Render a compact, source-truthful Role Market feed and local shortlist."""
    company_types = ["Public", "Private", "Startup", "Unknown"]
    employee_bands = ["1–10", "11–50", "51–200", "201–500", "501–1,000", "1,001–5,000", "5,001+", "Unknown"]
    funding_stages = ["Pre-seed", "Seed", "Series A", "Series B", "Series C+", "Not applicable", "Unknown"]
    sources = sorted({item.source for match in run.matches for item in match.opening.provenance})
    filters = st.columns(4)
    with filters[0]:
        selected_types = st.multiselect("Company type", company_types, key=f"role-filter-type:{thread_id}")
    with filters[1]:
        selected_sizes = st.multiselect("Company size", employee_bands, key=f"role-filter-size:{thread_id}")
    with filters[2]:
        selected_stages = st.multiselect("Funding stage", funding_stages, key=f"role-filter-stage:{thread_id}")
    with filters[3]:
        selected_sources = st.multiselect("Source", sources, key=f"role-filter-source:{thread_id}")
    st.caption("Company type, size, and funding stage appear only when a dated company source exists. Leave a filter empty to include all values; select Unknown to include records without sourced facts.")

    filtered_query = run.query.model_copy(
        update={
            "company_types": tuple(selected_types),
            "employee_bands": tuple(selected_sizes),
            "funding_stages": tuple(selected_stages),
            "sources": tuple(selected_sources),
        }
    )
    matches = [match for match in run.matches if opening_matches_filters(match.opening, filtered_query)]
    search, period, order = st.columns((3, 2, 2))
    with search:
        search_text = st.text_input(
            "Search these official openings",
            placeholder="Company, title, location, or source",
            key=f"role-filter-search:{thread_id}",
        ).strip().casefold()
    with period:
        period_choice = st.selectbox(
            "Period",
            list(PERIOD_CHOICES),
            key=f"role-filter-period:{thread_id}",
            help="Matches only the employer's stated wording (e.g. “Summer 2026 internship”). Openings without period wording are excluded while a period is set.",
        )
        specific_period = ""
        if period_choice == "Specific period…":
            specific_period = st.text_input(
                "Specific period",
                placeholder="Summer 2026, 2027, Q3…",
                max_chars=100,
                key=f"role-filter-period-specific:{thread_id}",
            )
    with order:
        sort_order = st.selectbox(
            "Order by",
            ["Role relevance", "Source timestamp", "Company A–Z"],
            key=f"role-filter-order:{thread_id}",
        )
    if period_choice != "Any time":
        matches = [
            match for match in matches
            if opening_matches_period(
                match.opening,
                season="" if period_choice == "Specific period…" else period_choice,
                specific=specific_period if period_choice == "Specific period…" else "",
            )
        ]
    if search_text:
        matches = [
            match
            for match in matches
            if search_text in " ".join(
                (
                    match.opening.title,
                    match.opening.company.name,
                    match.opening.location or "",
                    " ".join(opening_sources(match.opening)),
                )
            ).casefold()
        ]
    if sort_order == "Source timestamp":
        matches.sort(
            key=lambda match: (
                bool(match.opening.source_timestamp),
                match.opening.source_timestamp or "",
                match.opening.company.name.casefold(),
                match.opening.title.casefold(),
            ),
            reverse=True,
        )
    elif sort_order == "Company A–Z":
        matches.sort(
            key=lambda match: (
                match.opening.company.name.casefold(),
                match.opening.title.casefold(),
                match.opening.canonical_url or "",
            )
        )

    state_store = _role_market_state_store()
    states = state_store.list_states(career_track_id, thread_id)
    state_by_opening_key = {state.opening_key: state for state in states}
    visible_matches: list = []
    for match in matches:
        state = _role_market_state_for(match.opening, state_by_opening_key)
        if state is None or state.status is not RoleMarketStatus.HIDDEN:
            visible_matches.append(match)

    summary = st.columns(3)
    summary[0].metric("Visible openings", len(visible_matches))
    summary[1].metric("Companies", len({match.opening.company.name for match in visible_matches}))
    summary[2].metric(
        "Saved / tracking",
        sum(state.status is not RoleMarketStatus.HIDDEN for state in states),
    )
    st.markdown(
        "<div class=\"role-market-note\">"
        "<strong>Role relevance</strong> combines the role family with optional local CV-skill overlap. "
        "It is not a prediction of eligibility, interview odds, or hiring likelihood. "
        "Availability can change; verify every role on its official listing."
        "</div>",
        unsafe_allow_html=True,
    )
    st.checkbox(
        "Load remote company logos", key="remote-logos-opt-in",
        help="Off by default: loading a remote image shares your IP address with its host.",
    )
    if run.errors:
        st.warning("Some registered feeds could not be refreshed: " + " · ".join(run.errors))
    with st.expander("Refresh audit", expanded=False):
        st.dataframe([source.model_dump() for source in run.sources], hide_index=True, use_container_width=True)

    _role_market_shortlist(career_track_id, thread_id, states)

    if not visible_matches:
        if matches:
            st.info("Every matching opening is hidden in your local shortlist. Restore one below to show it in the feed.")
        else:
            st.info("No stored openings match these filters. Clear a filter, search more broadly, or refresh a wider role family.")
        return
    visible_limit = len(visible_matches)
    if len(visible_matches) > 12:
        visible_limit = st.selectbox(
            "Show in feed",
            [12, 24, 48],
            key=f"role-feed-limit:{thread_id}",
        )
        st.caption(
            f"Showing the top {min(visible_limit, len(visible_matches))} of {len(visible_matches)} matching openings. "
            "Use search or filters to narrow the board."
        )
    for match in visible_matches[:visible_limit]:
        _role_match_card(
            match,
            career_track_id,
            thread_id,
            _role_market_state_for(match.opening, state_by_opening_key),
        )
    _role_location_map(visible_matches, thread_id)


def _refresh_role_market(
    workspace_id: str,
    thread_id: str,
    *,
    role_title: str,
    aliases: str,
    profile_skills: tuple[str, ...],
    enabled_sources: tuple[str, ...],
    boards=None,
) -> None:
    """Fetch only registered official boards, then save transparent local matches."""
    alias_terms = tuple(item.strip() for item in aliases.split(",") if item.strip()) or suggest_role_aliases(role_title)
    query = RoleQuery(title=role_title, aliases=alias_terms, profile_skills=profile_skills)
    openings: list[DiscoveredOpening] = []
    snapshots: list[SourceSnapshot] = []
    errors: list[str] = []
    retrieved_at = datetime.now(UTC).isoformat()
    for board in (DEFAULT_VETTED_COMPANY_BOARDS if boards is None else boards):
        if board.source not in enabled_sources:
            continue
        try:
            raw_openings = fetch_public_board_openings(
                board.source,
                board.board_identifier,
                company=board.company.name,
            )
            # Shared mapping with the scheduled role-market refresh; timestamp
            # fallbacks intentionally do not guess created/published/updated.
            openings.extend(openings_from_board(raw_openings, board, retrieved_at=retrieved_at))
            snapshots.append(SourceSnapshot(
                source=f"{board.company.name} · {board.source}",
                identifier=board.board_identifier,
                opening_count=len(raw_openings),
            ))
        except Exception as exc:
            message = f"{board.company.name} · {board.source}: {str(exc)[:280]}"
            errors.append(message)
            snapshots.append(SourceSnapshot(
                source=f"{board.company.name} · {board.source}",
                identifier=board.board_identifier,
                error=str(exc)[:280],
            ))
    all_attempts_failed = bool(snapshots) and all(snapshot.error for snapshot in snapshots)
    if all_attempts_failed:
        previous = ROLE_DISCOVERY.latest_run(career_track_id=workspace_id, workspace_id=thread_id)
        retained = "The last successful opportunity board is still shown." if previous else "No opportunity board has been saved yet."
        st.session_state[f"role-market-refresh-notice:{thread_id}"] = (
            "No registered feed could be refreshed. " + retained + " " + " · ".join(errors)
        )
        STORE.record_event(
            "role_discovery_refresh_failed",
            {
                "role_title": query.title,
                "source_count": len(snapshots),
                "error_count": len(errors),
            },
        )
        return

    st.session_state.pop(f"role-market-refresh-notice:{thread_id}", None)
    matches = rank_openings(query, openings)
    ROLE_DISCOVERY.save_latest_run(
        career_track_id=workspace_id,
        workspace_id=thread_id,
        query=query,
        matches=matches,
        sources=tuple(snapshots),
        errors=tuple(errors),
    )
    STORE.record_event(
        "role_discovery_refresh",
        {
            "role_title": query.title,
            "source_count": len(snapshots),
            "opening_count": len(openings),
            "match_count": len(matches),
            "error_count": len(errors),
        },
    )


def _role_card_key(opening: DiscoveredOpening) -> str:
    """Create a stable widget suffix without falling back to a saved identity."""

    try:
        value = opening_key(opening)
    except ValueError:
        # This is only a widget key.  The local shortlist remains unavailable
        # when an official source does not provide a durable opening identity.
        value = "|".join((
            opening.source,
            opening.source_identifier or "",
            opening.external_id or "",
            opening.source_url or "",
            opening.title,
            opening.company.name,
        ))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _company_monogram(name: str) -> str:
    """Return a local, privacy-preserving fallback company mark."""

    words = [
        "".join(character for character in word if character.isalnum())
        for word in name.split()
    ]
    words = [word for word in words if word]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return f"{words[0][0]}{words[1][0]}".upper()


def _remote_logos_allowed() -> bool:
    """Remote images load only after an explicit, per-session opt-in.

    Loading a remote logo shares the browser's IP address with the logo host,
    so role pages and the product home render local monograms until the user
    ticks the checkbox on that page.
    """
    try:
        return bool(st.session_state.get("remote-logos-opt-in", False))
    except Exception:
        return False


def _company_mark_markup(company_name: str) -> str:
    """Render a managed image mark above a resilient local monogram fallback."""

    logo_url = _company_brand_store().logo_for(company_name) if _remote_logos_allowed() else None
    try:
        logo_url = validate_public_https_logo_url(logo_url)
    except ValueError:
        # Stored mappings are validated on write. This guard also protects a
        # future catalog edit from becoming an unsafe HTML attribute.
        logo_url = None
    image = (
        f'<img src="{escape(logo_url, quote=True)}" alt="{escape(company_name, quote=True)} logo" '
        'loading="lazy" referrerpolicy="no-referrer">'
        if logo_url
        else ""
    )
    return (
        f'<div class="role-feed-avatar" aria-label="{escape(company_name, quote=True)}">'
        f'<span class="role-feed-monogram" aria-hidden="true">{escape(_company_monogram(company_name))}</span>'
        f"{image}</div>"
    )


def _source_timestamp_label(opening: DiscoveredOpening) -> str | None:
    """Present only the timestamp semantics that the official source supplied."""

    if not opening.source_timestamp:
        return None
    labels = {
        "published": "Published at source",
        "created": "Created at source",
        "updated": "Updated at source",
    }
    label = labels.get(opening.source_timestamp_kind or "", "Source timestamp")
    try:
        timestamp = datetime.fromisoformat(opening.source_timestamp.replace("Z", "+00:00"))
        value = timestamp.strftime("%d %b %Y").lstrip("0")
    except ValueError:
        value = opening.source_timestamp
    return f"{label} · {value}"


def _role_market_state_for(
    opening: DiscoveredOpening,
    states_by_opening_key: dict[str, RoleMarketState],
) -> RoleMarketState | None:
    """Find a local state only when the listing has a source-owned identity."""

    try:
        return states_by_opening_key.get(opening_key(opening))
    except ValueError:
        return None


def _role_match_card(
    match,
    career_track_id: str,
    thread_id: str,
    state: RoleMarketState | None,
) -> None:
    """Render a compact official-opening card with local, non-submission actions."""

    opening = match.opening
    card_key = _role_card_key(opening)
    sources = opening_sources(opening)
    source_label = " / ".join(sources) if sources else opening.source
    # ``role_locations`` excludes pure work-arrangement labels (for example,
    # a provider placing "Hybrid" in its location field), so they never become
    # a world-map pin or a claim about a company base.
    location = " · ".join(match.role_locations) if match.role_locations else "Location not listed"
    metadata = [location]
    if opening.workplace_type:
        metadata.append(opening.workplace_type)
    elif opening.location and not match.role_locations:
        metadata.append(opening.location)
    if opening.employment_type:
        metadata.append(opening.employment_type)
    timestamp_label = _source_timestamp_label(opening)
    if timestamp_label:
        metadata.append(timestamp_label)
    metadata_html = "".join(
        f'<span class="role-feed-pill">{escape(item)}</span>'
        for item in metadata
    )
    metadata_html += f'<span class="role-feed-pill source">Official {escape(source_label)} listing</span>'
    if state and state.status is not RoleMarketStatus.HIDDEN:
        metadata_html += (
            f'<span class="role-feed-pill state">{escape(state.status.label)} locally</span>'
        )

    reasons = []
    if match.matched_title_terms:
        reasons.append("role family: " + ", ".join(match.matched_title_terms))
    if match.matched_profile_skills:
        reasons.append("local profile overlap: " + ", ".join(match.matched_profile_skills))
    reason_text = "; ".join(reasons) if reasons else "matching role-title terms"

    with st.container(border=True):
        avatar, summary, relevance = st.columns((0.72, 5.7, 1.25))
        with avatar:
            st.markdown(
                _company_mark_markup(opening.company.name),
                unsafe_allow_html=True,
            )
        with summary:
            st.markdown(
                f'<div class="role-feed-title">{escape(opening.title)}</div>'
                f'<div class="role-feed-company">{escape(opening.company.name)}</div>'
                f'<div class="role-feed-meta">{metadata_html}</div>'
                f'<p class="role-feed-reason"><strong>Why it appears:</strong> {escape(reason_text)}.</p>',
                unsafe_allow_html=True,
            )
        with relevance:
            st.markdown(
                f'<div class="role-feed-relevance"><b>{match.score}</b><span>role relevance</span></div>',
                unsafe_allow_html=True,
            )

        actions = st.columns((1.35, 1.35, 1))
        with actions[0]:
            if opening.source_url:
                st.link_button(
                    "Open official application",
                    opening.source_url,
                    type="primary",
                    key=f"role-listing:{thread_id}:{card_key}",
                )
            else:
                st.caption("Official listing URL unavailable")
        with actions[1]:
            _open_discovered_job_workspace(
                match,
                career_track_id,
                key=f"prepare-role-match:{thread_id}:{card_key}",
            )
        with actions[2]:
            _role_market_primary_action(
                career_track_id,
                thread_id,
                opening,
                state,
                key=f"role-state:{thread_id}:{card_key}",
                relevance=match.score,
            )

        with st.expander("Role details & sources", expanded=False):
            st.caption(
                "This is a public-board observation. The app does not submit an application, "
                "contact people, or infer hiring activity."
            )
            if opening.description:
                st.write(opening.description[:2_000])
                if len(opening.description) > 2_000:
                    st.caption("Description excerpt shown. Use the official listing for the full text.")
            else:
                st.caption("No description was supplied by this source response.")
            facts = opening.company
            st.caption(
                f"Company facts: {facts.company_type} · {facts.employee_band} employees · {facts.funding_stage}."
            )
            if facts.facts_source_url:
                st.link_button(
                    "Open company-facts source",
                    facts.facts_source_url,
                    type="secondary",
                    key=f"role-facts:{thread_id}:{card_key}",
                )
            _role_source_observations(opening)
            _role_market_secondary_actions(
                career_track_id,
                thread_id,
                opening,
                state,
                key=f"role-secondary:{thread_id}:{card_key}",
            )


def _role_source_observations(opening: DiscoveredOpening) -> None:
    """Keep provider-specific timestamp semantics visible after source merges."""

    rows = []
    for source in opening.provenance:
        timestamp_label = _source_timestamp_label(
            opening.model_copy(
                update={
                    "source_timestamp": source.source_timestamp,
                    "source_timestamp_kind": source.source_timestamp_kind,
                }
            )
        )
        rows.append({
            "Source": source.source,
            "Board": source.source_identifier or "Not supplied",
            "Workplace": source.workplace_type or "Not supplied",
            "Employment": source.employment_type or "Not supplied",
            "Timestamp": timestamp_label or "Not supplied",
            "Retrieved": source.retrieved_at or "Not supplied",
        })
    if rows:
        st.caption("Official source observations retained for this listing")
        st.dataframe(rows, hide_index=True, use_container_width=True)


def _role_market_primary_action(
    career_track_id: str,
    thread_id: str,
    opening: DiscoveredOpening,
    state: RoleMarketState | None,
    *,
    key: str,
    relevance: int | None = None,
) -> None:
    """Offer a shortlist choice without claiming an application was made."""

    try:
        opening_key(opening)
    except ValueError:
        st.caption("Save unavailable: the source did not provide a durable listing ID.")
        return
    store = _role_market_state_store()
    if state is None:
        if st.button("Save for review", key=key):
            _application_store().save(career_track_id, thread_id, opening, relevance=relevance)
            store.set_status(career_track_id, thread_id, opening, RoleMarketStatus.SAVED)
            st.session_state["tracker-notice"] = f"Saved {opening.company.name} to My applications."
            st.rerun()
    elif state.status is RoleMarketStatus.SAVED:
        if st.button("Start tracking", key=key):
            _application_store().save(career_track_id, thread_id, opening, relevance=relevance)
            store.set_status(career_track_id, thread_id, opening, RoleMarketStatus.TRACKING)
            _navigate(view="applications")
    else:
        if st.button("Keep saved", key=key):
            store.set_status(career_track_id, thread_id, opening, RoleMarketStatus.SAVED)
            st.rerun()


def _role_market_secondary_actions(
    career_track_id: str,
    thread_id: str,
    opening: DiscoveredOpening,
    state: RoleMarketState | None,
    *,
    key: str,
) -> None:
    """Allow candidates to edit local viewing choices; never mark an application."""

    try:
        opening_key(opening)
    except ValueError:
        return
    store = _role_market_state_store()
    actions = st.columns(2)
    with actions[0]:
        if state is not None and st.button("Remove local status", key=f"{key}:remove"):
            store.clear_status(career_track_id, thread_id, opening)
            st.rerun()
    with actions[1]:
        if st.button("Hide from this feed", key=f"{key}:hide"):
            store.set_status(career_track_id, thread_id, opening, RoleMarketStatus.HIDDEN)
            st.rerun()


def _role_market_shortlist(
    career_track_id: str,
    thread_id: str,
    states: list[RoleMarketState],
) -> None:
    """Expose saved/hidden source snapshots even if a later refresh drops them."""

    with st.expander("Your local shortlist", expanded=False):
        st.caption(
            "Saved, tracking, and hidden are local viewing choices. They do not mean an application "
            "was submitted or a company was contacted. Manage your progress in My applications. "
            "Hiding or removing a feed status keeps your application history."
        )
        if not states:
            st.caption("Save an official opening to keep its source snapshot here.")
            return
        store = _role_market_state_store()
        for state in states:
            opening = state.opening
            state_key = _role_card_key(opening)
            info, action = st.columns((4, 1))
            with info:
                st.text(
                    f"{opening.title} · {opening.company.name}\n"
                    f"{state.status.label} locally · {opening.location or 'Location not listed'}"
                )
            with action:
                label = "Unhide" if state.status is RoleMarketStatus.HIDDEN else "Remove"
                if st.button(label, key=f"shortlist:{thread_id}:{state_key}:{label.casefold()}"):
                    store.clear_status(career_track_id, thread_id, opening)
                    st.rerun()


def _prepared_discovered_workspace(career_track_id: str, opening: DiscoveredOpening) -> str | None:
    """Find an existing preparation workspace only through the official URL."""

    canonical_url = opening.canonical_url
    if not canonical_url:
        return None
    for workspace_thread in WORKSPACES.list_threads(career_track_id):
        if canonicalize_url(workspace_thread["draft"].get("job_url")) == canonical_url:
            return workspace_thread["id"]
    return None


def _my_applications(career_track_id: str) -> None:
    tracker = _application_store()
    tracker.import_shortlist(career_track_id)
    track = next(track for track in WORKSPACES.list_workspaces() if track["id"] == career_track_id)
    render_application_tracker(
        tracker,
        career_track_id,
        track_name=track["name"],
        thread_names={thread["id"]: thread["name"] for thread in WORKSPACES.list_threads(career_track_id)},
        logo_markup=_company_mark_markup,
        on_browse=lambda: _navigate(focus="Role market"),
        on_prepare=lambda record: _enter_preparation_workspace(career_track_id, record.opening),
        on_open=lambda record: _open_application(career_track_id, record.id),
    )


def _open_application(career_track_id: str, application_id: str) -> None:
    """Deep-link to an application inside its own career track.

    The application route resolves records within the selected track, so the
    owning track must be selected before navigation; otherwise a fresh session
    would open the first track and report the record as unavailable.
    """
    st.session_state["pending_workspace"] = career_track_id
    _hub_go("application", application=application_id)


def _enter_preparation_workspace(career_track_id: str, opening: DiscoveredOpening) -> None:
    """Reuse the official listing's preparation space when entering from tracking."""
    prepared_thread_id = _prepared_discovered_workspace(career_track_id, opening)
    if not prepared_thread_id:
        prepared_thread_id = _create_discovered_job_workspace(career_track_id, opening)
    st.session_state[f"pending_thread:{career_track_id}"] = prepared_thread_id
    _navigate(focus="Job brief")


def _create_discovered_job_workspace(career_track_id: str, opening: DiscoveredOpening) -> str:
    context = []
    if opening.location:
        context.append(f"Listing location: {opening.location}")
    if opening.workplace_type:
        context.append(f"Listing workplace type: {opening.workplace_type}")
    if opening.employment_type:
        context.append(f"Listing employment type: {opening.employment_type}")
    job_text = "\n".join((*context, "", opening.description or "")).strip()
    draft = {
        **WORKSPACES.shared_profile(),
        "job_title": opening.title,
        "company": opening.company.name,
        "job_url": opening.source_url or "",
        "job_text": job_text,
    }
    return WORKSPACES.create_thread(career_track_id, f"{opening.title} · {opening.company.name}"[:100], draft)


def _open_discovered_job_workspace(match, career_track_id: str, key: str) -> None:
    """Open or create a normal local preparation workspace for one official opening."""

    opening = match.opening
    if existing := _prepared_discovered_workspace(career_track_id, opening):
        if st.button("Open preparation workspace", key=key):
            st.session_state[f"pending_thread:{career_track_id}"] = existing
            st.rerun()
        return
    if st.button("Prepare this application", key=key):
        prepared_thread_id = _create_discovered_job_workspace(career_track_id, opening)
        st.session_state[f"pending_thread:{career_track_id}"] = prepared_thread_id
        st.rerun()


# A deliberately conservative coordinate lookup for the local map.  We only
# pin unambiguous, country/region-qualified listing locations; an unmatched
# string remains visible in the source list rather than being guessed from a
# company HQ or a same-named city elsewhere in the world.
_ROLE_LOCATION_COORDINATES = {
    "amsterdam, netherlands": (52.3676, 4.9041),
    "austin, tx": (30.2672, -97.7431),
    "austin, texas": (30.2672, -97.7431),
    "bengaluru, india": (12.9716, 77.5946),
    "berlin, germany": (52.5200, 13.4050),
    "dublin, ireland": (53.3498, -6.2603),
    "london, england": (51.5072, -0.1276),
    "london, gb": (51.5072, -0.1276),
    "london, uk": (51.5072, -0.1276),
    "london, united kingdom": (51.5072, -0.1276),
    "mountain view, ca": (37.3861, -122.0839),
    "mountain view, california": (37.3861, -122.0839),
    "new york, ny": (40.7128, -74.0060),
    "new york, new york": (40.7128, -74.0060),
    "new york, us": (40.7128, -74.0060),
    "new york, united states": (40.7128, -74.0060),
    "palo alto, ca": (37.4419, -122.1430),
    "palo alto, california": (37.4419, -122.1430),
    "palo alto, us": (37.4419, -122.1430),
    "palo alto, united states": (37.4419, -122.1430),
    "madrid, es": (40.4168, -3.7038),
    "madrid, spain": (40.4168, -3.7038),
    "paris, france": (48.8566, 2.3522),
    "paris, fr": (48.8566, 2.3522),
    "san francisco, ca": (37.7749, -122.4194),
    "san francisco, california": (37.7749, -122.4194),
    "san francisco, us": (37.7749, -122.4194),
    "san francisco, united states": (37.7749, -122.4194),
    "seattle, wa": (47.6062, -122.3321),
    "seattle, washington": (47.6062, -122.3321),
    "singapore, singapore": (1.3521, 103.8198),
    "toronto, ontario": (43.6532, -79.3832),
    "toronto, canada": (43.6532, -79.3832),
    "zurich, switzerland": (47.3769, 8.5417),
    "zurich, ch": (47.3769, 8.5417),
}


def _role_location_segments(location: str) -> tuple[str, ...]:
    """Split only explicit multi-location separators from a source listing."""
    normalized = location.replace("\n", " • ").replace(";", " • ").replace("|", " • ")
    return tuple(segment.strip(" ,") for segment in normalized.split("•") if segment.strip(" ,"))


def _coordinates_for_role_location(location: str) -> tuple[float, float] | None:
    normalized = " ".join(location.casefold().split())
    return _ROLE_LOCATION_COORDINATES.get(normalized)


def _coordinate_points_for_role_location(location: str) -> tuple[tuple[str, tuple[float, float]], ...]:
    """Return every unambiguous city included in a source-listed location."""
    return tuple(
        (segment, coordinates)
        for segment in _role_location_segments(location)
        if (coordinates := _coordinates_for_role_location(segment))
    )


def _role_location_map(matches, thread_id: str) -> None:
    """Map only listing-stated locations—never company HQs as a proxy for a role."""
    companies = sorted({match.opening.company.name for match in matches}, key=str.casefold)
    if not companies:
        return
    selected_company = st.selectbox(
        "Inspect a company's role locations",
        companies,
        key=f"role-location-company:{thread_id}",
    )
    selected = [match for match in matches if match.opening.company.name == selected_company]
    by_location: dict[str, list] = {}
    for match in selected:
        for location in match.role_locations:
            by_location.setdefault(location, []).append(match)
    st.markdown(f"### {selected_company} role locations")
    st.caption("These pins come only from the locations listed on matching job openings. They are not headquarters or general company-footprint claims.")
    points_by_location: dict[str, dict] = {}
    for location, location_matches in by_location.items():
        for map_location, coordinates in _coordinate_points_for_role_location(location):
            latitude, longitude = coordinates
            point = points_by_location.setdefault(map_location, {
                "location": map_location,
                "roles": [],
                "latitude": latitude,
                "longitude": longitude,
                "count": 0,
            })
            point["roles"].extend(match.opening.title for match in location_matches)
            point["count"] += len(location_matches)
    points = [
        {
            **point,
            "roles": " · ".join(dict.fromkeys(point["roles"])),
            "radius": point["count"] * 45_000,
        }
        for point in points_by_location.values()
    ]
    if points:
        layer = pdk.Layer(
            "ScatterplotLayer",
            id=f"role-location-markers:{thread_id}",
            data=points,
            get_position=["longitude", "latitude"],
            get_radius="radius",
            get_fill_color=[210, 130, 75, 205],
            radius_min_pixels=8,
            radius_max_pixels=19,
            pickable=True,
            auto_highlight=True,
        )
        latitude = sum(point["latitude"] for point in points) / len(points)
        longitude = sum(point["longitude"] for point in points) / len(points)
        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=pdk.ViewState(latitude=latitude, longitude=longitude, zoom=3.2 if len(points) == 1 else 1.3, pitch=0),
            map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
            tooltip={
                "html": "<b>{location}</b><br/>{roles}",
                "style": {"backgroundColor": "#1F1B16", "color": "#FFFAF3"},
            },
        )
        st.pydeck_chart(deck, use_container_width=True, height=330, key=f"role-location-map:{thread_id}")
    elif by_location:
        st.info("Matching openings list locations, but this local map has no unambiguous coordinate match for them yet. The locations are shown below without a pin.")
    else:
        st.info("The matching openings did not state a location. The app will not replace it with a company HQ.")
    for location, location_matches in by_location.items():
        st.markdown(f"- **{location}** · " + "; ".join(match.opening.title for match in location_matches))


def _permitted_sources() -> None:
    """Keep custom source reads and imports available without crowding role discovery."""
    st.subheader("Bring a lawful source")
    st.caption("Use an official employer board you know, an authorized employer integration, or a job export you obtained lawfully. These are separate from the small registered-feed role market.")
    source, identifier = st.columns(2)
    with source:
        source_kind = st.selectbox("Public source", ["Greenhouse", "Lever", "Recruitee"])
    with identifier:
        token = st.text_input("Board identifier", help="Greenhouse board token, Lever site handle, or Recruitee company slug.")
    if st.button("Fetch this official company board"):
        try:
            if source_kind == "Greenhouse":
                jobs = fetch_greenhouse_jobs(token)
            elif source_kind == "Lever":
                jobs = fetch_lever_jobs(token)
            else:
                jobs = fetch_recruitee_jobs(token)
            new_jobs = MONITOR.refresh(source=source_kind, identifier=token, jobs=jobs)
            st.session_state["source_jobs"] = jobs
            st.session_state["new_source_jobs"] = new_jobs
            STORE.record_event("public_job_fetch", {"source": source_kind, "identifier": token, "count": len(jobs), "new_count": len(new_jobs)})
        except Exception as exc:
            st.error(str(exc))
    if "new_source_jobs" in st.session_state:
        st.info(f"{len(st.session_state['new_source_jobs'])} newly observed job(s) on the latest user-triggered refresh.")
    for index, job in enumerate(st.session_state.get("source_jobs", [])[:30]):
        st.markdown(f"- **{job.title}** · {job.company} · {job.location or 'Location not listed'}" + (f" · [Official page]({job.url})" if job.url else ""))
        _open_job_thread(job, f"open-source:{index}")

    with st.expander("Authorized employer integration", expanded=False):
        st.caption("Use SmartRecruiters only when the employer has given you a permitted Posting API token. Tokens are used for this request only and are never stored.")
        smart_company = st.text_input("SmartRecruiters company identifier")
        smart_token = st.text_input("SmartRecruiters Posting API token", type="password")
        if st.button("Fetch SmartRecruiters postings through the official API"):
            try:
                smart_jobs = fetch_smartrecruiters_postings(smart_company, smart_token)
                new_smart_jobs = MONITOR.refresh(source="SmartRecruiters", identifier=smart_company, jobs=smart_jobs)
                st.session_state["smart_jobs"] = smart_jobs
                st.success(f"Fetched {len(smart_jobs)} role(s), including {len(new_smart_jobs)} newly observed.")
                STORE.record_event("smartrecruiters_official_fetch", {"identifier": smart_company, "count": len(smart_jobs), "new_count": len(new_smart_jobs)})
            except Exception as exc:
                st.error(str(exc))
        for index, job in enumerate(st.session_state.get("smart_jobs", [])[:20]):
            st.markdown(f"- **{job.title}** · {job.company}" + (f" · [Official page]({job.url})" if job.url else ""))
            _open_job_thread(job, f"open-smart:{index}")

    st.markdown("#### Import a licensed or user-provided job export")
    st.caption("Upload CSV or JSON you personally exported or obtained with permission. Up to 500 records/5 MB; imported facts remain reviewable.")
    job_export = st.file_uploader("Job export (.csv or .json)", type=["csv", "json"], key="job_export")
    if job_export and st.button("Import job export"):
        try:
            jobs = import_job_export(job_export.getvalue(), job_export.name)
            st.session_state["imported_jobs"] = jobs
            STORE.record_event("job_export_import", {"filename": job_export.name, "count": len(jobs)})
            st.success(f"Imported {len(jobs)} evidence-ready job records.")
        except Exception as exc:
            st.error(str(exc))
    for index, job in enumerate(st.session_state.get("imported_jobs", [])[:20]):
        st.markdown(f"- **{job.title}** · {job.company}" + (f" · [Source]({job.url})" if job.url else ""))
        _open_job_thread(job, f"open-import:{index}")

    with st.expander("Local monitoring registry"):
        st.caption("Monitoring is user-triggered only. Source identifiers are retained locally; credentials are never stored.")
        watches = MONITOR.watches()
        if watches:
            st.dataframe(watches, use_container_width=True, hide_index=True)
        else:
            st.write("No source has been refreshed yet.")


def _company_explorer(workspace_id: str, thread_id: str) -> None:
    """Show transparent, profile-derived companies on an accessible world map."""
    thread = WORKSPACES.thread(workspace_id, thread_id)
    profile = thread["draft"]
    profile_source = "this Job Workspace"
    if not profile["cv_text"].strip():
        shared = WORKSPACES.shared_profile()
        if shared["cv_text"].strip():
            profile = shared
            profile_source = "your saved shared profile"

    st.subheader("Profile company explorer")
    st.caption("A small, curated world map of companies worth researching from skills detected in your CV. These are not live openings, hiring predictions, or a claim that every pin is a headquarters.")
    if not profile["cv_text"].strip():
        st.info("Add your CV in Job brief first. We will also ask for GitHub and/or a portfolio there when you have them; links are optional and no profile is fetched automatically.")
        return

    links = {field: profile[field] for field in PROFILE_FIELDS if field != "cv_text" and profile[field].strip()}
    skills = detected_profile_skills(profile["cv_text"], links)
    if not skills:
        st.warning("No skills from the local profile vocabulary were detected yet. Add a clear `Skills: Python, SQL, …` line to your CV in Job brief, then return here.")
        return

    st.caption(f"Using {profile_source}. Detected profile skills: {' · '.join(skills[:12])}" + (f" · +{len(skills) - 12} more" if len(skills) > 12 else ""))
    regions = sorted({pin.region for pin in COMPANY_PINS})
    selected_regions = st.multiselect(
        "Explore regions",
        regions,
        default=regions,
        key=f"explorer-regions:{thread_id}",
        help="Only the displayed catalogue pins are filtered. This does not imply immigration eligibility, remote-work availability, or an active role.",
    )
    recommendations = recommend_companies(
        profile["cv_text"],
        links=links,
        regions=tuple(selected_regions),
    )
    if not recommendations:
        st.info("No catalogue companies overlap with the selected profile skills in these regions. Try another region or add more explicit skills to your CV.")
        return

    map_rows = [
        {
            "company": item.company,
            "city": item.city,
            "country": item.country,
            "focus": item.focus,
            "matching_skills": ", ".join(item.matching_skills),
            "longitude": item.longitude,
            "latitude": item.latitude,
            "radius": 90_000 + (len(item.matching_skills) * 22_000),
        }
        for item in recommendations
    ]
    layer = pdk.Layer(
        "ScatterplotLayer",
        id=f"company-explorer-markers:{thread_id}",
        data=map_rows,
        get_position=["longitude", "latitude"],
        get_radius="radius",
        get_fill_color=[32, 80, 65, 190],
        radius_min_pixels=7,
        radius_max_pixels=20,
        pickable=True,
        auto_highlight=True,
    )
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=18, longitude=8, zoom=1.08, pitch=0),
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip={
            "html": "<b>{company}</b><br/>{city}, {country}<br/>{focus}<br/><br/>Profile overlap: {matching_skills}",
            "style": {"backgroundColor": "#1F1B16", "color": "#FFFAF3"},
        },
    )
    st.pydeck_chart(deck, use_container_width=True, height=480, key=f"company-explorer-map:{thread_id}")

    footprint_order = sorted(
        recommendations,
        key=lambda item: (-len(company_footprint(item.company)), -len(item.matching_skills), item.company.casefold()),
    )
    options = {f"{item.company} · {item.city}, {item.country}": item for item in footprint_order}
    selected_label = st.selectbox("Inspect a company's footprint", list(options), key=f"explorer-company:{thread_id}")
    selected = options[selected_label]
    with st.container(border=True):
        st.markdown(f"#### {selected.company} · {selected.city}, {selected.country}")
        st.write(selected.focus)
        st.write("Why it appears here: your profile overlaps with " + ", ".join(selected.matching_skills) + ".")
        st.caption("Review the company and current openings yourself. Skill overlap is only a research starting point, not evidence that a role fits, is open, or is accessible to you.")
        st.link_button(f"Open {selected.company} careers page", selected.careers_url, type="secondary")

    _company_footprint(selected, thread_id)

    st.markdown("**All visible companies**")
    st.dataframe(
        [
            {
                "Company": item.company,
                "Selected hub": f"{item.city}, {item.country}",
                "Focus": item.focus,
                "Profile overlap": ", ".join(item.matching_skills),
            }
            for item in recommendations
        ],
        hide_index=True,
        use_container_width=True,
    )


def _company_footprint(selected, thread_id: str) -> None:
    """Drill into one company's selected, source-linked locations."""
    hubs = company_footprint(selected.company)
    st.markdown(f"### {selected.company} footprint")
    st.caption("Selected source-linked locations, not a complete office directory or live-role map. A company can have one Global/Group HQ and several specialised hubs; a location is called an HQ only when the linked source supports that label.")
    if len(hubs) == 1:
        st.info("This first catalogue has one selected hub for this company. Add verified locations before treating it as a global footprint.")

    map_rows = [
        {
            "site_type": hub.site_type,
            "city": hub.city,
            "country": hub.country,
            "focus": hub.focus,
            "longitude": hub.longitude,
            "latitude": hub.latitude,
            "color": [32, 80, 65, 205] if "HQ" in hub.site_type else [210, 130, 75, 205],
        }
        for hub in hubs
    ]
    layer = pdk.Layer(
        "ScatterplotLayer",
        id=f"company-footprint-markers:{thread_id}",
        data=map_rows,
        get_position=["longitude", "latitude"],
        get_radius=115_000,
        get_fill_color="color",
        radius_min_pixels=8,
        radius_max_pixels=18,
        pickable=True,
        auto_highlight=True,
    )
    if len(hubs) == 1:
        latitude, longitude, zoom = hubs[0].latitude, hubs[0].longitude, 3.1
    else:
        latitude = sum(hub.latitude for hub in hubs) / len(hubs)
        longitude = sum(hub.longitude for hub in hubs) / len(hubs)
        zoom = 1.0
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=latitude, longitude=longitude, zoom=zoom, pitch=0),
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip={
            "html": "<b>{site_type}</b><br/>{city}, {country}<br/><br/>{focus}",
            "style": {"backgroundColor": "#1F1B16", "color": "#FFFAF3"},
        },
    )
    st.pydeck_chart(deck, use_container_width=True, height=360, key=f"company-footprint-map:{thread_id}")

    st.markdown("**What each selected site is publicly described as doing**")
    for index, hub in enumerate(hubs):
        with st.container(border=True):
            st.markdown(f"**{hub.site_type} · {hub.city}, {hub.country}**")
            st.write(hub.focus)
            source_note = f"Public source" + (f" ({hub.source_year})" if hub.source_year else "") + "."
            st.caption(source_note)
            if hub.verification_note:
                st.caption(hub.verification_note)
            st.link_button(
                f"Open source for {hub.city}",
                hub.source_url,
                type="secondary",
                key=f"footprint-source:{thread_id}:{selected.company}:{index}",
            )


def _interview(workspace_id: str, thread_id: str) -> None:
    """A saved, role-specific rehearsal area—not a generic one-off question form."""
    thread = WORKSPACES.thread(workspace_id, thread_id)
    result = thread["analysis"] if not thread["stale"] else None
    st.subheader("Interview lab")
    st.caption("Practice answers for this target role. Feedback checks answer structure, not factual or technical correctness; saved attempts stay in this job workspace.")
    if thread["stale"]:
        st.warning("Refresh the Job brief first. Interview questions are held back while the role evidence is stale.")
        return
    if not result:
        st.info("Analyze this job in Job brief to get evidence-aware, role-specific interview questions.")
        return
    attempts = WORKSPACES.interview_attempts(workspace_id, thread_id)
    level = difficulty_level(attempts)
    passed, needed = level_progress(attempts)
    level_cols = st.columns((1, 3))
    level_cols[0].metric("Difficulty", f"Lv {level}")
    level_cols[1].markdown(f"**{LEVEL_NAMES[level]}**  ")
    if level >= MAX_LEVEL:
        level_cols[1].caption("Maximum level reached: cross-examination. Keep defending your evidence.")
    else:
        level_cols[1].progress(passed / needed, text=f"{passed}/{needed} rehearsals scored 75+ toward level {level + 1} · questions get harder as you prove yourself")
    if attempts:
        average = round(sum(attempt["score"] for attempt in attempts) / len(attempts))
        history_metrics = st.columns(3)
        history_metrics[0].metric("Saved rehearsals", len(attempts))
        history_metrics[1].metric("Average practice evidence score", f"{average}/100")
        history_metrics[2].metric("Question areas covered", len({attempt["category"] for attempt in attempts}))
    else:
        st.info("Your first saved rehearsal will create a private practice history for this role.")
    questions = build_interview_questions(result.candidate, result.job, level=level)
    selected = st.selectbox("Question", questions, format_func=lambda question: f"{question.category.title()} · {question.question}", key=f"interview-question:{thread_id}")
    scope = f"{thread_id}:{selected.id}"
    st.write("A strong answer should include: " + "; ".join(selected.what_good_evidence_looks_like))
    answer = st.text_area("Your answer (type it, or transcribe an optional recording below)", height=160, key=f"interview-answer:{scope}")
    try:
        audio = st.audio_input("Record an answer (optional)", key=f"interview-audio:{scope}")
    except AttributeError:
        audio = None
        st.caption("Upgrade Streamlit to use in-app audio recording; typed answers work now.")
    if audio is not None:
        st.audio(audio)
        if st.button("Transcribe recording with OpenAI"):
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                st.error("Set OPENAI_API_KEY to use optional transcription. Audio is not sent otherwise.")
            else:
                try:
                    transcript = transcribe_openai_audio(audio.getvalue(), getattr(audio, "name", "answer.wav"), key)
                    st.session_state[f"interview-transcript:{scope}"] = transcript
                except Exception as exc:
                    st.error(f"Transcription failed: {exc}")
    if transcript := st.session_state.get(f"interview-transcript:{scope}"):
        transcript = st.text_area("Transcript", transcript, height=100, key=f"transcript-display:{scope}")
        answer = answer or transcript
    if st.button("Score and save this rehearsal", type="primary"):
        if not answer.strip():
            st.error("Write or transcribe an answer before saving this rehearsal.")
        else:
            feedback = evaluate_answer(selected, answer)
            try:
                WORKSPACES.save_interview_attempt(
                    workspace_id,
                    thread_id,
                    question_id=selected.id,
                    category=selected.category,
                    question=selected.question,
                    answer=answer,
                    score=feedback.score,
                    strengths=feedback.strengths,
                    missing=feedback.missing,
                )
                st.success("Rehearsal saved in this job workspace.")
                new_level = difficulty_level(WORKSPACES.interview_attempts(workspace_id, thread_id))
                if new_level > level:
                    st.balloons()
                    st.success(f"Level up! You reached level {new_level}: {LEVEL_NAMES[new_level]}. Questions just got harder.")
                st.metric("Practice evidence score", f"{feedback.score}/100", help="Checks answer structure, not technical correctness.")
                st.write("**Strengths:** " + (" ".join(feedback.strengths) or "Not enough evidence yet."))
                st.write("**Improve:** " + " ".join(feedback.missing))
                st.info("Follow-up: " + feedback.follow_up)
            except ValueError as exc:
                st.error(str(exc))

    if attempts:
        with st.expander("Saved practice history", expanded=False):
            for attempt in attempts[:12]:
                when = attempt["created_at"].split("T", 1)[0]
                st.markdown(f"**{attempt['category'].title()} · {attempt['score']}/100 · {when}**")
                st.caption(attempt["question"])
                st.write(attempt["answer"])
                if attempt["missing"]:
                    st.caption("Next improvement: " + " ".join(attempt["missing"]))


def _upload_text(uploaded) -> str:
    suffix = Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
        temporary.write(uploaded.getvalue())
        path = Path(temporary.name)
    try:
        return load_document(path)
    finally:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
