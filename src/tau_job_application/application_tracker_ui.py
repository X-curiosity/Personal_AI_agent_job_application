"""Application list, deadline triage, and candidate-edited timelines."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta
from html import escape
import json
from zoneinfo import ZoneInfo

import streamlit as st

from tau_job_application.application_tracker import (
    ApplicationProgress, ApplicationStage, ApplicationTrackerStore, TrackedApplication,
)


def tracker_today() -> date:
    return datetime.now(ZoneInfo("Europe/Zurich")).date()


def ordered_applications(records, order: str = "Closing soon"):
    """Keep closed applications last; unknown dates never outrank real dates."""
    if order == "Recently changed":
        newest_first = sorted(records, key=lambda row: row.updated_at, reverse=True)
        return sorted(newest_first, key=lambda row: row.progress.stage is ApplicationStage.CLOSED)
    if order == "Company A–Z":
        return sorted(records, key=lambda row: (row.progress.stage is ApplicationStage.CLOSED,
                                               row.opening.company.name.casefold(), row.opening.title.casefold()))
    field = "next_step_on" if order == "Next action" else "deadline"
    return sorted(records, key=lambda row: (
        row.progress.stage is ApplicationStage.CLOSED,
        getattr(row.progress, field) or date.max,
        row.opening.company.name.casefold(), row.id,
    ))


def due_label(value: date, today: date) -> str:
    days = (value - today).days
    if days < 0:
        return f"{abs(days)} day{'s' if days != -1 else ''} overdue"
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    return value.strftime("%d %b %Y").lstrip("0")


def weekly_attention(records, today: date):
    """Surface overdue and near-term work without inventing missing dates."""
    horizon = today + timedelta(days=7)
    active = [row for row in records if row.progress.stage is not ApplicationStage.CLOSED]
    actions = ordered_applications([
        row for row in active
        if row.progress.next_step_on and row.progress.next_step_on <= horizon
    ], "Next action")
    deadlines = ordered_applications([
        row for row in active
        if row.progress.stage in {ApplicationStage.SAVED, ApplicationStage.PREPARING,
                                  ApplicationStage.CONTACTED}
        and row.progress.deadline and today <= row.progress.deadline <= horizon
        and row.progress.availability != "expired"
    ])
    return actions, deadlines


def render_application_tracker(
    store: ApplicationTrackerStore,
    career_track_id: str,
    *,
    track_name: str,
    thread_names: dict[str, str],
    logo_markup: Callable[[str], str],
    on_browse: Callable[[], None],
    on_prepare: Callable[[TrackedApplication], None],
    on_open: Callable[[TrackedApplication], None] | None = None,
) -> None:
    records = store.list_records(career_track_id)
    today = tracker_today()
    st.markdown(_STYLES, unsafe_allow_html=True)
    st.markdown(
        '<div class="section-kicker">Your search, in motion</div>'
        '<h1 class="tracker-title">My applications</h1>'
        f'<p class="tracker-intro">Every saved opportunity in {escape(track_name)}. '
        'Keep the next move clear, from first interest to an offer.</p>', unsafe_allow_html=True,
    )
    notice = st.session_state.pop("tracker-notice", None)
    if notice:
        st.success(notice)
    header = st.columns((3, 1))
    header[0].caption("Progress changes when you record it. Opening an employer page leaves your status unchanged.")
    if header[1].button("Find more roles", type="primary", use_container_width=True):
        on_browse()

    counts = Counter(record.progress.stage for record in records)
    filter_key = f"tracker-stage-filter:{career_track_id}"
    st.caption("Your pipeline · select a stage to see its applications")
    stages = list(ApplicationStage)
    for stage_row in (stages[:4], stages[4:]):
        columns = st.columns(len(stage_row))
        for column, stage in zip(columns, stage_row, strict=True):
            if column.button(f"{stage.label} · {counts[stage]}",
                             key=f"tracker-stage:{career_track_id}:{stage.value}",
                             type="primary" if st.session_state.get(filter_key) == stage.label else "secondary",
                             use_container_width=True):
                st.session_state[filter_key] = stage.label
                st.rerun()
    if not records:
        st.info("Save a role from the Role market to start your application tracker. Your saved advert, notes, and progress will stay together here.")
        st.markdown("**Get started in three steps**")
        st.markdown("1. Find a role you like in the Role market.\n"
                    "2. Select **Save for review** to keep it here.\n"
                    "3. Record your progress and add your next step.")
        return

    due, deadlines = weekly_attention(records, today)
    st.markdown("### Your next seven days")
    action_column, deadline_column = st.columns(2)
    with action_column.container(border=True):
        st.markdown("#### Next actions")
        if not due:
            st.caption("No actions due in the next seven days. Add a next step to any application below.")
        for record in due[:3]:
            st.text(f"{due_label(record.progress.next_step_on, today)} · {record.progress.next_step}\n"
                    f"{record.opening.company.name} · {record.opening.title}")
        if len(due) > 3:
            st.caption(f"{len(due) - 3} more · choose Next action below to see the full queue.")
    with deadline_column.container(border=True):
        st.markdown("#### Closing soon")
        if not deadlines:
            st.caption("No recorded deadlines coming up. Dates are only shown when you add them.")
        for record in deadlines[:3]:
            st.text(f"{due_label(record.progress.deadline, today)} · {record.opening.company.name}\n"
                    f"{record.opening.title}")
        if len(deadlines) > 3:
            st.caption(f"{len(deadlines) - 3} more · choose Closing soon below to see them.")

    st.markdown("### All applications")

    controls = st.columns((2, 1.3, 1.3))
    query = controls[0].text_input("Search applications", placeholder="Company, role, or note").strip().casefold()
    stage_filter = controls[1].selectbox("Application stage", ["All active", "All stages", *(stage.label for stage in ApplicationStage)], key=filter_key)
    order = controls[2].selectbox("Sort applications", ["Closing soon", "Next action", "Recently changed", "Company A–Z"])
    attention_only = st.checkbox("Needs attention in the next seven days", key=f"tracker-attention:{career_track_id}")
    attention_ids = {row.id for row in [*due, *deadlines]}
    filtered = [row for row in records if (
        stage_filter == "All stages"
        or (stage_filter == "All active" and row.progress.stage is not ApplicationStage.CLOSED)
        or stage_filter == row.progress.stage.label
    ) and (not attention_only or row.id in attention_ids) and (not query or query in " ".join((
        row.opening.title, row.opening.company.name, row.progress.next_step, row.progress.notes,
    )).casefold())]
    filtered = ordered_applications(filtered, order)
    st.caption(f"{len(filtered)} of {len(records)} saved applications · deadlines and availability are entered by you.")
    if not filtered:
        st.info("No applications match these filters. Choose All stages to include closed applications.")
    pages = max(1, (len(filtered) + 9) // 10)
    page = st.selectbox("Results page", range(1, pages + 1)) if pages > 1 else 1
    for record in filtered[(page - 1) * 10:page * 10]:
        _application_card(store, career_track_id, record, today, thread_names,
                          logo_markup=logo_markup, on_prepare=on_prepare, on_open=on_open)

    with st.expander("Export your application history"):
        payload = [
            {**row.model_dump(mode="json"),
             "history": [event.model_dump(mode="json") for event in store.history(career_track_id, row.id)]}
            for row in records
        ]
        st.download_button("Download tracker history", json.dumps(payload, ensure_ascii=False, indent=2),
                           file_name="my-applications.json", mime="application/json")


def _application_card(store, career_track_id, record, today, thread_names, *, logo_markup, on_prepare, on_open=None):
    progress, opening = record.progress, record.opening
    key = f"application:{record.id}"
    with st.container(border=True):
        mark, title, status = st.columns((0.6, 4.5, 1.3))
        mark.markdown(logo_markup(opening.company.name), unsafe_allow_html=True)
        title.markdown(
            f'<div class="role-feed-title">{escape(opening.title)}</div>'
            f'<div class="role-feed-company">{escape(opening.company.name)} · '
            f'{escape(opening.location or "Location not listed")}</div>', unsafe_allow_html=True,
        )
        status.markdown(f'<span class="tracker-status {progress.stage.value}">{progress.stage.label}</span>',
                        unsafe_allow_html=True)
        details = []
        if progress.deadline:
            deadline = ("passed " + progress.deadline.strftime("%d %b %Y")
                        if progress.deadline < today else due_label(progress.deadline, today))
            details.append(f"Deadline: {deadline}")
        if progress.availability == "expired":
            details.append("Expired · marked by you")
        elif progress.availability == "open":
            details.append("Open · last checked by you")
        if record.relevance is not None:
            details.append(f"Role relevance when saved: {record.relevance}/100")
        if details:
            st.caption(" · ".join(details))
        if progress.next_step:
            overdue = bool(progress.next_step_on and progress.next_step_on < today
                           and progress.stage is not ApplicationStage.CLOSED)
            st.markdown(f'<div class="tracker-next {"overdue" if overdue else ""}">'
                        f'<b>{"Overdue action" if overdue else "Next step"}</b> · {escape(progress.next_step)}'
                        + (f' <span>· {escape(due_label(progress.next_step_on, today))}</span>'
                           if progress.next_step_on else '') + '</div>', unsafe_allow_html=True)
        if on_open and st.button("Documents, interview & replies", key=f"{key}:open", use_container_width=True):
            on_open(record)
        actions = st.columns(3)
        if opening.canonical_url:
            actions[0].link_button("Open employer page", opening.canonical_url, use_container_width=True)
        if actions[1].button("Prepare this role", key=f"{key}:prepare", use_container_width=True):
            on_prepare(record)
        if progress.stage in {ApplicationStage.SAVED, ApplicationStage.PREPARING, ApplicationStage.CONTACTED}:
            if actions[2].button("I applied", key=f"{key}:applied", use_container_width=True):
                updated = progress.model_copy(update={
                    "stage": ApplicationStage.APPLIED, "stage_on": today,
                    "applied_on": progress.applied_on or today,
                })
                try:
                    store.update(career_track_id, record.id, updated, expected_updated_at=record.updated_at)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state["tracker-notice"] = f"Recorded that you applied to {opening.company.name}."
                    st.rerun()
        with st.expander("Update progress & notes", expanded=False):
            _edit_application(store, career_track_id, record, key)
        with st.expander("History & saved advert", expanded=False):
            st.caption("Saved from: " + thread_names.get(record.thread_id, "Job workspace"))
            st.caption("The original advert is retained even if it leaves the feed. Missing feed results do not automatically mark it expired.")
            for event in store.history(career_track_id, record.id):
                timestamp = event.occurred_at[:10]
                if event.action == "updated":
                    fields = ", ".join(field.replace("_", " ") for field in event.changed_fields)
                    st.text(f"{timestamp} · {event.progress.stage.label} · Updated {fields}")
                    if "next_step" in event.changed_fields or "next_step_on" in event.changed_fields:
                        st.caption("Next step: " + (event.progress.next_step or "Cleared") +
                                   (f" · {event.progress.next_step_on}" if event.progress.next_step_on else ""))
                    if "notes" in event.changed_fields:
                        st.text(event.progress.notes or "Notes cleared")
                    for field in ("stage_on", "applied_on", "deadline", "closed_reason", "availability"):
                        if field in event.changed_fields:
                            st.caption(field.replace("_", " ").capitalize() + ": " + str(getattr(event.progress, field) or "Cleared"))
                elif event.action == "reply_status_update":
                    st.text(f"{timestamp} · {event.progress.stage.label} · Recorded from a connected reply")
                else:
                    st.text(f"{timestamp} · Saved" + (" · carried over from your shortlist" if event.action == "imported_saved_role" else ""))
            st.caption(f"Original source: {opening.source} · captured {opening.retrieved_at or record.created_at}")
            st.text(opening.description or "The source did not include an advert description.")
            remove = st.checkbox("Remove this application and its history", key=f"{key}:confirm-remove")
            if st.button("Remove application", key=f"{key}:remove", disabled=not remove):
                store.delete(career_track_id, record.id)
                st.session_state["tracker-notice"] = "Application and its history removed from the tracker."
                st.rerun()


def _edit_application(store, career_track_id, record, key):
    progress = record.progress
    # A new edit version resets widget defaults after quick actions or updates.
    version = f"{key}:{record.updated_at}"
    with st.form(version):
        stage = st.selectbox("Status", list(ApplicationStage),
                               index=list(ApplicationStage).index(progress.stage),
                               format_func=lambda stage: stage.label, key=f"{version}:stage")
        next_step = st.text_input("Next step", value=progress.next_step, max_chars=500,
                                  placeholder="Prepare for the technical interview")
        next_step_on = st.date_input("Next-step date (optional)", value=progress.next_step_on)
        notes = st.text_area("Application notes", value=progress.notes, max_chars=10_000,
                              placeholder="What happened, what to prepare, what to remember")
        with st.expander("Dates & listing details (optional)"):
            left, right = st.columns(2)
            stage_on = left.date_input("Status date (optional)", value=progress.stage_on)
            applied_on = right.date_input("Applied on (optional)", value=progress.applied_on)
            deadline = st.date_input("Application deadline (optional)", value=progress.deadline)
            closing_reasons = {"": "No reason selected", "rejected": "Rejected", "withdrawn": "Withdrawn", "other": "Other"}
            closed_reason = st.selectbox("Reason if closed", list(closing_reasons),
                                        index=list(closing_reasons).index(progress.closed_reason), format_func=closing_reasons.get)
            availability_labels = {"unverified": "Not checked", "open": "I checked: still open", "expired": "I checked: expired / removed"}
            availability = st.selectbox("Listing availability", list(availability_labels),
                                       index=list(availability_labels).index(progress.availability), format_func=availability_labels.get)
        submitted = st.form_submit_button("Save application update", type="primary")
    if submitted:
        try:
            if stage != progress.stage and stage_on == progress.stage_on:
                stage_on = tracker_today()
            updated = ApplicationProgress(
                stage=stage, stage_on=stage_on, applied_on=applied_on, deadline=deadline,
                next_step=next_step, next_step_on=next_step_on, notes=notes,
                closed_reason=closed_reason if stage is ApplicationStage.CLOSED else "",
                availability=availability,
            )
            store.update(career_track_id, record.id, updated, expected_updated_at=record.updated_at)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state["tracker-notice"] = f"Updated your {record.opening.company.name} application."
            st.rerun()


_STYLES = """
<style>
.tracker-title {color:#173a31; letter-spacing:-.04em; margin:.25rem 0;}
.tracker-intro {color:#5b7164; max-width:680px;}
.tracker-pipeline {display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:8px; margin:1rem 0 1.5rem;}
.tracker-stage {background:#ffffff; border:1px solid #dce4d9; border-radius:12px; padding:14px 10px;}
.tracker-stage span {display:block; font-size:.75rem; color:#5b7164;}
.tracker-stage b {display:block; color:#173a31; font-size:1.6rem; margin-top:.2rem;}
.tracker-status {display:inline-block; border-radius:999px; padding:.35rem .7rem; font-size:.78rem; font-weight:700; background:#e8eee7; color:#294e3e;}
.tracker-status.interview,.tracker-status.offer {background:#daf0df;color:#1c5731;}
.tracker-status.applied,.tracker-status.contacted {background:#e2ebf4;color:#264b70;}
.tracker-status.closed {background:#eceae8;color:#665e59;}
.tracker-next {background:#edf7f0;color:#215a40;border-left:3px solid #16734c;border-radius:8px;padding:.7rem .9rem;margin:.65rem 0 1rem;font-size:.88rem;}
.tracker-next.overdue {background:#fff1f0;color:#9b2925;border-left-color:#c2413b;}
.tracker-next span {font-weight:600;}
@media(max-width:700px) {.tracker-pipeline {grid-template-columns:repeat(4,minmax(0,1fr));}}
</style>
"""
