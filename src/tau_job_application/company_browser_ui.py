"""Portfolio-style company browser: one card list, two company universes.

Every role page embeds this browser. The user chooses between **Startups**
(the local YC directory snapshot) and **Big companies** (the local Global
Capital Atlas snapshot) — there is no separate YC section. Cards follow the
reference portfolio layout: real logo (opt-in, with a monogram fallback),
bold name, one-line description, and a muted meta line. Entries are local
research leads, never vacancy claims; snapshots refresh only on explicit
action.
"""
from __future__ import annotations

from html import escape
from urllib.parse import urlparse

import streamlit as st

from tau_job_application.capital_atlas import (
    VALUE_THRESHOLDS,
    AtlasFilters,
    atlas_facets,
    fetch_atlas_companies,
    to_catalog_company,
)
from tau_job_application.company_catalog import CatalogCompany, employee_band
from tau_job_application.yc_directory import (
    YC_STATUSES,
    YCFilters,
    directory_facets,
    fetch_yc_directory,
)

_CB_STYLE = """
<style>
.cb-card {display:flex; gap:14px; align-items:flex-start; padding:16px 4px 14px; border-bottom:1px solid #e7e2d3;}
.cb-mark {position:relative; flex:none; width:46px; height:46px; border-radius:11px; overflow:hidden;
          background:#efece1; border:1px solid #e0dac6; display:grid; place-items:center;}
.cb-monogram {font-weight:750; color:#565138; font-size:.92rem; letter-spacing:.03em;}
.cb-mark img {position:absolute; inset:0; width:100%; height:100%; object-fit:contain; background:#fff; padding:5px;}
.cb-text h3 {margin:0; font-size:1.06rem; line-height:1.2; color:#1c2b23; font-weight:700;}
.cb-text p {margin:.18rem 0 .32rem; color:#414c43; font-size:.9rem; line-height:1.35;}
.cb-text small {color:#8b8571; font-size:.78rem; letter-spacing:.02em;}
</style>
"""


def _domain_logo_url(website: str | None) -> str | None:
    """Third-party logo lookup by domain; rendered only after explicit opt-in."""

    host = urlparse(website).hostname if website else None
    if not host:
        return None
    return f"https://logo.clearbit.com/{host.removeprefix('www.')}"


def _card_html(name: str, description: str | None, meta: str, logo_url: str | None, *, load_logos: bool) -> str:
    monogram = escape("".join(part[0] for part in name.split()[:2]).upper() or "?")
    image = ""
    if load_logos and logo_url:
        image = f'<img src="{escape(logo_url, quote=True)}" alt="" loading="lazy" onerror="this.remove()">'
    return (
        f'<div class="cb-card"><div class="cb-mark"><span class="cb-monogram">{monogram}</span>{image}</div>'
        f'<div class="cb-text"><h3>{escape(name)}</h3><p>{escape(description or "")}</p>'
        f"<small>{escape(meta)}</small></div></div>"
    )


def _save_button(records: list[CatalogCompany], catalog, key_prefix: str) -> None:
    if not records:
        return
    if st.button(
        f"Save {len(records)} selected to company database",
        type="primary", key=f"{key_prefix}:save",
    ):
        try:
            count = catalog.import_companies(records)
            st.success(f"Saved {count} research lead(s). Open the company database to review them and connect an official job board.")
        except ValueError as exc:
            st.error(str(exc))


