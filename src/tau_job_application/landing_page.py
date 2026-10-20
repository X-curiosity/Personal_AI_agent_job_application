"""A small, data-injected public-facing landing page for Co-Apply GPT.

The application keeps job-preparation data local.  This renderer deliberately
does not reach into the database, inspect session state, or make network
requests: its caller supplies a compact snapshot of the local role market and
the callbacks that move a candidate into their private workspace.  That keeps
the landing view reusable for the normal Streamlit route, a demo route, and
tests while avoiding a second source of truth for career data.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from html import escape

import streamlit as st

from tau_job_application.company_branding import validate_public_https_logo_url


LandingAction = Callable[[], None]


@dataclass(frozen=True, slots=True)
class LandingOpportunity:
    """A compact, display-only official-opening preview.

    ``logo_url`` is optional and must point to a public HTTPS image to render.
    It is intentionally a presentation field: source URLs and application
    actions remain in the private Role Market, where their provenance is
    visible to the candidate.
    """

    title: str
    company: str
    location: str | None = None
    workplace_type: str | None = None
    source_label: str | None = None
    relevance: int | None = None
    logo_url: str | None = None


@dataclass(frozen=True, slots=True)
class LandingPageData:
    """The locally derived facts needed to render the product landing page."""

    role_pages: int = 0
    official_openings: int = 0
    shortlisted_openings: int = 0
    companies: int = 0
    latest_role_title: str | None = None
    latest_refreshed_at: str | None = None
    opportunities: tuple[LandingOpportunity, ...] = ()


def build_landing_page_data(
    *,
    role_pages: int,
    official_openings: int,
    shortlisted_openings: int,
    companies: int,
    latest_role_title: str | None = None,
    latest_refreshed_at: str | None = None,
    opportunities: Sequence[LandingOpportunity] = (),
) -> LandingPageData:
    """Build a presentation snapshot while keeping counters non-negative.

    The caller is responsible for deriving counts from its local stores.  The
    renderer applies no ranking and makes no claim about a role's availability
    beyond the supplied official-board snapshot.
    """

    return LandingPageData(
        role_pages=max(0, int(role_pages)),
        official_openings=max(0, int(official_openings)),
        shortlisted_openings=max(0, int(shortlisted_openings)),
        companies=max(0, int(companies)),
        latest_role_title=_optional_text(latest_role_title),
        latest_refreshed_at=_optional_text(latest_refreshed_at),
        opportunities=tuple(opportunities),
    )


def safe_https_image_url(value: str | None) -> str | None:
    """Return an image URL safe to put in an ``img`` element, if any.

    A browser, rather than the Streamlit server, loads these images.  Requiring
    HTTPS, a host, no credentials, and a modest URL length prevents HTML-URL
    schemes and avoids accidentally rendering a data URI or a local resource.
    This is deliberately not a verification claim about ownership of a logo.
    """

    if not isinstance(value, str) or not (candidate := value.strip()) or len(candidate) > 2_048:
        return None
    try:
        return validate_public_https_logo_url(candidate)
    except ValueError:
        return None


def render_landing_page(
    data: LandingPageData,
    *,
    on_enter_workspace: LandingAction | None = None,
    on_open_role_market: LandingAction | None = None,
    key_prefix: str = "campaign-landing",
) -> None:
    """Render the standalone dynamic landing page.

    ``on_enter_workspace`` and ``on_open_role_market`` are intentionally
    injected.  For example, a caller can update ``st.query_params`` and rerun
    without this module needing to know application routing or storage.
    """

    st.markdown(_LANDING_STYLES, unsafe_allow_html=True)
    st.markdown(_hero_markup(data), unsafe_allow_html=True)

    primary, secondary = st.columns((1.35, 1))
    with primary:
        st.button(
            "Enter Co-Apply GPT",
            type="primary",
            key=f"{key_prefix}:enter-workspace",
            on_click=on_enter_workspace,
            disabled=on_enter_workspace is None,
            help=(
                "This route needs the application workspace callback."
                if on_enter_workspace is None
                else None
            ),
            use_container_width=True,
        )
    with secondary:
        st.button(
            "See live role markets",
            key=f"{key_prefix}:open-role-market",
            on_click=on_open_role_market,
            disabled=on_open_role_market is None,
            help=(
                "A saved role market will open in Co-Apply GPT."
                if on_open_role_market is None
                else None
            ),
            use_container_width=True,
        )

    st.markdown(
        "<div class=\"campaign-section-kicker\">What is live on this device</div>",
        unsafe_allow_html=True,
    )
    metric_columns = st.columns(4)
    metrics = (
        (data.role_pages, "job workspaces", "roles you are preparing for"),
        (data.official_openings, "official openings", "from your latest role market"),
        (data.shortlisted_openings, "saved or tracking", "local shortlist choices"),
        (data.companies, "companies", "represented in the latest market"),
    )
    for column, (value, label, note) in zip(metric_columns, metrics, strict=True):
        with column:
            st.markdown(_metric_markup(value, label, note), unsafe_allow_html=True)

    _render_opportunity_pulse(data, key_prefix=key_prefix)
    _render_how_it_works()
    st.caption(
        "Live counters come from local snapshots of public employer boards. "
        "They do not mean an application was submitted, a person was contacted, "
        "or a role is still available; verify each role on its official listing."
    )


def _render_opportunity_pulse(data: LandingPageData, *, key_prefix: str) -> None:
    """Show a small, factual preview instead of duplicating the full Role Market."""

    st.markdown(
        "<div class=\"campaign-section-kicker campaign-pulse-kicker\">Opportunity pulse</div>",
        unsafe_allow_html=True,
    )
    role = escape(data.latest_role_title or "your next role")
    refresh = _format_refreshed_at(data.latest_refreshed_at)
    if data.opportunities:
        intro = f"A local preview for <strong>{role}</strong>"
        if refresh:
            intro += f" · last refreshed {escape(refresh)}"
        st.markdown(f"<p class=\"campaign-pulse-copy\">{intro}</p>", unsafe_allow_html=True)
        columns = st.columns(min(3, len(data.opportunities)))
        for column, opening in zip(columns, data.opportunities[:3], strict=False):
            with column:
                st.markdown(_opportunity_markup(opening), unsafe_allow_html=True)
        if len(data.opportunities) > 3:
            st.caption(f"Plus {len(data.opportunities) - 3} more matching official openings in the Role Market.")
    else:
        st.markdown(
            "<section class=\"campaign-empty-pulse\">"
            "<strong>Your live role market will appear here.</strong><br>"
            "Choose a role, review its lookalike titles, and refresh the registered public employer feeds when you are ready."
            "</section>",
            unsafe_allow_html=True,
        )


def _render_how_it_works() -> None:
    st.markdown(
        "<div class=\"campaign-section-kicker campaign-how-kicker\">A calmer way to run a search</div>",
        unsafe_allow_html=True,
    )
    steps = (
        ("01", "Explore the market", "Build one role page and see matching jobs from the public employer feeds you chose."),
        ("02", "Prove the fit", "Refine your evidence, shape one or two credible proof projects, and keep claims grounded."),
        ("03", "Practice the conversation", "Use the job workspace to rehearse the interview once you decide a role is worth pursuing."),
    )
    columns = st.columns(3)
    for column, (number, title, description) in zip(columns, steps, strict=True):
        with column:
            st.markdown(
                "<section class=\"campaign-step-card\">"
                f"<div class=\"campaign-step-number\">{number}</div>"
                f"<h3>{escape(title)}</h3>"
                f"<p>{escape(description)}</p>"
                "</section>",
                unsafe_allow_html=True,
            )


def _hero_markup(data: LandingPageData) -> str:
    title = data.latest_role_title or "your next role"
    role_detail = (
        f"Your most recent market is for <strong>{escape(title)}</strong>. "
        "Keep the research, proof, and interview preparation together."
        if data.latest_role_title
        else "Give the workspace a role to explore, then turn scattered job hunting into one focused campaign."
    )
    return (
        "<section class=\"campaign-landing-hero\">"
        "<div class=\"campaign-hero-orbit campaign-hero-orbit-one\"></div>"
        "<div class=\"campaign-hero-orbit campaign-hero-orbit-two\"></div>"
        "<div class=\"campaign-hero-content\">"
        "<div class=\"campaign-eyebrow\">Co-Apply GPT</div>"
        "<h1>Run your job search like a thoughtful campaign.</h1>"
        f"<p>{role_detail}</p>"
        "<div class=\"campaign-hero-promise\">"
        "Official openings · evidence-first preparation · practice before the interview"
        "</div>"
        "</div>"
        "</section>"
    )


def _metric_markup(value: int, label: str, note: str) -> str:
    return (
        "<section class=\"campaign-metric\">"
        f"<div class=\"campaign-metric-value\">{value}</div>"
        f"<div class=\"campaign-metric-label\">{escape(label)}</div>"
        f"<div class=\"campaign-metric-note\">{escape(note)}</div>"
        "</section>"
    )


def _opportunity_markup(opening: LandingOpportunity) -> str:
    """Render display facts with HTML escaping and a managed-logo fallback."""

    company = _text_or_fallback(opening.company, "Company")
    title = _text_or_fallback(opening.title, "Role title")
    items = [item for item in (opening.location, opening.workplace_type, opening.source_label) if _optional_text(item)]
    metadata = "".join(
        f'<span class="campaign-opportunity-pill">{escape(item.strip())}</span>'
        for item in items
    )
    relevance = ""
    if opening.relevance is not None:
        relevance_value = max(0, min(100, int(opening.relevance)))
        relevance = (
            "<div class=\"campaign-opportunity-score\">"
            f"<b>{relevance_value}</b><span>role relevance</span></div>"
        )
    monogram = _company_monogram(company)
    logo_url = safe_https_image_url(opening.logo_url)
    image = (
        f'<img src="{escape(logo_url, quote=True)}" alt="{escape(company, quote=True)} logo" '
        'loading="lazy" referrerpolicy="no-referrer">'
        if logo_url
        else ""
    )
    return (
        "<section class=\"campaign-opportunity-card\">"
        "<div class=\"campaign-opportunity-heading\">"
        "<div class=\"campaign-opportunity-logo\">"
        f"<span aria-hidden=\"true\">{escape(monogram)}</span>{image}</div>"
        "<div>"
        f"<h3>{escape(title)}</h3>"
        f"<p>{escape(company)}</p>"
        "</div>"
        "</div>"
        f"<div class=\"campaign-opportunity-meta\">{metadata}</div>"
        f"{relevance}"
        "</section>"
    )


def _optional_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _text_or_fallback(value: str | None, fallback: str) -> str:
    return _optional_text(value) or fallback


def _company_monogram(name: str) -> str:
    words = [word for word in name.replace("&", " ").split() if word]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return f"{words[0][0]}{words[1][0]}".upper()


def _format_refreshed_at(value: str | None) -> str | None:
    if not (timestamp := _optional_text(value)):
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp
    return parsed.strftime("%-d %b %Y")


_LANDING_STYLES = """
<style>
.campaign-landing-hero {position:relative; overflow:hidden; isolation:isolate; background:linear-gradient(122deg,#1F1B16 0%,#1F1B16 57%,#4A4238 100%); border-radius:22px; padding:clamp(2rem,5vw,4.15rem) clamp(1.45rem,6vw,5.5rem); box-shadow:0 19px 45px rgba(23,58,49,.18); margin:.1rem 0 1.05rem;}
.campaign-hero-content {position:relative; z-index:1; max-width:790px;}
.campaign-eyebrow {color:#E6DFD1; font-weight:750; letter-spacing:.14em; text-transform:uppercase; font-size:.72rem; margin-bottom:.7rem;}
.campaign-landing-hero h1 {color:#FFFAF3; font-size:clamp(2.1rem,5vw,4.35rem); max-width:850px; line-height:1.02; letter-spacing:-.045em; margin:0 0 1rem;}
.campaign-landing-hero p {color:#E6DFD1; font-size:clamp(1rem,1.7vw,1.2rem); line-height:1.5; margin:0; max-width:720px;}
.campaign-hero-promise {display:inline-block; color:#FFFAF3; border:1px solid rgba(255,255,255,.35); border-radius:999px; padding:.44rem .78rem; margin-top:1.35rem; background:rgba(14,39,32,.18); font-size:.81rem;}
.campaign-hero-orbit {position:absolute; border:1px solid rgba(255,250,243,.37); border-radius:50%; z-index:0;}
.campaign-hero-orbit-one {width:360px; height:360px; right:-132px; top:-132px; box-shadow:0 0 0 36px rgba(255,250,243,.06),0 0 0 78px rgba(255,250,243,.04);}
.campaign-hero-orbit-two {width:175px; height:175px; right:18%; bottom:-118px; border-color:rgba(216,229,215,.25);}
.campaign-section-kicker {font-size:.74rem; letter-spacing:.13em; text-transform:uppercase; color:#655D52; font-weight:800; margin:1.75rem 0 .56rem;}
.campaign-metric {height:100%; background:rgba(255,255,252,.84); border:1px solid #E6DFD1; border-radius:15px; padding:1rem 1rem .9rem; box-shadow:0 5px 16px rgba(31,27,22,.045);}
.campaign-metric-value {color:#1F1B16; font-size:clamp(1.55rem,3vw,2.25rem); line-height:1; font-weight:790; letter-spacing:-.035em;}
.campaign-metric-label {color:#1F1B16; font-size:.85rem; font-weight:700; margin-top:.45rem;}
.campaign-metric-note {color:#736A5E; font-size:.74rem; line-height:1.3; margin-top:.18rem;}
.campaign-pulse-kicker {margin-top:2rem; margin-bottom:.25rem;}
.campaign-pulse-copy {color:#655D52; margin:.05rem 0 .75rem;}
.campaign-empty-pulse {background:#F6F2EA; color:#655D52; border:1px solid #E6DFD1; border-radius:14px; padding:1rem 1.1rem; line-height:1.45;}
.campaign-opportunity-card {height:100%; min-height:175px; background:rgba(255,255,252,.86); border:1px solid #E6DFD1; border-radius:15px; padding:1rem; box-shadow:0 5px 16px rgba(31,27,22,.045);}
.campaign-opportunity-heading {display:flex; gap:.7rem; align-items:flex-start;}
.campaign-opportunity-logo {position:relative; flex:none; display:grid; place-items:center; width:40px; height:40px; overflow:hidden; border-radius:11px; border:1px solid #E6DFD1; color:#1F1B16; font-size:.74rem; font-weight:800; letter-spacing:.04em; background:linear-gradient(145deg,#F3EEE6,#E6DFD1);}
.campaign-opportunity-logo img {position:absolute; inset:0; width:100%; height:100%; object-fit:contain; padding:4px;}
.campaign-opportunity-card h3 {color:#1F1B16; font-size:.96rem; line-height:1.22; margin:.05rem 0 .18rem;}
.campaign-opportunity-card p {color:#655D52; font-size:.82rem; margin:0;}
.campaign-opportunity-meta {display:flex; gap:.3rem; flex-wrap:wrap; margin-top:.8rem;}
.campaign-opportunity-pill {display:inline-block; border-radius:999px; padding:.18rem .45rem; background:#F1ECE3; border:1px solid #E6DFD1; color:#655D52; font-size:.68rem; line-height:1.2;}
.campaign-opportunity-score {display:flex; align-items:baseline; gap:.3rem; color:#1F1B16; margin-top:.8rem;}
.campaign-opportunity-score b {font-size:1.1rem;}
.campaign-opportunity-score span {font-size:.67rem; color:#736A5E; text-transform:uppercase; letter-spacing:.05em;}
.campaign-how-kicker {margin-top:2.1rem;}
.campaign-step-card {height:100%; background:rgba(255,255,252,.68); border-top:3px solid #736A5E; border-radius:0 14px 14px 14px; padding:1rem 1.05rem;}
.campaign-step-number {font-size:.7rem; font-weight:800; letter-spacing:.12em; color:#736A5E;}
.campaign-step-card h3 {color:#1F1B16; margin:.36rem 0; font-size:1rem;}
.campaign-step-card p {color:#655D52; font-size:.84rem; line-height:1.42; margin:0;}
@media (max-width: 700px) {.campaign-landing-hero {padding:2.05rem 1.35rem; border-radius:17px;}.campaign-hero-promise {border-radius:12px;}.campaign-hero-orbit-one {right:-215px;}.campaign-metric {margin-bottom:.35rem;}}
</style>
"""
