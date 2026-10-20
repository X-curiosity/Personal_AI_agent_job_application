"""Role-first, editorial career portal built on the existing preparation stores."""
from __future__ import annotations

from datetime import UTC, datetime
from html import escape
import os
import re

import streamlit as st

from tau_job_application.application_tracker import ApplicationStage
from tau_job_application.application_tracker_ui import tracker_today
from tau_job_application.career_hub import FIELDS, HubStore, Interests, contact_searches, draft_documents, infer_email, suggested_roles
from tau_job_application.career_inbox import InboxStore, read_gmail, read_slack
from tau_job_application.capital_atlas import fetch_capital_atlas
from tau_job_application.company_browser_ui import render_company_browser
from tau_job_application.company_catalog import fetch_companies_marketcap, fetch_yc_hiring
from tau_job_application.hiring_index import build_hiring_index
from tau_job_application.hiring_match import calculate_evidence_match
from tau_job_application.parsing import parse_candidate_text
from tau_job_application.pipeline import analyze_texts
from tau_job_application.role_discovery import (
    DEFAULT_VETTED_COMPANY_BOARDS,
    PERIOD_CHOICES,
    CompanyFacts,
    VettedCompanyBoard,
    opening_matches_period,
    suggest_role_aliases,
)
from tau_job_application.role_market_state import RoleMarketStatus, opening_key


PORTAL_BOARDS = (*DEFAULT_VETTED_COMPANY_BOARDS, VettedCompanyBoard(
    company=CompanyFacts(name="OpenAI"), source="Ashby", board_identifier="openai",
    board_url="https://jobs.ashbyhq.com/openai"))


def go(view, **params):
    st.query_params.clear()
    st.query_params.update({"view": view, **params})
    st.session_state.pop("topnav", None)
    st.rerun()


def render_onboarding(api, track, *, standalone=True):
    store = HubStore(api.WORKSPACES.path)
    saved = store.interests(track)
    st.markdown('<div class="section-kicker">A direction, not a box</div><h1>Where do you want to go?</h1>', unsafe_allow_html=True)
    st.write("Choose a few interests. We’ll turn them into role pages you can explore, prepare for, and track.")
    fields = st.multiselect("1 · Fields that interest you", list(FIELDS), default=saved.fields if saved else [], key=f"hub-fields:{track}")
    options = [sub for field in fields for sub in FIELDS[field]]
    subfields = st.multiselect("2 · Go a little deeper", options, default=[sub for sub in (saved.subfields if saved else []) if sub in options], key=f"hub-subfields:{track}")
    roles = suggested_roles(subfields)
    if saved:
        roles = sorted(set(roles + saved.roles))
    selected = st.multiselect("3 · Roles you would like to explore", roles, default=saved.roles if saved else [], key=f"hub-roles:{track}")
    custom = st.text_input("Or add your own roles (comma-separated)", max_chars=1000, placeholder="Hardware Engineer, Investment Associate", key=f"hub-custom:{track}")
    st.caption("These paths overlap. ML engineering can connect electrical engineering, CS, neuroscience, economics, and more. Your degree does not limit which roles you can explore. This is a starter catalogue, not an exhaustive list.")
    if st.button("Build my role pages", type="primary", key=f"hub-save:{track}"):
        try:
            interests = Interests(fields=fields, subfields=subfields, roles=selected + [role.strip() for role in custom.split(",") if role.strip()])
            store.save_interests(track, interests)
            go("career")
        except ValueError:
            st.error("Choose at least one role. Keep each role name under 100 characters and select no more than 20.")


def render_portal(api, track, view):
    st.markdown(_STYLE, unsafe_allow_html=True)
    store = HubStore(api.WORKSPACES.path)
    if view == "onboarding" or (view == "career" and not store.interests(track)):
        render_onboarding(api, track)
    elif view == "career":
        _home(api, store, track)
    elif view == "role":
        _role(api, store, track)
    elif view == "application":
        _application(api, store, track)
    elif view == "match":
        from tau_job_application.match_onboarding_ui import render_match_onboarding
        render_match_onboarding(api, track)
    elif view == "companies":
        _companies(api, track)


_SIGNAL_LABELS = {
    "live_openings": "✓ Live openings (official board)",
    "directory_flag": "Directory flag (unverified)",
}


