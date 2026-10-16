"""Optional multi-agent console: one deterministic coordinator, bounded specialists.

The console is disabled unless model credentials are exported and the user
explicitly consents to sending their request text to the configured provider.
Specialist tool results (local directory/profile data) are also part of the
provider context once a run starts. Routing, budgets, and the action trace are
deterministic and visible; canonical records change only through typed tools.
"""
from __future__ import annotations

import asyncio
import os

import streamlit as st

from tau_job_application.agents import (
    AGENT_SPECS,
    SPECS_BY_KEY,
    TeamDependencies,
    route_request,
)

_HISTORY_LIMIT = 20


def _coordinator(api, track: str):
    from tau_ai import OpenAICompatibleConfig, OpenAICompatibleProvider

    from tau_job_application.agents import TeamCoordinator as Coordinator

    provider = OpenAICompatibleProvider(OpenAICompatibleConfig(api_key=os.environ["OPENAI_API_KEY"]))
    return Coordinator(
        provider=provider,
        model=os.environ["MODEL_NAME"],
        deps=TeamDependencies(
            yc_store=api._yc_directory_store(),
            catalog_store=api._company_catalog_store(),
            residency_store=api._residency_store(),
            workspace_id=track,
        ),
    )


def render_agents_console(api, track: str) -> None:
    st.markdown(
        '<div class="section-kicker">Optional, bounded, visible</div><h1>Agent team</h1>',
        unsafe_allow_html=True,
    )
    st.write(
        "One coordinator routes your request to a single specialist (company scout, eligibility advisor, "
        "or application prep), each limited to its own typed tools, a turn limit, and a tool-call budget."
    )
    st.caption(
        "Specialists never message anyone, submit applications, scrape LinkedIn/X, or invent facts. "
        "Scores, eligibility rules, and stored records stay deterministic and outside the chat transcript."
    )

    if not (os.environ.get("OPENAI_API_KEY") and os.environ.get("MODEL_NAME")):
        st.info(
            "The agent team is optional and currently disabled. Export OPENAI_API_KEY and MODEL_NAME in the "
            "shell that launches this app, then reload. Everything else in the workspace works without them."
        )
        return

    with st.expander("What gets sent to the model provider?", expanded=False):
        st.write(
            "Your request text, the specialist's instructions, and the results of any tool it calls "
            "(for example matching directory records or your saved residency profile). Nothing is sent "
            "until you tick the consent box and press Run. Conversation history below stays local."
        )

    consent = st.checkbox(
        "I consent to sending my request and its local tool results to the configured model provider for this run.",
        key=f"agents-consent:{track}",
    )

    labels = {"Automatic routing (recommended)": None}
    labels.update({f"{spec.name}: {spec.description}": spec.key for spec in AGENT_SPECS})
    choice = st.selectbox("Specialist", list(labels), key=f"agents-specialist:{track}")
    request = st.text_area(
        "Your request", max_chars=4000, key=f"agents-request:{track}",
        placeholder="Examples: “Which active YC startups in fintech are hiring?” · “I live in France and want to apply in Canada: what do I need?”",
    )

    preview = route_request(request) if request.strip() and labels[choice] is None else None
    if preview:
        st.caption(f"Routing preview → **{SPECS_BY_KEY[preview.agent_key].name}** ({preview.reason})")

    if st.button("Run specialist", type="primary", disabled=not consent or not request.strip()):
        with st.spinner("Running the bounded specialist…"):
            result = asyncio.run(_coordinator(api, track).run(request, agent_key=labels[choice]))
        history = st.session_state.setdefault(f"agents-history:{track}", [])
        history.append({"request": request, "result": result})
        del history[: max(0, len(history) - _HISTORY_LIMIT)]

    history = st.session_state.get(f"agents-history:{track}", [])
    for entry in reversed(history):
        result = entry["result"]
        with st.container(border=True):
            st.caption(f"You · {entry['request'][:160]}")
            st.markdown(f"**{result.agent_name}** · {result.routing.reason}")
            if result.error:
                st.error(result.error)
            if result.text:
                st.write(result.text)
            if result.tool_trace:
                with st.expander(f"Action trace · {len(result.tool_trace)} tool call(s) · {result.turns} turn(s)", expanded=False):
                    for call in result.tool_trace:
                        status = "✓" if call.ok else ("✗" if call.ok is False else "…")
                        st.markdown(f"- {status} `{call.tool_name}` `{call.arguments}`")
                        if call.message:
                            st.caption(call.message[:300])
            if result.blocked_tool_calls:
                st.caption(f"{result.blocked_tool_calls} tool call(s) were blocked by the run budget.")
    if not history:
        st.info("No runs yet. The team works one bounded specialist at a time; every action it takes is listed above.")
