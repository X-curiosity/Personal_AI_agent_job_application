"""Guided match onboarding UI: five steps with a live company-match count.

Follows the startupmap.one seeker-join pattern (docs/STARTUPMAP_RE_NOTES.md),
generalized to every company type in the local data. Role areas and experience
shape the role pages offered at the end; only stage, industry and location
filter the company count, and the sidebar always says which facts did it.
"""
from __future__ import annotations

from html import escape

import streamlit as st

from tau_job_application.career_hub import FIELDS, HubStore, Interests
from tau_job_application.match_onboarding import (
    EXPERIENCE_LEVELS,
    LOCATION_MODES,
    ROLE_AREA_TO_FIELD,
    ROLE_AREAS,
    STAGE_GROUPS,
    STEPS,
    WORK_STYLES,
    MatchPreferenceStore,
    MatchPreferences,
    company_matches,
    gather_match_candidates,
    match_summary,
)

_STEP_TITLES = {
    "roles": "What do you want to do?",
    "experience": "How experienced are you?",
    "work": "How and where do you want to work?",
    "stage": "What kind of company?",
    "industry": "Any industries you care about?",
}

_STEP_LABELS = {
    "roles": "Role areas",
    "experience": "Experience",
    "work": "Work style & place",
    "stage": "Company stage",
    "industry": "Industries",
}


def _industry_options(candidates) -> list[str]:
    industries = sorted(
        {facts.industry.strip() for facts in candidates if facts.industry and facts.industry.strip()},
        key=str.casefold,
    )
    return industries[:60]


def _match_sidebar(candidates, prefs: MatchPreferences, current_step: str) -> None:
    view = prefs.for_step(current_step)
    summary = match_summary(candidates, view)
    matched = [facts for facts in candidates if company_matches(facts, view)]
    with st.sidebar:
        st.markdown("### Your matches so far")
        st.metric("Companies hiring that fit", summary["companies"])
        st.caption(f"{summary['live']} verified against a live official board · updates as you answer")
        if matched:
            st.caption("Including: " + " · ".join(facts.name for facts in matched[:6]))
        else:
            st.caption("No company fits these filters yet — widen one to see matches.")
        with st.expander("What this count uses", expanded=False):
            st.caption(
                "Deterministic filters over the local hiring index and company database: "
                "company stage (estimated from team size or stage labels), industry, and location. "
                "Role areas and experience never hide a company — they shape your role pages. "
                "Nothing leaves this device."
            )


def _step_body(prefs: MatchPreferences, step: str, candidates) -> MatchPreferences:
    if step == "roles":
        picked = st.multiselect(
            "Role areas", list(ROLE_AREAS), default=list(prefs.role_areas),
            key="match-roles",
            help="Pick everything that interests you; you refine exact roles later.",
        )
        for area in picked:
            st.caption(f"**{area}** — {ROLE_AREAS[area]}")
        return prefs.model_copy(update={"role_areas": tuple(picked)})

    if step == "experience":
        labels = {level: f"{label} · {detail}" for level, label, detail in EXPERIENCE_LEVELS}
        choice = st.radio(
            "Experience", list(labels), format_func=labels.get,
            index=[level for level, _, _ in EXPERIENCE_LEVELS].index(prefs.experience) if prefs.experience in labels else None,
            key="match-experience",
        )
        return prefs.model_copy(update={"experience": choice or ""})

    if step == "work":
        styles = st.multiselect(
            "Work styles", list(WORK_STYLES), default=list(prefs.work_styles),
            key="match-work-styles", format_func=str.title,
        )
        mode_labels = {mode: label for mode, label in LOCATION_MODES}
        mode = st.radio(
            "Location", list(mode_labels), format_func=mode_labels.get,
            index=[mode for mode, _ in LOCATION_MODES].index(prefs.location_mode),
            key="match-location-mode",
        )
        country, cities = prefs.country, prefs.target_cities
        if mode == "country":
            country = st.text_input("Country", value=prefs.country, max_chars=60, key="match-country",
                                    placeholder="Germany, USA, Switzerland…")
        elif mode == "cities":
            cities_text = st.text_input(
                "Cities (comma-separated)", value=", ".join(prefs.target_cities), max_chars=200,
                key="match-cities", placeholder="Zurich, Berlin, London",
            )
            cities = tuple(city.strip() for city in cities_text.split(",") if city.strip())
        return prefs.model_copy(update={
            "work_styles": tuple(styles), "location_mode": mode,
            "country": country.strip(), "target_cities": tuple(cities),
        })

    if step == "stage":
        labels = {group: f"{label} — {desc}" for group, label, desc in STAGE_GROUPS}
        picked = st.multiselect(
            "Company stages", list(labels), default=list(prefs.stage_groups),
            format_func=labels.get, key="match-stage",
            help="Leave empty for any. Stage is estimated from team size or stage labels, never verified funding data.",
        )
        return prefs.model_copy(update={"stage_groups": tuple(picked)})

    if step == "industry":
        picked = st.multiselect(
            "Industries", _industry_options(candidates), default=[i for i in prefs.industries],
            key="match-industry",
            help="Leave empty for any industry. Matching is name-based on stored directory facts.",
        )
        return prefs.model_copy(update={"industries": tuple(picked[:20])})

    raise ValueError("Unknown onboarding step")


