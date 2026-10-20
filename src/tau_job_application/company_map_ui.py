"""Hiring-company map: every company type, one honest pin each.

Adapted from the startupmap.one map patterns (docs/STARTUPMAP_RE_NOTES.md):
pins colored by company stage (early/growth/scale-up/big — the generalization
beyond startups), a verified-live visual distinction, stage/industry/signal
filters, and an optional "my match answers" filter. Deliberate differences:
no Mapbox token (Carto basemap, like the app's other maps), no supercluster
(the bounded ~1k pins do not need it), and country-level pins are rendered as
large soft discs because the gazetteer never invents city precision.
"""
from __future__ import annotations

import pydeck as pdk
import streamlit as st

from tau_job_application.city_coordinates import geocode_location
from tau_job_application.match_onboarding import (
    STAGE_GROUPS,
    MatchPreferenceStore,
    MatchPreferences,
    company_matches,
    gather_match_candidates,
)

STAGE_COLORS: dict[str, list[int]] = {
    "early": [22, 115, 76, 235],
    "growth": [61, 90, 116, 235],
    "scaleup": [116, 97, 58, 235],
    "big": [94, 84, 68, 235],
}
STAGE_LABELS = {group: label for group, label, _ in STAGE_GROUPS}


def build_map_points(candidates, prefs: MatchPreferences | None = None) -> tuple[list[dict], list[str]]:
    """One point per mappable company; names without coordinates are returned
    separately and counted openly in the UI rather than silently dropped."""

    points: list[dict] = []
    unmapped: list[str] = []
    for facts in candidates:
        if prefs is not None and not company_matches(facts, prefs):
            continue
        geocode = geocode_location(facts.locations)
        if geocode is None:
            unmapped.append(facts.name)
            continue
        live = facts.hiring_signal == "live_openings"
        city_level = geocode.precision == "city"
        points.append({
            "name": facts.name,
            "stage": STAGE_LABELS[facts.stage_group],
            "signal": "Live official board" if live else "Directory flag (unverified)",
            "industry": facts.industry or "n/a",
            "location": facts.locations or "n/a",
            "precision": f"{geocode.precision}-level ({geocode.label})",
            "latitude": geocode.latitude,
            "longitude": geocode.longitude,
            "color": STAGE_COLORS[facts.stage_group] if city_level else [*STAGE_COLORS[facts.stage_group][:3], 90],
            "radius": 26_000 if live else 16_000 if city_level else 90_000,
        })
    return points, unmapped


def render_company_map(api, track: str) -> None:
    """The map section inside the Companies view."""

    candidates = gather_match_candidates(api._hiring_index_store(), api._company_catalog_store())
    st.divider()
    st.markdown('<div class="section-kicker">Where hiring is happening</div><h2>Hiring company map</h2>', unsafe_allow_html=True)
    st.caption(
        "One pin per hiring company from the local index and catalogue, colored by company stage. "
        "Live-board companies get a stronger pin; directory flags are unverified. "
        "Locations are geocoded offline from directory text: city-level pins are exact, soft discs are country-level estimates."
    )
    if not candidates:
        st.info("Build the hiring index or import companies first; the map reads the same local data.")
        return

    store = MatchPreferenceStore(api.WORKSPACES.path)
    saved = store.load(track)
    use_match = st.checkbox(
        "Filter with my Match me answers",
        key=f"map-match-filter:{track}",
        disabled=saved is None,
        help="Applies your stage, industry and location answers from the Match me flow." if saved
             else "Finish the Match me flow first (career home → Match me · 5 answers).",
    )
    controls = st.columns(4)
    stage_pick = controls[0].multiselect(
        "Stage", list(STAGE_LABELS), default=[], format_func=STAGE_LABELS.get,
        key=f"map-stage:{track}",
    )
    industries = sorted({facts.industry for facts in candidates if facts.industry}, key=str.casefold)
    industry_pick = controls[1].multiselect("Industry", industries[:60], default=[], key=f"map-industry:{track}")
    signal_pick = controls[2].selectbox(
        "Signal", ["All", "Live official board", "Directory flag (unverified)"], key=f"map-signal:{track}"
    )
    search = controls[3].text_input("Company", key=f"map-search:{track}", placeholder="Name contains…")

    prefs = saved if (use_match and saved) else None
    points, unmapped = build_map_points(candidates, prefs)
    points = [
        point for point in points
        if (not stage_pick or point["stage"] in [STAGE_LABELS[group] for group in stage_pick])
        and (not industry_pick or point["industry"] in industry_pick)
        and (signal_pick == "All" or point["signal"] == signal_pick)
        and (not search.strip() or search.strip().casefold() in point["name"].casefold())
    ]

    legend = " · ".join(
        f'<b style="color:rgb({STAGE_COLORS[group][0]},{STAGE_COLORS[group][1]},{STAGE_COLORS[group][2]})">●</b> {label}'
        for group, label, _ in STAGE_GROUPS
    )
    st.markdown(
        f'<div style="font-size:.8rem;color:#4e655a">{legend} &nbsp;·&nbsp; '
        f'{len(points)} pinned · {len(unmapped)} without a mappable location</div>',
        unsafe_allow_html=True,
    )

    if points:
        layer = pdk.Layer(
            "ScatterplotLayer",
            id=f"company-map:{track}",
            data=points,
            get_position=["longitude", "latitude"],
            get_radius="radius",
            get_fill_color="color",
            radius_min_pixels=4,
            radius_max_pixels=26,
            pickable=True,
            auto_highlight=True,
        )
        latitude = sum(point["latitude"] for point in points) / len(points)
        longitude = sum(point["longitude"] for point in points) / len(points)
        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=pdk.ViewState(latitude=latitude, longitude=longitude, zoom=1.1 if len(points) > 3 else 3.4, pitch=0),
            map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
            tooltip={
                "html": "<b>{name}</b><br/>{stage} · {signal}<br/>{industry} · {location}<br/><i>{precision}</i>",
                "style": {"backgroundColor": "#173a31", "color": "#fffef8"},
            },
        )
        st.pydeck_chart(deck, use_container_width=True, height=520, key=f"company-map-chart:{track}")
    else:
        st.info("No company matches these filters on the map. Widen one filter to see pins.")

    with st.expander(f"Pinned companies ({len(points)})", expanded=False):
        st.dataframe(
            [{
                "Company": point["name"], "Stage": point["stage"], "Signal": point["signal"],
                "Industry": point["industry"], "Location": point["location"], "Pin": point["precision"],
            } for point in points],
            hide_index=True, use_container_width=True,
        )
    if unmapped:
        with st.expander(f"Not pinned ({len(unmapped)})", expanded=False):
            st.caption(
                "These companies are remote, list no place, or name a place outside the offline gazetteer. "
                "They stay in the database views below; the map never guesses a coordinate."
            )
            st.write(" · ".join(unmapped[:100]))
