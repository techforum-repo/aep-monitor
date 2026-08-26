from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import data, database
from ..poller import refresh_segments
from ..utils import safe_csv
from .shared import format_timestamp, get_active_sandbox, mark_cache_sandbox, refresh_button, render_friendly_error, sandbox_changed_since_cache, status_pill


def _ensure_loaded() -> None:
    if st.session_state.segment_job_rows is None or sandbox_changed_since_cache("segment_job_rows", get_active_sandbox()):
        _do_refresh()


def _do_refresh() -> None:
    active_sandbox = get_active_sandbox()
    try:
        st.session_state.segment_rows = data.fetch_segments(sandbox=active_sandbox)
        st.session_state.segment_job_rows = refresh_segments(sandbox=active_sandbox)
        mark_cache_sandbox("segment_job_rows", active_sandbox)
        st.session_state["_segments_error"] = None
    except Exception as exc:
        st.session_state["_segments_error"] = exc


def render() -> None:
    st.markdown("### Segments — Segmentation Service (Unified Profile)")
    st.caption(f"Segment definitions and recent evaluation jobs. Sandbox: **{get_active_sandbox()}**.")
    st.caption(
        "⚠️ Newest, least-verified integration in this app (alongside Query Service) — the response shape "
        "wasn't confirmed against a live tenant. See README's Known Limitations before trusting exact field "
        "names on a new tenant; the raw response is always available below to check."
    )

    if refresh_button("Refresh from Adobe", key="segments_refresh"):
        _do_refresh()
    _ensure_loaded()

    error = st.session_state.get("_segments_error")
    if error is not None:
        if render_friendly_error(error, key="segments_retry", context="Fetching segments and segment jobs"):
            _do_refresh()
            st.rerun()
        return

    segments = st.session_state.segment_rows or []
    jobs = st.session_state.segment_job_rows or []
    st.caption(f"Last refreshed {format_timestamp(database.latest_checked_at('Segments'))}")

    st.markdown("#### Segment definitions")
    if not segments:
        st.info("No segment definitions found for this sandbox/credential.")
    else:
        seg_table = pd.DataFrame([
            {"Segment": s["name"], "Description": s["description"] or "—", "Schema": s["schema_ref"] or "—"}
            for s in segments
        ])
        st.dataframe(seg_table, use_container_width=True, hide_index=True, key="segments_definitions_table")
        st.download_button("Download as CSV", safe_csv(seg_table), "segments.csv", "text/csv")

    st.divider()
    st.markdown("#### Recent segment jobs")
    st.caption(
        "A failed job here is very often the real, upstream cause of \"the audience never reached the "
        "destination\" — check this before assuming the problem is the activation flow itself (see the "
        "AEP Ingestion page's Connector column)."
    )
    if not jobs:
        st.info("No segment jobs found for this sandbox/credential.")
        return

    job_table = pd.DataFrame([
        {
            "Segment": j["segment_name"],
            "Status": status_pill(j["status"]),
            "Profiles segmented": j.get("segmented_profile_count"),
            "Started": j["started_at"],
            "Ended": j["ended_at"],
        }
        for j in jobs
    ])
    st.dataframe(job_table, use_container_width=True, hide_index=True, key="segments_jobs_table")
    st.download_button("Download as CSV", safe_csv(job_table), "segment_jobs.csv", "text/csv")

    with st.expander("Raw responses"):
        for j in jobs:
            st.json(j["raw"], expanded=False)