def _hiring_index(api):
    """Internal actively-hiring index: live official boards + YC directory flags."""

    store = api._hiring_index_store()
    run = store.run()
    st.divider()
    st.subheader("Actively hiring index")
    st.caption(
        "Built from the local YC snapshot (Active + hiring flag, the data behind vclense-style YC globe views) "
        "and live checks against reviewed official job boards. LinkedIn is never scraped or automated: "
        "live rows read the same employer ATS postings LinkedIn mirrors, through the boards' official feeds."
    )
    header = st.columns((3, 1))
    header[0].caption(
        f"Built {str(run['built_at'])[:16].replace('T', ' ')} UTC · {run['entry_count']} companies · {run['live_count']} with live board checks"
        if run else "No hiring index yet."
    )
    if run:
        from datetime import UTC, datetime
        age_hours = (datetime.now(UTC) - datetime.fromisoformat(str(run["built_at"]))).total_seconds() / 3600
        if age_hours > 48:
            st.warning(f"The index is {int(age_hours)} hours old. It refreshes automatically every 6 hours when the schedule is installed (./install_schedule.sh), or rebuild it now.")
        else:
            st.caption(f"Freshness: {max(1, int(age_hours))}h old · auto-refreshes every 6h via the installed schedule (log: .job_assistant/refresh.log)")
    if header[1].button("Build / refresh index", use_container_width=True):
        if api._yc_directory_store().snapshot() is None:
            st.error("Refresh the startup snapshot on a role page first; the index is built from it.")
        else:
            with st.spinner("Building the index (live board checks are capped at 25 per build)…"):
                from tau_job_application.hiring_index import persist_index_build
                build = build_hiring_index(
                    yc_store=api._yc_directory_store(),
                    catalog_store=api._company_catalog_store(),
                    fetch_openings=api.fetch_public_board_openings,
                )
                indexed, outcome = persist_index_build(store, build)
            if build.errors:
                st.warning("Some boards could not be checked; they were skipped, not zeroed: " + " · ".join(build.errors))
            if outcome == "saved":
                live = sum(1 for entry in build.entries if entry.signal == "live_openings")
                st.success(f"Indexed {indexed} companies flagged as hiring ({live} verified against live boards).")
                st.rerun()
            else:
                st.info("The previous index was kept: no verified hiring entries could be built this time.")
    if run is None:
        st.info("Build the index once to list actively hiring companies. Live verification uses only reviewed board mappings and the vetted registry.")
        return

    controls = st.columns(4)
    signal = controls[0].selectbox(
        "Signal", ["All signals", "live_openings", "directory_flag"],
        format_func=lambda value: _SIGNAL_LABELS.get(value, value),
        key="hiring-index-signal",
    )
    industries = store.facets()["industries"]
    industry = controls[1].selectbox("Industry", ["All industries", *industries], key="hiring-index-industry")
    region = controls[2].text_input("Region contains", placeholder="Germany, USA, remote…", key="hiring-index-region")
    query = controls[3].text_input("Search", placeholder="company, role, industry", max_chars=200, key="hiring-index-query")

    entries = store.entries(
        signal="" if signal == "All signals" else signal,
        industry="" if industry == "All industries" else industry,
        region=region, query=query, limit=200,
    )
    st.caption(f"{len(entries)} companies listed")
    if not entries:
        st.info("No companies match these filters in the current index.")
        return
    st.dataframe(
        [
            {
                "Company": entry.name,
                "Signal": _SIGNAL_LABELS[entry.signal],
                "Openings": str(entry.openings_count) if entry.openings_count is not None else "",
                "Sample roles": " · ".join(entry.sample_titles[:3]),
                "Industry": entry.industry or "",
                "Batch": entry.yc_batch or "",
                "Source": entry.source_label,
            }
            for entry in entries
        ],
        hide_index=True, use_container_width=True,
    )
    st.caption("“Live openings” counts come from the company's reviewed official board at build time. “Directory flag” means the YC directory claims hiring; verify on the company's own careers page.")


def _portal_boards(api):
    """Combine built-in reviewed boards with user-reviewed catalogue mappings."""
    boards = [*PORTAL_BOARDS, *api._company_catalog_store().boards()]
    unique = {}
    for board in boards:
        unique[(board.source, board.board_identifier)] = board
    return tuple(unique.values())


