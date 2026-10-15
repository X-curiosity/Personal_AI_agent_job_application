"""YC company explorer view with vclense-style filters synced to the URL.

Filters run locally against the stored snapshot; the network is touched only
by the explicit refresh button. The state mirrors the ycglobe query style:
``?view=yc&status=Active&flags=hiring``.
"""
from __future__ import annotations

import streamlit as st

from tau_job_application.company_catalog import CatalogCompany, employee_band
from tau_job_application.yc_directory import (
    YC_STATUSES,
    YCFilters,
    directory_facets,
    fetch_yc_directory,
)


def _param_values(name: str) -> list[str]:
    value = st.query_params.get(name, "")
    if isinstance(value, list):
        return [part for entry in value for part in str(entry).split(",") if part.strip()]
    return [part for part in str(value).split(",") if part.strip()]


def render_yc_browser(api) -> None:
    store = api._yc_directory_store()
    catalog = api._company_catalog_store()
    st.markdown(
        '<div class="section-kicker">Public directory, local filters</div><h1>YC company explorer</h1>',
        unsafe_allow_html=True,
    )
    st.write(
        "Filter the YC company directory the way sites like YC Globe do — status, hiring flag, batch, "
        "industry, region — but locally, against a snapshot you refresh explicitly."
    )
    st.caption(
        "Source: the unofficial yc-oss daily mirror of the public YC directory. A directory entry — "
        "even one flagged as hiring — is never proof of an open vacancy. Verify on the company's own board."
    )

    snapshot = store.snapshot()
    header = st.columns((2, 1))
    header[0].caption(
        f"Snapshot: {snapshot['record_count']} companies · refreshed {str(snapshot['refreshed_at'])[:16].replace('T', ' ')} UTC"
        if snapshot else "No directory snapshot yet."
    )
    if header[1].button("Refresh directory snapshot", use_container_width=True):
        try:
            with st.spinner("Fetching the public yc-oss directory once…"):
                count = store.refresh(fetch_yc_directory())
            st.success(f"Stored {count} public company records.")
            st.rerun()
        except (RuntimeError, ValueError):
            st.error("The directory could not be refreshed. The previous snapshot was kept; try again later.")

    if snapshot is None:
        st.info("Refresh the snapshot once to start filtering. Nothing is fetched until you do.")
        return

    companies = store.companies()
    facets = directory_facets(companies)

    default_statuses = [s for s in _param_values("status") if s in YC_STATUSES]
    default_hiring = "hiring" in {flag.casefold() for flag in _param_values("flags")}

    with st.expander("Filters", expanded=True):
        row = st.columns(4)
        statuses = row[0].multiselect("Status", list(YC_STATUSES), default=default_statuses)
        batches = row[1].multiselect("Batch", facets["batches"])
        industries = row[2].multiselect("Industry", facets["industries"])
        regions = row[3].multiselect("Region", facets["regions"])
        row = st.columns(4)
        hiring_only = row[0].checkbox("Hiring only", value=default_hiring)
        top_only = row[1].checkbox("Top companies only")
        query = row[2].text_input("Search", placeholder="name, description, tag", max_chars=200)
        limit = row[3].selectbox("Max results", [25, 50, 100, 200, 500], index=2)
        row = st.columns(4)
        min_team = row[0].number_input("Min team size", min_value=0, max_value=100_000, value=0, step=5)
        max_team_value = row[1].number_input("Max team size (0 = no cap)", min_value=0, max_value=100_000, value=0, step=5)
        if row[2].button("Apply filters to URL", use_container_width=True):
            params = {"view": "yc"}
            if statuses:
                params["status"] = ",".join(statuses)
            flags = [flag for flag, active in (("hiring", hiring_only), ("top", top_only)) if active]
            if flags:
                params["flags"] = ",".join(flags)
            st.query_params.clear()
            st.query_params.update(params)
            st.rerun()
        if row[3].button("Clear URL filters", use_container_width=True):
            st.query_params.clear()
            st.query_params["view"] = "yc"
            st.rerun()

    filters = YCFilters(
        statuses=tuple(statuses), hiring_only=hiring_only, top_only=top_only,
        batches=tuple(batches), industries=tuple(industries), regions=tuple(regions),
        query=query, min_team_size=int(min_team) or None,
        max_team_size=int(max_team_value) or None, limit=int(limit),
    )
    matches = store.search(filters)
    st.caption(f"{len(matches)} matching companies (snapshot filter, not a live feed)")

    if not matches:
        st.info("No companies match these filters in the current snapshot. Broaden the filters or refresh the snapshot.")
        return

    selected: list[str] = []
    columns = st.columns(2)
    for index, company in enumerate(matches):
        with columns[index % 2]:
            with st.container(border=True):
                header_cols = st.columns((5, 1))
                header_cols[0].subheader(company.name)
                if header_cols[1].checkbox("Save", key=f"yc-save:{company.slug}", label_visibility="collapsed"):
                    selected.append(company.slug)
                tags = [
                    company.status, company.batch, "Hiring" if company.is_hiring else None,
                    "Top company" if company.top_company else None,
                    f"team {company.team_size}" if company.team_size is not None else None,
                    company.stage,
                ]
                st.caption(" · ".join(tag for tag in tags if tag and tag != "Unknown"))
                if company.industries or company.regions:
                    st.caption(" / ".join((*company.industries, *company.regions))[:160])
                if company.one_liner:
                    st.write(company.one_liner)
                links = st.columns(2)
                links[0].link_button("YC directory page", company.directory_url, use_container_width=True)
                if company.website:
                    links[1].link_button("Company website", company.website, use_container_width=True)

    st.divider()
    if st.button(f"Save {len(selected)} selected to company database", disabled=not selected, type="primary"):
        by_slug = {company.slug: company for company in companies}
        records = [
            CatalogCompany(
                source="YC community API", source_key=by_slug[slug].slug,
                source_url=by_slug[slug].directory_url, name=by_slug[slug].name, company_type="Startup",
                website=by_slug[slug].website, locations=by_slug[slug].locations,
                industry=by_slug[slug].industries[0] if by_slug[slug].industries else None,
                funding_stage=by_slug[slug].stage or "Unknown",
                employee_band=employee_band(by_slug[slug].team_size),
                hiring=by_slug[slug].is_hiring, yc_batch=by_slug[slug].batch,
                summary=by_slug[slug].one_liner,
            )
            for slug in selected if slug in by_slug
        ]
        try:
            count = catalog.import_companies(records)
            st.success(f"Saved {count} research lead(s). Open the company database to review them and connect an official job board.")
        except ValueError as exc:
            st.error(str(exc))
    st.caption("Saved companies become local research leads only; open roles come from a reviewed official job board, never from this directory.")
