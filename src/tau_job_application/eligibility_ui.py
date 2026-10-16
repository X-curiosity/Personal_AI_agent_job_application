"""Work-eligibility view: self-declared residency profile + document checklists."""
from __future__ import annotations

import streamlit as st

from tau_job_application.eligibility import (
    DISCLAIMER,
    KNOWN_COUNTRIES,
    ResidencyProfile,
    eligibility_checklist,
)

_PATHWAY_LABELS = {
    "domestic": "Domestic application",
    "free_movement": "Free-movement bloc (EU/EEA/Switzerland)",
    "existing_permit": "Existing work permit",
    "sponsorship": "Employer-sponsored work visa",
}


def render_eligibility(api, track: str) -> None:
    store = api._residency_store()
    saved = store.get(track)
    st.markdown(
        '<div class="section-kicker">Cross-border applications</div><h1>Work eligibility</h1>',
        unsafe_allow_html=True,
    )
    st.write(
        "Tell us where you live and what passports or permits you hold. When a role is outside your "
        "residency country, we show which pathway likely applies and which documents to prepare."
    )
    st.caption("Everything here is self-declared and stored locally. It is never sent to a job feed or employer.")

    with st.expander("Your residency profile", expanded=saved is None):
        citizenships = st.multiselect(
            "Citizenship(s)", list(KNOWN_COUNTRIES),
            default=list(saved.citizenships) if saved else [],
            help="Countries where you hold a passport.",
        )
        residence_options = list(KNOWN_COUNTRIES)
        residence = st.selectbox(
            "Country of residence", residence_options,
            index=residence_options.index(saved.residence_country) if saved and saved.residence_country in residence_options else None,
            placeholder="Where you currently live",
        )
        permits = st.multiselect(
            "Existing work permits (countries)", list(KNOWN_COUNTRIES),
            default=list(saved.work_permits) if saved else [],
            help="Countries where you already hold a valid work permit or visa.",
        )
        if st.button("Save residency profile", type="primary"):
            try:
                if residence is None:
                    raise ValueError("Choose your country of residence")
                profile = ResidencyProfile(
                    citizenships=tuple(citizenships), residence_country=residence, work_permits=tuple(permits),
                )
                store.save(track, profile)
                st.success("Residency profile saved locally.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    profile = store.get(track)
    if profile is None:
        st.info("Save your residency profile once to build country-specific checklists.")
        return

    st.divider()
    st.subheader("Check a job country")
    st.caption(
        f"Citizen of {', '.join(profile.citizenships)} · resident in {profile.residence_country}"
        + (f" · permits: {', '.join(profile.work_permits)}" if profile.work_permits else "")
    )
    country_options = list(KNOWN_COUNTRIES)
    job_country = st.selectbox(
        "Country of the role", country_options,
        index=country_options.index(profile.residence_country) if profile.residence_country in country_options else None,
        placeholder="Where is the position located?",
        key=f"eligibility-job-country:{track}",
    )
    if st.button("Build my document checklist", type="primary") and job_country:
        try:
            result = eligibility_checklist(profile, job_country)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state[f"eligibility-result:{track}"] = result.model_dump(mode="json")

    result = st.session_state.get(f"eligibility-result:{track}")
    if not result:
        return
    st.markdown(f"**Pathway: {_PATHWAY_LABELS.get(result['pathway'], result['pathway'])}** · {result['job_country']}")
    st.write(result["summary"])
    for item in result["items"]:
        with st.container(border=True):
            st.markdown(f"**{item['title']}**")
            st.write(item["detail"])
            if item["documents"]:
                st.markdown("Documents to prepare:")
                for document in item["documents"]:
                    st.markdown(f"- {document}")
            if item["official_source"]:
                st.markdown(f"[Verify with the official source]({item['official_source']})")
    st.warning(DISCLAIMER)