def _startup_browser(api, key_prefix: str) -> None:
    store = api._yc_directory_store()
    catalog = api._company_catalog_store()
    snapshot = store.snapshot()
    header = st.columns((3, 1))
    header[0].caption(
        f"Startup snapshot: {snapshot['record_count']} YC companies · refreshed {str(snapshot['refreshed_at'])[:16].replace('T', ' ')} UTC"
        if snapshot else "No startup snapshot yet."
    )
    if header[1].button("Refresh startups", key=f"{key_prefix}:yc-refresh", use_container_width=True):
        try:
            with st.spinner("Fetching the public yc-oss directory once…"):
                count = store.refresh(fetch_yc_directory())
            st.success(f"Stored {count} public company records.")
            st.rerun()
        except (RuntimeError, ValueError):
            st.error("The directory could not be refreshed. The previous snapshot was kept; try again later.")
    if snapshot is None:
        st.info("Refresh the startup snapshot once to start browsing. Nothing is fetched until you do.")
        return

    companies = store.companies()
    facets = directory_facets(companies)
    row = st.columns(4)
    statuses = row[0].multiselect("Status", list(YC_STATUSES), default=["Active"], key=f"{key_prefix}:yc-status")
    hiring_only = row[1].checkbox("Hiring only", value=True, key=f"{key_prefix}:yc-hiring")
    batches = row[2].multiselect("Batch", facets["batches"], key=f"{key_prefix}:yc-batch")
    limit = row[3].selectbox("Max results", [12, 24, 50, 100, 200], index=1, key=f"{key_prefix}:yc-limit")
    row = st.columns(4)
    industries = row[0].multiselect("Industry", facets["industries"], key=f"{key_prefix}:yc-industry")
    regions = row[1].multiselect("Region", facets["regions"], key=f"{key_prefix}:yc-region")
    query = row[2].text_input("Search", placeholder="name, description, tag", max_chars=200, key=f"{key_prefix}:yc-query")
    load_logos = row[3].checkbox(
        "Load remote company logos", key=f"{key_prefix}:yc-logos",
        help="Off by default: remote logos share your IP address with the logo host.",
    )

    matches = store.search(YCFilters(
        statuses=tuple(statuses), hiring_only=hiring_only, batches=tuple(batches),
        industries=tuple(industries), regions=tuple(regions), query=query, limit=int(limit),
    ))
    st.caption(f"{len(matches)} matching startups · a directory entry, even flagged hiring, is never proof of an open vacancy")
    if not matches:
        st.info("No startups match these filters in the current snapshot. Broaden the filters or refresh.")
        return

    selected: list[str] = []
    columns = st.columns(2)
    for index, company in enumerate(matches):
        with columns[index % 2]:
            card_cols = st.columns((11, 1))
            meta = " · ".join(part for part in (
                company.batch, company.status,
                "Hiring" if company.is_hiring else None,
                company.stage if company.stage and company.stage != "Unknown" else None,
            ) if part)
            card_cols[0].markdown(
                _card_html(company.name, company.one_liner, meta, company.logo_url, load_logos=load_logos),
                unsafe_allow_html=True,
            )
            if card_cols[1].checkbox("Save", key=f"{key_prefix}:yc-save:{company.slug}", label_visibility="collapsed"):
                selected.append(company.slug)

    by_slug = {company.slug: company for company in companies}
    _save_button([
        CatalogCompany(
            source="YC community API", source_key=by_slug[slug].slug,
            source_url=by_slug[slug].directory_url, name=by_slug[slug].name, company_type="Startup",
            website=by_slug[slug].website, logo_url=by_slug[slug].logo_url, locations=by_slug[slug].locations,
            industry=by_slug[slug].industries[0] if by_slug[slug].industries else None,
            funding_stage=by_slug[slug].stage or "Unknown",
            employee_band=employee_band(by_slug[slug].team_size),
            hiring=by_slug[slug].is_hiring, yc_batch=by_slug[slug].batch, summary=by_slug[slug].one_liner,
        )
        for slug in selected if slug in by_slug
    ], catalog, key_prefix)


