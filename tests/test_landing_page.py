from tau_job_application.landing_page import (
    LandingOpportunity,
    build_landing_page_data,
    safe_https_image_url,
)
from streamlit.testing.v1 import AppTest


def test_landing_data_keeps_counts_non_negative_and_preserves_preview():
    preview = LandingOpportunity(
        title="Platform Engineer",
        company="Example Co",
        location="Paris, France",
        relevance=87,
    )

    data = build_landing_page_data(
        role_pages=-1,
        official_openings=3,
        shortlisted_openings=-2,
        companies=2,
        latest_role_title="  Platform Engineer ",
        opportunities=[preview],
    )

    assert data.role_pages == 0
    assert data.official_openings == 3
    assert data.shortlisted_openings == 0
    assert data.companies == 2
    assert data.latest_role_title == "Platform Engineer"
    assert data.opportunities == (preview,)


def test_landing_logo_urls_accept_only_credential_free_https_urls():
    assert safe_https_image_url("https://assets.example/logo.svg") == "https://assets.example/logo.svg"
    assert safe_https_image_url("http://assets.example/logo.svg") is None
    assert safe_https_image_url("data:image/svg+xml,example") is None
    assert safe_https_image_url("https://user:secret@assets.example/logo.svg") is None
    assert safe_https_image_url("https://127.0.0.1/logo.svg") is None
    assert safe_https_image_url("javascript:alert(1)") is None


def test_landing_renderer_uses_injected_callbacks_and_escapes_preview_text():
    app = AppTest.from_string(
        '''
import streamlit as st
from tau_job_application.landing_page import (
    LandingOpportunity,
    build_landing_page_data,
    render_landing_page,
)


def enter_workspace():
    st.session_state["entered"] = True


def open_market():
    st.session_state["market_opened"] = True


data = build_landing_page_data(
    role_pages=2,
    official_openings=4,
    shortlisted_openings=1,
    companies=3,
    latest_role_title="Platform Engineer",
    opportunities=[
        LandingOpportunity(
            title="<script>untrusted</script>",
            company="Example Co",
            location="Paris, France",
            source_label="Official board",
            relevance=88,
            logo_url="javascript:alert(1)",
        )
    ],
)
render_landing_page(data, on_enter_workspace=enter_workspace, on_open_role_market=open_market)
''',
        default_timeout=30,
    ).run()

    assert not app.exception
    html = " ".join(item.value for item in app.markdown if item.value)
    assert "Run your job search like a thoughtful campaign" in html
    assert "&lt;script&gt;untrusted&lt;/script&gt;" in html
    assert "javascript:alert" not in html
    next(button for button in app.button if button.label == "Enter Co-Apply GPT").click()
    app.run()
    assert app.session_state["entered"]
    next(button for button in app.button if button.label == "See live role markets").click()
    app.run()
    assert app.session_state["market_opened"]