def _companies(api, track=None):
    catalog = api._company_catalog_store()
    st.markdown('<div class="section-kicker">Source-aware discovery</div><h1>Your company database</h1>', unsafe_allow_html=True)
    st.write("Bring in a small, reviewable company set, then connect each employer’s official public hiring board. Directory records and job adverts remain separate.")
    st.caption("Imports are manual, capped at 100 records, and saved with their source. No company website is crawled and no personal contact data is collected.")

    from tau_job_application.company_map_ui import render_company_map
    render_company_map(api, track)

    with st.expander("Import companies", expanded=not bool(catalog.list_companies(limit=1))):
        limit = st.number_input("Companies per import", min_value=5, max_value=100, value=25, step=5)
        yc_query = st.text_input("Optional YC focus", placeholder="hardware, robotics, finance, AI")
        atlas_minimum = st.selectbox("Global Capital Atlas minimum value", [10, 25, 50, 100, 250, 500, 1000], index=0,
                                     format_func=lambda value: f"${value}B+" if value < 1000 else "$1T+")
        first, second, third = st.columns(3)
        if first.button("Import largest public companies", use_container_width=True):
            try:
                with st.spinner("Reading one public ranking page…"):
                    count = catalog.import_companies(fetch_companies_marketcap(limit=int(limit)))
                st.success(f"Saved {count} CompaniesMarketCap records with provenance.")
                st.rerun()
            except (RuntimeError, ValueError):
                st.error("The public-company source could not be refreshed. Nothing was replaced; try again later.")
        if second.button("Import hiring YC startups", use_container_width=True):
            try:
                with st.spinner("Reading the public YC hiring dataset…"):
                    companies = fetch_yc_hiring(limit=int(limit), query=yc_query)
                    if not companies:
                        raise ValueError("No matching YC companies")
                    count = catalog.import_companies(companies)
                st.success(f"Saved {count} hiring YC startup records with provenance.")
                st.rerun()
            except (RuntimeError, ValueError):
                st.error("No matching YC companies were imported. Try a broader focus or refresh later.")
        if third.button("Import Global Capital Atlas majors", use_container_width=True):
            try:
                with st.spinner("Reading the Global Capital Atlas page asset…"):
                    count = catalog.import_companies(fetch_capital_atlas(min_value_billions=int(atlas_minimum), limit=int(limit)))
                st.success(f"Saved {count} Global Capital Atlas records with provenance.")
                st.rerun()
            except (RuntimeError, ValueError):
                st.error("The Global Capital Atlas could not be refreshed. Nothing was replaced; try again later.")
        st.caption("YC Globe inspired this view. The import uses the smaller, inspectable yc-oss hiring JSON rather than reverse-engineering VCLense’s interactive dashboard. "
                   "Global Capital Atlas (capital.theojaffee.net) is read once per explicit import from its published page asset; a valuation is not a vacancy signal.")

    _hiring_index(api)

    controls = st.columns((2, 1, 1))
    query = controls[0].text_input("Search the database", placeholder="company, industry, place, ticker")
    source = controls[1].selectbox("Source", ["All", "CompaniesMarketCap", "YC community API", "Global Capital Atlas"])
    hiring = controls[2].checkbox("Hiring only")
    rows = catalog.list_companies(query=query, source=None if source == "All" else source, hiring_only=hiring)
    st.caption(f"{len(rows)} locally stored companies · listings are candidates until an official board is reviewed below")
    load_logos = st.checkbox("Load remote company logos", help="Off by default because loading a remote image shares your IP address with its host.")
    columns = st.columns(2)
    for index, row in enumerate(rows[:100]):
        company = row["company"]
        with columns[index % 2]:
            with st.container(border=True):
                header = st.columns((1, 5))
                if load_logos and company.logo_url:
                    header[0].image(company.logo_url, width=46)
                else:
                    header[0].markdown(f"**{escape(''.join(part[0] for part in company.name.split()[:2]).upper())}**")
                header[1].subheader(company.name)
                tags = [company.company_type, company.industry, company.country or company.locations,
                        company.market_cap, company.yc_batch, "Hiring" if company.hiring else None]
                st.caption(" · ".join(value for value in tags if value and value != "Unknown"))
                if company.summary:
                    st.write(company.summary)
                links = st.columns(2)
                links[0].link_button("View source", company.source_url, use_container_width=True)
                if company.website:
                    links[1].link_button("Company website", company.website, use_container_width=True)
                st.caption(f"{row['board_count']} reviewed job board(s) · imported {row['imported_at'][:10]}")

    st.divider()
    st.subheader("Connect an official company job board")
    st.write("Paste only the public board identifier from Greenhouse, Lever, or Ashby. We test the provider feed before saving it; future role refreshes then include its live positions.")
    if not rows:
        st.info("Import or find a company first.")
        return
    labels = {f"{row['company'].name} · {row['company'].source} · #{row['id']}": row for row in rows}
    selected_label = st.selectbox("Company", list(labels))
    provider = st.selectbox("Hiring platform", ["Greenhouse", "Lever", "Ashby"])
    identifier = st.text_input("Public board identifier", placeholder="company-name")
    st.caption("Examples: boards.greenhouse.io/figma → figma; jobs.ashbyhq.com/openai → openai; jobs.lever.co/example → example.")
    if st.button("Verify and save board", type="primary"):
        selected = labels[selected_label]
        try:
            preview = api.fetch_public_board_openings(provider, identifier, company=selected["company"].name)
            catalog.register_board(int(selected["id"]), provider, identifier)
            st.success(f"Board verified and saved. It currently publishes {len(preview)} position(s).")
        except (RuntimeError, ValueError):
            st.error("That board could not be verified. Check the platform and identifier; it was not saved.")


def _home(api, store, track):
    interests = store.interests(track)
    header = st.columns((5, 1))
    header[0].markdown('<div class="section-kicker">Your next chapter</div><h1>Good work starts with a direction.</h1>', unsafe_allow_html=True)
    header[0].write("Explore your roles. Build the evidence. Keep every application in one place.")
    if header[1].button("Edit my interests", use_container_width=True):
        go("onboarding")
    if header[1].button("Match me · 5 answers", type="primary", use_container_width=True,
                        help="Guided setup: role areas, experience, work style, company stage, industries — with a live count of hiring companies that fit."):
        go("match")
    columns = st.columns(2)
    for i, role in enumerate(interests.roles):
        with columns[i % 2]:
            st.markdown(f'<article class="hub-tile"><h2>{escape(role)}</h2><p>Live employer listings · tailored documents · project evidence</p><small>YOUR ROLE PAGE</small></article>', unsafe_allow_html=True)
            if st.button(f"Explore {role}", key=f"hub-open:{role}", use_container_width=True):
                go("role", role=role)
    _structured_profile(api, store, track)


def _structured_profile(api, store, track):
    """Zenply's core asset: the structured, recruiter-queryable candidate profile."""

    from tau_job_application.structured_profile import (
        RecruiterCriteria,
        build_structured_profile,
        evaluate_recruiter_query,
    )

    st.divider()
    st.markdown('<div class="section-kicker">What recruiters will query</div><h2>Your structured profile</h2>', unsafe_allow_html=True)
    st.caption(
        "Recruiters filter on structured data; candidates only have unstructured, self-reported documents. "
        "This is your data, organised: confirmed skills, completed evidence, declared eligibility, rehearsal level. "
        "Nothing leaves this device unless you download it yourself."
    )
    profile = build_structured_profile(
        workspaces=api.WORKSPACES, hub_store=store,
        residency_store=api._residency_store(), evidence_store=api._evidence_store(),
        application_store=api._application_store(), track=track,
    )
    completed = sum(1 for project in profile.evidence_projects if project.status == "completed")
    metrics = st.columns(4)
    metrics[0].metric("Confirmed skills", len(profile.skills))
    metrics[1].metric("Completed evidence projects", completed)
    metrics[2].metric("Interview level", f"Lv {profile.interview.current_level}")
    metrics[3].metric("Applications tracked", sum(profile.applications_by_stage.values()))
    if not profile.residence_country:
        st.caption("Add your residency profile (sidebar → Work eligibility) so recruiters can filter you on work authorization.")

    with st.expander("Run a recruiter-style filter on yourself", expanded=False):
        criteria_cols = st.columns(4)
        skills_text = criteria_cols[0].text_input("Required skills (comma-separated)", placeholder="Python, SQL", key=f"profile-criteria-skills:{track}")
        min_projects = criteria_cols[1].number_input("Min completed projects", min_value=0, max_value=50, value=0, key=f"profile-criteria-projects:{track}")
        min_level = criteria_cols[2].slider("Min interview level", min_value=1, max_value=5, value=1, key=f"profile-criteria-level:{track}")
        countries = ["Any country", "Germany", "France", "Switzerland", "United Kingdom", "United States", "Canada", "Netherlands", "Spain"]
        job_country = criteria_cols[3].selectbox("Job country", countries, key=f"profile-criteria-country:{track}")
        result = evaluate_recruiter_query(profile, RecruiterCriteria(
            skills_all=tuple(part.strip() for part in skills_text.split(",") if part.strip()),
            min_completed_projects=int(min_projects), min_interview_level=int(min_level),
            job_country=None if job_country == "Any country" else job_country,
        ))
        if result.qualified:
            st.success("Qualified for this filter." + (" " + " ".join(result.reasons) if result.reasons != ("All criteria satisfied.",) else ""))
        else:
            st.error("Filtered out: " + " ".join(result.reasons))
        st.caption("Deterministic rules, not a hiring prediction. Sponsorship needs are flags, not rejections.")

    st.download_button(
        "Download my structured profile (JSON)",
        data=profile.model_dump_json(indent=2),
        file_name="coapply_structured_profile.json",
        mime="application/json",
        key=f"profile-download:{track}",
    )