def _big_company_browser(api, key_prefix: str) -> None:
    store = api._atlas_store()
    catalog = api._company_catalog_store()
    snapshot = store.snapshot()
    header = st.columns((3, 1))
    header[0].caption(
        f"Big-company snapshot: {snapshot['record_count']} companies valued $10B+ · refreshed {str(snapshot['refreshed_at'])[:16].replace('T', ' ')} UTC"
        if snapshot else "No big-company snapshot yet."
    )
    if header[1].button("Refresh big companies", key=f"{key_prefix}:atlas-refresh", use_container_width=True):
        try:
            with st.spinner("Reading the Global Capital Atlas page asset…"):
                count = store.refresh(fetch_atlas_companies())
            st.success(f"Stored {count} public company records.")
            st.rerun()
        except (RuntimeError, ValueError):
            st.error("The atlas could not be refreshed. The previous snapshot was kept; try again later.")
    if snapshot is None:
        st.info("Refresh the big-company snapshot once to start browsing. Nothing is fetched until you do.")
        return

    companies = store.companies()
    facets = atlas_facets(companies)
    row = st.columns(4)
    minimum = row[0].selectbox(
        "Minimum value", list(VALUE_THRESHOLDS), index=0,
        format_func=lambda value: f"${value}B+" if value < 1000 else "$1T+",
        key=f"{key_prefix}:atlas-min",
    )
    ownership = row[1].multiselect("Type", facets["ownership"], key=f"{key_prefix}:atlas-type")
    industries = row[2].multiselect("Industry", facets["industries"], key=f"{key_prefix}:atlas-industry")
    limit = row[3].selectbox("Max results", [12, 24, 50, 100, 200], index=1, key=f"{key_prefix}:atlas-limit")
    row = st.columns(4)
    countries = row[0].multiselect("Country", facets["countries"], key=f"{key_prefix}:atlas-country")
    query = row[1].text_input("Search", placeholder="name, description, ticker", max_chars=200, key=f"{key_prefix}:atlas-query")
    load_logos = row[2].checkbox(
        "Load remote company logos", key=f"{key_prefix}:atlas-logos",
        help="Off by default: remote logos share your IP address with the logo host.",
    )

    matches = store.search(AtlasFilters(
        min_value_billions=int(minimum), ownership=tuple(ownership), industries=tuple(industries),
        countries=tuple(countries), query=query, limit=int(limit),
    ))
    st.caption(f"{len(matches)} matching companies · a valuation is never a vacancy signal")
    if not matches:
        st.info("No companies match these filters in the current snapshot. Broaden the filters or refresh.")
        return

    selected: list[str] = []
    columns = st.columns(2)
    for index, company in enumerate(matches):
        with columns[index % 2]:
            card_cols = st.columns((11, 1))
            meta = " · ".join(part for part in (company.formatted_value, company.ownership, company.country, company.ticker) if part)
            description = (company.description or "")[:160].strip() or None
            card_cols[0].markdown(
                _card_html(company.name, description, meta, _domain_logo_url(company.website), load_logos=load_logos),
                unsafe_allow_html=True,
            )
            if card_cols[1].checkbox("Save", key=f"{key_prefix}:atlas-save:{company.slug}", label_visibility="collapsed"):
                selected.append(company.slug)

    by_slug = {company.slug: company for company in companies}
    _save_button([to_catalog_company(by_slug[slug]) for slug in selected if slug in by_slug], catalog, key_prefix)


def render_company_browser(api, *, role: str | None = None, key_prefix: str = "cb") -> None:
    """One browser, two universes: startups or big companies — no YC section."""

    st.markdown(_CB_STYLE, unsafe_allow_html=True)
    segment = st.segmented_control(
        "Company type", ["Startups", "Big companies"], default="Startups",
        key=f"{key_prefix}:segment",
        help="Startups: the local YC directory snapshot. Big companies: the local Global Capital Atlas snapshot ($10B+).",
    )
    if segment == "Big companies":
        _big_company_browser(api, key_prefix)
    else:
        _startup_browser(api, key_prefix)
    if role:
        st.caption(f"Research leads for your {role} preparation — verify openings on each company's official job board.")
