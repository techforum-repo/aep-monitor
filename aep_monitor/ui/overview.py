from __future__ import annotations

import streamlit as st

from .. import database
from ..poller import refresh_all
from .shared import format_timestamp, get_active_sandbox, mark_cache_sandbox, refresh_button, render_friendly_error, sandbox_changed_since_cache


def _ensure_loaded() -> None:
    if st.session_state.aep_rows is None or sandbox_changed_since_cache("aep_rows", get_active_sandbox()):
        _do_refresh()


def _do_refresh() -> None:
    active_sandbox = get_active_sandbox()
    try:
        results = refresh_all(sandbox=active_sandbox)
    except Exception as exc:
        st.session_state["_overview_error"] = exc
        return
    st.session_state["_overview_error"] = None
    st.session_state.aep_rows = results["aep"]
    mark_cache_sandbox("aep_rows", active_sandbox)  # same key aep_page.py tracks — shares one cache
    st.session_state.dc_rows = results["dc"]
    st.session_state.cja_connections = results["cja"]
    st.session_state.quota_rows = results["quota"]


def render() -> None:
    col1, col2 = st.columns([1, 5])
    with col1:
        if refresh_button("Refresh everything", key="overview_refresh"):
            _do_refresh()
    _ensure_loaded()

    error = st.session_state.get("_overview_error")
    if error is not None:
        if render_friendly_error(error, key="overview_retry", context="Refreshing all three products"):
            _do_refresh()
            st.rerun()

    open_counts = database.open_alert_counts()
    critical = open_counts.get("critical", 0)
    warning = open_counts.get("warning", 0)
    if critical:
        st.error(f"🔴 {critical} critical alert{'s' if critical != 1 else ''} open — see the Alerts page.")
    elif warning:
        st.warning(f"🟡 {warning} warning{'s' if warning != 1 else ''} open — see the Alerts page.")
    else:
        st.success("🟢 No open alerts across AEP, Data Collection, CJA, or quotas.")

    aep_rows = st.session_state.aep_rows or []
    dc_rows = st.session_state.dc_rows or []
    cja_rows = st.session_state.cja_connections or []
    quota_rows = st.session_state.quota_rows or []

    aep_failed = sum(1 for r in aep_rows if (r.get("latest_run") or {}).get("status") in {"failed", "error"})
    dc_issues = sum(r.get("extension_issue_count", 0) + r.get("library_issue_count", 0) for r in dc_rows)
    cja_issues = sum(1 for r in cja_rows if r.get("has_issue"))
    quota_issues = sum(1 for r in quota_rows if r.get("is_high"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AEP dataflows", len(aep_rows), delta=f"-{aep_failed} failing" if aep_failed else "all healthy", delta_color="inverse" if aep_failed else "off")
    c1.caption(f"Sandbox **{get_active_sandbox()}** · refreshed {format_timestamp(database.latest_checked_at('AEP'))}")
    c2.metric("Data Collection properties", len(dc_rows), delta=f"-{dc_issues} issues" if dc_issues else "all healthy", delta_color="inverse" if dc_issues else "off")
    c2.caption(f"Last refreshed {format_timestamp(database.latest_checked_at('Data Collection'))}")
    c3.metric("CJA connections", len(cja_rows), delta=f"-{cja_issues} issues" if cja_issues else "all healthy", delta_color="inverse" if cja_issues else "off")
    c3.caption(f"Last refreshed {format_timestamp(database.latest_checked_at('CJA'))}")
    c4.metric("Data lifecycle quotas", len(quota_rows), delta=f"-{quota_issues} near limit" if quota_issues else "all healthy", delta_color="inverse" if quota_issues else "off")
    c4.caption("Dataset expiration & consumer-delete identity quotas")

    st.divider()
    st.markdown("#### Recent open alerts")
    open_alerts = database.list_alerts(resolved=False, limit=10)
    if open_alerts.empty:
        st.caption("Nothing open right now.")
    else:
        st.dataframe(
            open_alerts[["created_at", "source", "severity", "title"]],
            use_container_width=True, hide_index=True,
        )
        st.caption("Resolve or review these on the Alerts page.")

    st.divider()
    st.markdown("#### Data lifecycle quotas")
    st.caption("Dataset expiration & consumer-delete identity (privacy) quotas — Data Lifecycle Quota API.")
    if not quota_rows:
        st.caption("No quota data.")
    else:
        for row in quota_rows:
            label = f"{row['name']} — {row['consumed']:.0f} / {row['quota']:.0f} ({row['pct_used']:.0f}%)"
            st.progress(min(row["pct_used"] / 100, 1.0), text=label)
            if row["description"]:
                st.caption(row["description"])