def _relative_posted_label(opening) -> str:
    """'Posted 5d ago' style label, only from a source-supplied publication date."""

    if opening.source_timestamp_kind != "published" or not opening.source_timestamp:
        return "Publication date not provided"
    try:
        published = datetime.fromisoformat(opening.source_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return "Publication date not provided"
    days = max(0, (datetime.now(UTC) - published).days)
    if days == 0:
        return "Posted today"
    if days == 1:
        return "Posted 1d ago"
    if days < 7:
        return f"Posted {days}d ago"
    weeks = days // 7
    return f"Posted {weeks}w ago"


def _track_and_open(api, track, opening, relevance):
    """Create the dedicated application thread and record, then open its workspace."""

    target = api._prepared_discovered_workspace(track, opening) or api._create_discovered_job_workspace(track, opening)
    record = api._application_store().save(track, target, opening, relevance=relevance)
    st.session_state["pending_workspace"] = track
    go("application", application=record.id)


def _append_note(api, track, opening, record, relevance, note: str) -> None:
    """Start tracking if needed, then append one dated note to the application."""

    if record is None:
        target = api._prepared_discovered_workspace(track, opening) or api._create_discovered_job_workspace(track, opening)
        record = api._application_store().save(track, target, opening, relevance=relevance)
    stamp = datetime.now(UTC).date().isoformat()
    existing = record.progress.notes
    entry = f"{stamp} · {note.strip()}"
    progress = record.progress.model_copy(update={"notes": f"{existing}\n{entry}" if existing else entry})
    api._application_store().update(track, record.id, progress)


def _cluster_dashboard(api, track: str, thread: str, page_matches: list, *, hidden_count: int) -> None:
    """Saved-jobs style rows for one role cluster: track, note, apply, hide.

    LinkedIn's avatar stack is deliberately replaced by the candidate's own
    tracking status: this app has no connections data and never invents one.
    """

    tracker = api._application_store()
    tracker.import_shortlist(track)
    tracked_by_key = {record.opening_key: record for record in tracker.list_records(track)}

    selection_keys = [f"cluster-sel:{thread}:{opening_key(match.opening)}" for match in page_matches]
    selected = [match for match, key in zip(page_matches, selection_keys, strict=True) if st.session_state.get(key)]
    bar = st.columns((3, 1, 1))
    bar[0].caption(
        f"{len(selected)} selected · {len(page_matches)} listings on this page"
        + (f" · {hidden_count} hidden by you" if hidden_count else "")
    )
    if bar[1].button("Track selected", key=f"cluster-track:{thread}", disabled=not selected, use_container_width=True):
        for match in selected[:20]:
            target = api._prepared_discovered_workspace(track, match.opening) or api._create_discovered_job_workspace(track, match.opening)
            api._application_store().save(track, target, match.opening, relevance=match.score)
            st.session_state.pop(f"cluster-sel:{thread}:{opening_key(match.opening)}", None)
        st.rerun()
    if bar[2].button("Hide selected", key=f"cluster-hide:{thread}", disabled=not selected, use_container_width=True):
        state_store = api._role_market_state_store()
        for match in selected[:20]:
            state_store.set_status(track, thread, match.opening, "hidden")
            st.session_state.pop(f"cluster-sel:{thread}:{opening_key(match.opening)}", None)
        st.rerun()

    for match in page_matches:
        opening = match.opening
        key = opening_key(opening)
        record = tracked_by_key.get(key)
        row = st.columns((0.35, 0.65, 4.4, 1.35, 1.05, 0.95, 0.35))
        row[0].checkbox("Select", key=f"cluster-sel:{thread}:{key}", label_visibility="collapsed")
        with row[1]:
            st.markdown(api._company_mark_markup(opening.company.name), unsafe_allow_html=True)
        with row[2]:
            if st.button(opening.title, key=f"cluster-open:{thread}:{key}", type="tertiary",
                         help="Open this role's application workspace"):
                _track_and_open(api, track, opening, match.score)
            workplace = f" ({opening.workplace_type})" if opening.workplace_type else ""
            st.markdown(
                f'<p class="cluster-meta">{escape(opening.company.name)} · {escape(opening.location or "Location not listed")}{escape(workplace)}</p>'
                f'<p class="cluster-posted">{escape(_relative_posted_label(opening))} · Official {escape(opening.source)} listing</p>',
                unsafe_allow_html=True,
            )
        with row[3]:
            stage = record.progress.stage if record else None
            status_class = stage.value if stage else "untracked"
            status_label = stage.label if stage else "Not tracked"
            st.markdown(
                f'<span class="cluster-status {status_class}">{escape(status_label)}</span>'
                f'<div class="cluster-relevance"><b>{match.score}</b> role relevance</div>',
                unsafe_allow_html=True,
            )
        with row[4]:
            note_count = len([line for line in (record.progress.notes.splitlines() if record else []) if line.strip()])
            with st.popover(f"＋ Note{'' if not note_count else f' ({note_count})'}", use_container_width=True):
                if record and record.progress.notes:
                    st.caption("Latest notes")
                    st.text("\n".join(record.progress.notes.splitlines()[-3:]))
                if record is None:
                    st.caption("Saving a note also starts tracking this role (stage: Saved).")
                with st.form(f"cluster-note:{thread}:{key}"):
                    note = st.text_area("New note", max_chars=2000, placeholder="Spoke to recruiter, asked for transcript…")
                    if st.form_submit_button("Save note"):
                        if note.strip():
                            _append_note(api, track, opening, record, match.score, note)
                            st.rerun()
                        else:
                            st.error("Write the note first.")
        with row[5]:
            if opening.canonical_url:
                st.link_button("Apply ↗", opening.canonical_url, use_container_width=True,
                               help="Opens the employer's official listing in a new tab. You apply there, never here.")
            else:
                st.caption("No apply link")
        with row[6]:
            with st.popover("⋯"):
                if st.button("Open application workspace", key=f"cluster-ws:{thread}:{key}"):
                    _track_and_open(api, track, opening, match.score)
                if st.button("Hide from this cluster", key=f"cluster-hide-one:{thread}:{key}"):
                    api._role_market_state_store().set_status(track, thread, opening, "hidden")
                    st.rerun()
                st.caption("Hidden listings stay in the Role market shortlist, where you can restore them.")
        st.divider()
    st.caption("Not seeing some jobs? Only official boards registered for this product are checked; hidden listings can be restored from the Role market shortlist.")


def _role(api, store, track):
    role = api._route_value("role").strip()
    if not role or len(role) > 100:
        st.info("Choose a role from My role pages first.")
        return
    thread = store.role_page(api.WORKSPACES, track, role)
    st.markdown(f'<div class="section-kicker">Open possibilities</div><h1>{escape(role)}</h1>', unsafe_allow_html=True)
    st.caption("Employer-board observations, not a guarantee of availability. Refresh to check the feeds; no CV is sent to employers.")
    profile = api.WORKSPACES.shared_profile()
    left, right = st.columns((3, 1))
    aliases = left.text_input("Include related titles", value=", ".join(suggest_role_aliases(role)), key=f"hub-aliases:{thread}")
    run = api.ROLE_DISCOVERY.latest_run(career_track_id=track, workspace_id=thread)
    boards = _portal_boards(api)
    first_check = run is None and not st.session_state.get(f"hub-checked:{thread}")
    if right.button("Refresh positions", type="primary", use_container_width=True) or first_check:
        st.session_state[f"hub-checked:{thread}"] = True
        with st.spinner("Checking official employer boards…"):
            api._refresh_role_market(track, thread, role_title=role, aliases=aliases,
                                     profile_skills=tuple(parse_candidate_text(profile["cv_text"]).skills) if profile["cv_text"].strip() else (),
                                     enabled_sources=("Greenhouse", "Lever", "Ashby"), boards=boards)
        st.rerun()
    notice = st.session_state.get(f"role-market-refresh-notice:{thread}")
    if notice:
        st.warning(notice)
    run = api.ROLE_DISCOVERY.latest_run(career_track_id=track, workspace_id=thread)
    if not run:
        st.info("Refresh positions to load this role’s first live cluster. No demonstration vacancies are mixed into the results.")
        _role_company_browser(api, role, thread)
        return
    companies = sorted({board.company.name for board in boards})
    coverage = ", ".join(companies[:6]) + (f" and {len(companies) - 6} more" if len(companies) > 6 else "")
    st.caption(f"Last checked: {run.created_at} · {len(run.matches)} related listings · official-board coverage: {coverage}. Unmapped catalogue companies do not produce vacancy claims.")
    for error in run.errors:
        st.warning(error)
    st.checkbox(
        "Load remote company logos", key="remote-logos-opt-in",
        help="Off by default: loading a remote image shares your IP address with its host.",
    )
    # Filter keys are scoped to this role thread so one role's filters never
    # leak into another role page through Streamlit's widget state.
    controls = st.columns(4)
    company = controls[0].selectbox("Company", ["All companies", *sorted({match.opening.company.name for match in run.matches})], key=f"hub-company:{thread}")
    location = controls[1].text_input("Location", placeholder="City, country, or remote", key=f"hub-location:{thread}")
    period = controls[2].selectbox("Period", list(PERIOD_CHOICES), key=f"hub-period-choice:{thread}",
                                   help="Matches only the employer's stated wording (e.g. “Summer 2026 internship”).")
    order = controls[3].selectbox("Order", ["Recently published", "Role relevance"], key=f"hub-order:{thread}")
    specific_period = ""
    if period == "Specific period…":
        specific_period = st.text_input("Specific period", placeholder="Summer 2026, 2027, Q3…", max_chars=100, key=f"hub-period:{thread}")
    matches = [match for match in run.matches if (company == "All companies" or match.opening.company.name == company)
               and (not location or location.casefold() in (match.opening.location or "").casefold())
               and (period == "Any time" or opening_matches_period(
                   match.opening,
                   season="" if period == "Specific period…" else period,
                   specific=specific_period,
               ))]
    if order == "Recently published":
        # Never present an update time or the collection time as a publication date.
        matches.sort(key=lambda match: match.opening.source_timestamp if match.opening.source_timestamp_kind == "published" and match.opening.source_timestamp else "", reverse=True)
    state_store = api._role_market_state_store()
    states = {state.opening_key: state for state in state_store.list_states(track, thread)}
    visible = [match for match in matches if (state := states.get(opening_key(match.opening))) is None or state.status is not RoleMarketStatus.HIDDEN]
    hidden_count = len(matches) - len(visible)
    page_count = max(1, (len(visible) + 11) // 12)
    page = st.selectbox("Position page", range(1, page_count + 1), key=f"hub-page:{thread}") if page_count > 1 else 1
    _cluster_dashboard(api, track, thread, visible[(page - 1) * 12:page * 12], hidden_count=hidden_count)
    if not visible:
        st.info("No related positions in these employer feeds match your filters. Try an alias, restore a hidden listing, or use the existing Role market to bring a permitted source.")
    _role_company_browser(api, role, thread)


def _role_company_browser(api, role, thread):
    """The portfolio-style company choice shown on every role page."""

    st.divider()
    st.markdown(
        f'<div class="section-kicker">Choose your target</div><h2>Explore companies for {escape(role)}</h2>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Pick a startup from the local YC directory snapshot or a big company from the Global Capital "
        "Atlas snapshot. Entries are research leads, not vacancy claims; verify openings on official boards."
    )
    render_company_browser(api, role=role, key_prefix=f"role-browser:{thread}")


def _document_upload(api, label, key):
    upload = st.file_uploader(label, type=["pdf", "docx", "txt", "md"], key=key)
    if upload is None:
        return None
    if upload.size > 5_000_000:
        st.error("Choose a document smaller than 5 MB.")
        return None
    import hashlib
    fingerprint = hashlib.sha256(upload.getvalue()).hexdigest()
    if st.session_state.get(key + ":loaded") == fingerprint:
        return None
    try:
        # Check DOCX expansion before invoking the existing extractor.
        if upload.name.lower().endswith(".docx"):
            from io import BytesIO
            from zipfile import ZipFile
            with ZipFile(BytesIO(upload.getvalue())) as archive:
                if sum(item.file_size for item in archive.infolist()) > 15_000_000:
                    raise ValueError("Expanded document is too large")
        value = api._upload_text(upload)
        if not value.strip() or len(value) > 100_000:
            raise ValueError("Use a text-readable document with fewer than 100,000 characters")
        st.session_state[key + ":loaded"] = fingerprint
        return value
    except Exception:
        st.error("Could not read this document. Try a selectable-text PDF, DOCX, or plain text.")
        return None


def _application(api, store, track):
    tracker = api._application_store()
    try:
        record = tracker.get(track, api._route_value("application"))
    except ValueError:
        st.info("This application is not available in the selected career track.")
        return
    opening, thread = record.opening, record.thread_id
    if api.WORKSPACES.thread(track, thread)["draft"]["job_url"] != (opening.source_url or ""):
        # Legacy saved roles belonged to discovery threads. Keep their tracking
        # history intact, but edit documents/evidence in a dedicated preparation room.
        thread = api._prepared_discovered_workspace(track, opening) or api._create_discovered_job_workspace(track, opening)
        record = record.model_copy(update={"thread_id": thread})
    st.markdown(f'<div class="section-kicker">Your application workspace</div><h1>{escape(opening.title)}</h1><p>{escape(opening.company.name)} · {escape(opening.location or "Location not listed")} · {record.progress.stage.label}</p>', unsafe_allow_html=True)
    with st.expander("Role brief & source"):
        st.text(opening.description or "The feed did not provide an advert description.")
        if opening.canonical_url:
            st.link_button("Verify this vacancy at the employer", opening.canonical_url)
    tab_docs, tab_evidence, tab_practice, tab_people, tab_replies, tab_apply = st.tabs(
        ["Documents & fit", "Project evidence", "Interview practice", "People to contact", "Replies & status", "Apply"]
    )
    with tab_docs:
        _documents(api, store, track, record)
    with tab_evidence:
        api._project_evidence(track, thread)
        api._project_studio(track, thread)
    with tab_practice:
        api._interview(track, thread)
    with tab_people:
        _people(opening)
    with tab_replies:
        _replies(api, track, record)
    with tab_apply:
        st.subheader("Review, then apply")
        st.write("Download your reviewed documents, open the official form, and check its questions and declarations. Nothing is submitted by this app.")
        if opening.canonical_url:
            st.link_button("Open official application", opening.canonical_url, type="primary")
        st.info("Computer-use submission is not enabled. Employer forms and consent questions require a supervised, site-specific integration; this workspace is the preparation and review handoff.")
        confirmed = st.checkbox("I submitted this application on the employer’s website", key=f"hub-submitted:{record.id}")
        if st.button("Record my application", disabled=not confirmed, key=f"hub-record:{record.id}"):
            progress = record.progress.model_copy(update={"stage": ApplicationStage.APPLIED,
                "stage_on": tracker_today(), "applied_on": record.progress.applied_on or tracker_today(), "closed_reason": ""})
            tracker.update(track, record.id, progress, expected_updated_at=record.updated_at)
            go("applications")


def _documents(api, store, track, record):
    thread = api.WORKSPACES.thread(track, record.thread_id)
    documents = store.documents(track, record.thread_id)
    key = f"hub-docs:{record.id}"
    if key + ":pending-letter" in st.session_state:
        st.session_state[key + ":letter"] = st.session_state.pop(key + ":pending-letter")
    left, right = st.columns(2)
    with left:
        cv_upload = _document_upload(api, "Drop your CV", key + ":cv-upload")
        if cv_upload is not None:
            st.session_state[key + ":cv"] = cv_upload
        cv = st.text_area("CV or factual background", value=thread["draft"]["cv_text"], height=230, max_chars=100_000, key=key + ":cv", help="No CV yet? List your education, work, skills, and completed projects. We will not invent them.")
    with right:
        letter_upload = _document_upload(api, "Drop your motivation letter (optional)", key + ":letter-upload")
        if letter_upload is not None:
            st.session_state[key + ":letter"] = letter_upload
        letter = st.text_area("Motivation letter", value=documents["letter"], height=230, max_chars=100_000, key=key + ":letter")
    detected = parse_candidate_text(cv) if cv.strip() else None
    confirmed = st.multiselect("Skills you can substantiate for this application", detected.skills if detected else [],
                               default=[skill for skill in detected.skills if any(e.id == "candidate-skill-" + re.sub(r"[^a-z0-9]+", "-", skill.casefold()).strip("-") and e.confirmed for e in detected.evidence)] if detected else [], key=key + ":skills")
    st.caption("Review extracted skills before scoring. Only selected skills count as confirmed; an unconfirmed keyword or a planned project is not proof.")
    if st.button("Save documents & assess fit", type="primary", key=key + ":assess"):
        if not cv.strip():
            st.error("Add your CV or factual background first.")
        elif not record.opening.description:
            st.error("This feed did not provide a description. Add it in the existing Job brief before assessment.")
        else:
            result = analyze_texts(cv, thread["draft"]["job_text"], job_title=record.opening.title,
                                   company=record.opening.company.name, job_url=thread["draft"]["job_url"] or None,
                                   requirement_memory=api.REQUIREMENT_MEMORY, confirmed_skills=confirmed)
            draft = {**thread["draft"], "cv_text": cv}
            api.WORKSPACES.save_draft(track, record.thread_id, draft)
            api.WORKSPACES.save_analysis(track, record.thread_id, result)
            store.save_documents(track, record.thread_id, letter=letter, resume=documents["resume"])
            st.success("Documents saved. Fit is based on your confirmed CV skills and completed project evidence.")
    current = api.WORKSPACES.thread(track, record.thread_id)
    result = current["analysis"]
    approved = {skill for skill in result.candidate.skills if any(
        e.id == "candidate-skill-" + re.sub(r"[^a-z0-9]+", "-", skill.casefold()).strip("-") and e.confirmed
        for e in result.candidate.evidence)} if result else set()
    if result and not current["stale"] and cv == current["draft"]["cv_text"] and set(confirmed) == approved:
        assessment = calculate_evidence_match(result.candidate, result.job, api._evidence_store().list_projects(track, record.thread_id))
        metrics = st.columns(3)
        metrics[0].metric("CV requirement coverage", f"{assessment.role_coverage}/100")
        metrics[1].metric("Completed project coverage", f"{assessment.project_coverage}/100" if assessment.project_coverage is not None else "Not enough evidence")
        metrics[2].metric("Combined evidence match", f"{assessment.score}/100" if assessment.score is not None else "Not available")
        st.caption("Not a hiring probability or validated ATS score. Letter prose does not raise your evidence score. No employee profiles are used.")
        if st.button("Create reviewable CV & letter drafts", key=key + ":draft"):
            resume, new_letter = draft_documents(cv, record.opening.title, record.opening.company.name, result.tailored_resume.relevant_skills)
            store.save_documents(track, record.thread_id, letter=new_letter, resume=resume)
            st.session_state[key + ":pending-letter"] = new_letter
            st.rerun()
    else:
        st.caption("Save and assess the current documents to see a fresh score and create drafts.")
    documents = store.documents(track, record.thread_id)
    if documents["resume"]:
        st.caption("Drafts reorganise supplied facts and contain review placeholders. They are not final, generated credentials or a complete designed résumé.")
        st.download_button("Download CV draft (.txt)", documents["resume"], "cv-draft.txt", key=key + ":download-cv")
    if documents["letter"]:
        st.download_button("Download saved motivation letter (.txt)", documents["letter"], "motivation-letter.txt", key=key + ":download-letter")


def _people(opening):
    st.subheader("Find the team behind the role")
    st.caption("These are role-specific search suggestions, not verified named contacts. LinkedIn is opened for you; profiles are not scraped.")
    for role, url in contact_searches(opening.company.name, opening.title):
        st.link_button(f"Find {role}", url)
    public_emails = sorted(set(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", opening.description or "")))
    for address in public_emails[:5]:
        st.text(f"Address mentioned in the advert: {address} · check its purpose before contacting")
    with st.expander("Infer an address from an observed company pattern"):
        st.warning("An address hypothesis is not verified. Do not send to it until independently confirmed. No mailbox probing or bulk outreach is performed.")
        name = st.text_input("Public contact name")
        domain = st.text_input("Verified company email domain")
        pattern = st.selectbox("Observed naming pattern", ["first.last", "flast", "first"])
        source = st.text_input("Public source showing this company’s pattern", placeholder="https://…")
        if st.button("Generate unverified hypothesis"):
            try:
                st.code(infer_email(name, domain, pattern, source))
                st.caption("UNVERIFIED · hypothesis only · not saved or used for sending")
            except ValueError as exc:
                st.error(str(exc))


def _replies(api, track, record):
    inbox = InboxStore(api._application_store())
    st.subheader("Replies, connected to the right application")
    st.caption("Bind a conversation and an exact sender. Tokens are read from server configuration, never stored in the application database. Slack proposals always need review.")
    binding = inbox.binding(track, record.id)
    with st.form(f"hub-binding:{record.id}"):
        source = st.selectbox("Reply source", ["gmail", "slack"], index=1 if binding and binding["source"] == "slack" else 0)
        conversation = st.text_input("Gmail API thread ID or Slack conversation ID", value=binding["conversation"] if binding else "")
        sender = st.text_input("Exact recruiter email or Slack member ID", value=binding["sender"] if binding else "")
        auto = st.checkbox("Automatically update clear Gmail outcomes after binding", value=bool(binding and binding["auto_update"]))
        st.caption("Opt-in can record interview invitations, offers (not acceptance), or rejections. It never accepts an offer or sends a reply. Sender matching is not cryptographic identity verification.")
        if st.form_submit_button("Save reply connection"):
            try:
                inbox.bind(track, record.id, source=source, conversation=conversation, sender=sender, auto_update=auto)
                st.success("Connection saved. Only future, clearly matched Gmail replies can auto-update status.")
                binding = inbox.binding(track, record.id)
            except ValueError as exc:
                st.error(str(exc))
    if not binding:
        st.info("No connection saved. Manual tracking remains available in My applications.")
        return
    token_name = "GMAIL_ACCESS_TOKEN" if binding["source"] == "gmail" else "SLACK_BOT_TOKEN"
    configured = bool(os.environ.get(token_name))
    st.caption(f"{token_name}: {'configured' if configured else 'not configured; see the setup report'}")
    consent = st.checkbox("Allow reading this bound conversation on this device", key=f"hub-read:{record.id}")
    polling = st.checkbox("Check every 60 seconds while this page is open", disabled=not configured or not consent, key=f"hub-poll:{record.id}")

    @st.fragment(run_every=60 if polling and consent and configured else None)
    def sync_panel():
        clicked = st.button("Check for replies", disabled=not configured or not consent, key=f"hub-sync:{record.id}")
        if clicked or (polling and configured and consent):
            try:
                replies = (read_gmail if binding["source"] == "gmail" else read_slack)(os.environ[token_name], binding["conversation"])
                counts = {"updated": 0, "review": 0, "duplicate": 0, "unmatched": 0}
                for reply in sorted(replies, key=lambda item: item.received_at):
                    counts[inbox.ingest(track, record.id, reply, trusted_connector=True)] += 1
                st.success(f"Checked this conversation: {counts['updated']} status updates, {counts['review']} new replies to review.")
            except (ValueError, KeyError, TypeError):
                st.error("Could not complete sync. Check permissions and connection settings. Existing application history is retained.")
        for event in inbox.events(track, record.id):
            with st.container(border=True):
                st.caption(f"{event['source']} · {event['received_at']} · {event['state']}")
                st.text(event["text"])
                if event["state"] == "review" and event["proposed_stage"]:
                    if st.button(f"Confirm status: {event['proposed_stage']}", key=f"hub-confirm:{event['id']}"):
                        inbox.apply(track, record.id, event["id"])
                        st.rerun()
                elif event["state"] == "review":
                    st.caption("No unambiguous outcome detected. Update the status manually if needed.")
        st.caption("Current recorded status: " + api._application_store().get(track, record.id).progress.stage.label)
    sync_panel()


_STYLE = """<style>
.stApp,[data-testid="stAppViewContainer"]{background:#faf8f1!important;}
.hub-tile{padding:26px 0 22px;border-bottom:1px solid #c7c5bb;min-height:190px;}
.hub-tile h2{font-size:1.65rem;letter-spacing:-.035em;color:#151c18;margin:0;}
.hub-tile h3{font-size:1.04rem;line-height:1.45;color:#27392f;margin:1.2rem 0 .5rem;}
.hub-tile p{color:#48524b;line-height:1.6;margin:.65rem 0;}
.hub-tile small{font-family:monospace;font-size:.77rem;letter-spacing:.025em;color:#69716a;}
.hub-company{display:flex;align-items:center;gap:16px;}.hub-company .role-feed-avatar{flex-shrink:0;}
.cluster-title{color:#151c18;font-weight:650;font-size:.98rem;line-height:1.35;margin:0;}
.cluster-meta{color:#5f6a63;font-size:.84rem;margin:.15rem 0 0;}
.cluster-posted{color:#8a9088;font-size:.78rem;margin:.1rem 0 0;}
.cluster-status{display:inline-block;border-radius:999px;padding:.16rem .6rem;font-size:.72rem;font-weight:700;letter-spacing:.02em;}
.cluster-status.untracked{background:#f0eee6;color:#7a7565;border:1px solid #ddd8c8;}
.cluster-status.saved{background:#eef2ea;color:#4a5d52;border:1px solid #d5dfd2;}
.cluster-status.preparing{background:#e8eff5;color:#3d5a74;border:1px solid #cfdeeb;}
.cluster-status.applied{background:#e2efe5;color:#27543c;border:1px solid #bdd4c2;}
.cluster-status.contacted{background:#e2efe5;color:#27543c;border:1px solid #bdd4c2;}
.cluster-status.interview{background:#f7f2e4;color:#74613a;border:1px solid #e6d8af;}
.cluster-status.offer{background:#e5f3ec;color:#1c6a44;border:1px solid #bfe0cf;}
.cluster-status.closed{background:#f3e8e6;color:#8a4a40;border:1px solid #e2c9c4;}
.cluster-relevance{font-size:.72rem;color:#69716a;margin-top:.3rem;}
.cluster-relevance b{color:#173a31;font-size:.95rem;}
button:focus-visible,a:focus-visible{outline:3px solid #16734c!important;outline-offset:3px;}
@media(max-width:700px){.hub-tile{min-height:0;padding:20px 0;}.hub-tile h2{font-size:1.35rem;}}
</style>"""
