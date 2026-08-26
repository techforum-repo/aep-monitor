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
        "The Queries API's shape below is confirmed against Adobe's own published example response. "
        "⚠️ The Schedules section further down is not — same newest/least-verified caveat as the Segments page; "
        "see README's Known Limitations. The raw response is always available below to check either way."
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
        # Full SQL is shown in the detail section below, not as a table
        # column — a multi-line SELECT would blow out row height/column
        # width in a dataframe; a short one-line preview is enough to spot
        # which query is which before picking one for detail.
        query_table = pd.DataFrame([
            {
                # Confirmed live: the raw query object has no "name" field
                # at all (unlike segments/flows elsewhere in this app) — id
                # is the normal, expected value here, not a fallback for a
                # missing edge case.
                "Query": q["name"],
                "State": status_pill(q["state"]),
                "Client": q["client_type"] or "—",
                "User": q["user_id"] or "—",
                "DB": q["db_name"] or "—",
                "Scheduled": "Yes" if q["is_scheduled"] else "No",
                "Rows": q.get("row_count"),
                "Elapsed (ms)": q.get("elapsed_ms"),
                "Error": q["error_message"] or "—",
                "SQL preview": (q["sql"].splitlines()[0][:80] + "…") if q["sql"] else "—",
                "query_id": q["query_id"],
            }
            for q in queries
        ])
        st.dataframe(query_table.drop(columns=["query_id"]), use_container_width=True, hide_index=True, key="query_service_queries_table")
        st.download_button("Download as CSV", safe_csv(query_table.drop(columns=["query_id"])), "queries.csv", "text/csv")

        st.markdown("#### Query detail")
        names_by_id = {q["query_id"]: f"{q['name']} — {q['state']}" for q in queries}
        selected_id = st.selectbox("Choose a query", list(names_by_id.keys()), format_func=lambda qid: names_by_id[qid])
        selected = next(q for q in queries if q["query_id"] == selected_id)
        if selected["sql"]:
            st.code(selected["sql"], language="sql")
        else:
            st.caption("No SQL text returned for this query.")
        detail_cols = st.columns(3)
        detail_cols[0].caption(f"Database: **{selected['db_name'] or '—'}**")
        detail_cols[1].caption(f"Run by: **{selected['user_id'] or '—'}**")
        detail_cols[2].caption(f"Updated: **{format_timestamp(selected['updated_at'])}**")
        if selected["referenced_dataset_ids"]:
            st.caption("Referenced datasets (raw ids, not resolved to names): " + ", ".join(selected["referenced_dataset_ids"]))
        with st.expander("Raw response"):
            st.json(selected["raw"], expanded=False)

    st.divider()
    st.markdown("#### Scheduled queries")
    if not schedules:
        st.caption("No scheduled queries found.")
    else:
        sched_table = pd.DataFrame([{"Schedule": s["name"], "Enabled": "Yes" if s["enabled"] else "No"} for s in schedules])
        st.dataframe(sched_table, use_container_width=True, hide_index=True, key="query_service_schedules_table")
