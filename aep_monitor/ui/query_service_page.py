from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import data, database
from ..poller import refresh_query_service
from ..utils import safe_csv
from .shared import format_timestamp, get_active_sandbox, mark_cache_sandbox, refresh_button, render_friendly_error, sandbox_changed_since_cache, status_pill


def _ensure_loaded() -> None:
    if st.session_state.query_rows is None or sandbox_changed_since_cache("query_rows", get_active_sandbox()):
        _do_refresh()


def _do_refresh() -> None:
    active_sandbox = get_active_sandbox()
    try:
        st.session_state.query_schedule_rows = data.fetch_query_schedules(sandbox=active_sandbox)
        st.session_state.query_rows = refresh_query_service(sandbox=active_sandbox)
        mark_cache_sandbox("query_rows", active_sandbox)
        st.session_state["_query_service_error"] = None
    except Exception as exc:
        st.session_state["_query_service_error"] = exc


def render() -> None:
    st.markdown("### Query Service — ad-hoc & scheduled queries")
    st.caption(f"Recent queries against the data lake, and which are on a schedule. Sandbox: **{get_active_sandbox()}**.")
    st.caption(
        "⚠️ Newest, least-verified integration in this app (alongside Segments) — the response shape wasn't "
        "confirmed against a live tenant. See README's Known Limitations; the raw response is always available "
        "below to check."
    )

    if refresh_button("Refresh from Adobe", key="query_service_refresh"):
        _do_refresh()
    _ensure_loaded()

    error = st.session_state.get("_query_service_error")
    if error is not None:
        if render_friendly_error(error, key="query_service_retry", context="Fetching queries and schedules"):
            _do_refresh()
            st.rerun()
        return

    queries = st.session_state.query_rows or []
    schedules = st.session_state.query_schedule_rows or []
    st.caption(f"Last refreshed {format_timestamp(database.latest_checked_at('Query Service'))}")

    st.markdown("#### Recent queries")
    if not queries:
        st.info("No queries found for this sandbox/credential.")
    else:
        query_table = pd.DataFrame([
            {
                "Query": q["name"],
                "State": status_pill(q["state"]),
                "Scheduled": "Yes" if q["is_scheduled"] else "No",
                "Rows": q.get("row_count"),
                "Elapsed (ms)": q.get("elapsed_ms"),
                "Error": q["error_message"] or "—",
            }
            for q in queries
        ])
        st.dataframe(query_table, use_container_width=True, hide_index=True)
        st.download_button("Download as CSV", safe_csv(query_table), "queries.csv", "text/csv")
        with st.expander("Raw responses"):
            for q in queries:
                st.json(q["raw"], expanded=False)

    st.divider()
    st.markdown("#### Scheduled queries")
    if not schedules:
        st.caption("No scheduled queries found.")
    else:
        sched_table = pd.DataFrame([{"Schedule": s["name"], "Enabled": "Yes" if s["enabled"] else "No"} for s in schedules])
        st.dataframe(sched_table, use_container_width=True, hide_index=True)