def _finish(api, track: str, prefs: MatchPreferences, candidates) -> None:
    summary = match_summary(candidates, prefs)
    matched = [facts for facts in candidates if company_matches(facts, prefs)]
    st.success(f"{summary['companies']} hiring companies fit your answers · {summary['live']} verified on live official boards.")
    if matched:
        st.dataframe(
            [{
                "Company": facts.name,
                "Stage": f"{dict((g, l) for g, l, _ in STAGE_GROUPS)[facts.stage_group]} ({facts.stage_basis})",
                "Industry": facts.industry or "n/a",
                "Locations": facts.locations or "n/a",
                "Signal": "Live official board" if facts.hiring_signal == "live_openings" else "Directory flag (unverified)",
            } for facts in matched[:50]],
            hide_index=True, use_container_width=True,
        )
    st.caption("Stage is estimated from team size or stage labels — not verified funding data. Directory flags are unverified directory claims; live rows are read from official employer boards.")

    areas = [area for area in prefs.role_areas if area in ROLE_AREA_TO_FIELD]
    if areas:
        if st.button("Build role pages from my role areas", type="primary", key="match-build-roles"):
            from tau_job_application.career_hub_ui import go
            store = HubStore(api.WORKSPACES.path)
            existing = store.interests(track)
            fields = list(dict.fromkeys([*(existing.fields if existing else []), *(ROLE_AREA_TO_FIELD[area] for area in areas)]))
            subfields = list(existing.subfields) if existing else []
            roles = list(existing.roles) if existing else []
            for field in fields:
                for options in FIELDS.get(field, {}).values():
                    roles.extend(role for role in options[:2] if role not in roles)
            store.save_interests(track, Interests(fields=fields[:6], subfields=subfields, roles=roles[:20]))
            go("career")


def render_match_onboarding(api, track: str) -> None:
    """The five-step guided flow; answers persist per career track."""

    store = MatchPreferenceStore(api.WORKSPACES.path)
    prefs = store.load(track) or MatchPreferences(career_track_id=track)
    candidates = gather_match_candidates(api._hiring_index_store(), api._company_catalog_store())

    st.markdown('<div class="section-kicker">Match me</div><h1>Five answers, one honest count</h1>', unsafe_allow_html=True)
    st.caption(
        "Answer five questions and watch the company count narrow live. "
        "Everything is computed on this device from the local hiring index and company database."
    )

    current = next((step for step in STEPS if step not in prefs.steps_done), None)
    if current is None:
        _finish(api, track, prefs, candidates)
        if st.button("Edit my answers", key="match-edit"):
            store.save(prefs.model_copy(update={"steps_done": ()}))
            st.rerun()
        return

    _match_sidebar(candidates, prefs, current)
    progress = STEPS.index(current) / len(STEPS)
    st.progress(progress, text=f"Step {STEPS.index(current) + 1} of {len(STEPS)} · {_STEP_LABELS[current]}")
    st.subheader(_STEP_TITLES[current])

    updated = _step_body(prefs, current, candidates)
    left, right = st.columns((1, 1))
    valid = (
        (current == "roles" and bool(updated.role_areas))
        or (current == "experience" and bool(updated.experience))
        or (current == "work" and bool(updated.work_styles) and (
            updated.location_mode == "anywhere"
            or (updated.location_mode == "country" and bool(updated.country))
            or (updated.location_mode == "cities" and bool(updated.target_cities))
        ))
        or current in {"stage", "industry"}
    )
    if right.button("Continue →", type="primary", disabled=not valid, use_container_width=True, key=f"match-next:{current}"):
        store.save(updated.model_copy(update={"steps_done": (*prefs.steps_done, current)}))
        st.rerun()
    if current in {"stage", "industry"} and left.button("Skip — any", use_container_width=True, key=f"match-skip:{current}"):
        store.save(prefs.model_copy(update={"steps_done": (*prefs.steps_done, current)}))
        st.rerun()
