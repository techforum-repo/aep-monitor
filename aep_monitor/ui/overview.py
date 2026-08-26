from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from .. import alerts, database
from ..config import settings
from ..poller import refresh_all
from .shared import format_timestamp, get_active_sandbox, mark_cache_sandbox, refresh_button, render_friendly_error, sandbox_changed_since_cache

_BLUE = "#2a78d6"


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
    st.session_state.segment_job_rows = results["segments"]
    st.session_state.query_rows = results["query_service"]


def render() -> None:
    # Cheap (a handful of SELECT MAX queries), read-only, and independent of
    # the refresh button below — this is what lets the dashboard notice a
    # dead poller_cli.py cron job the next time a human opens this page,
    # instead of only ever checking freshness as a side effect of polling
    # (which can't catch the poller itself having stopped — see
    # alerts.evaluate_freshness()'s docstring).
    alerts.evaluate_freshness()

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
        st.success("🟢 No open alerts across AEP, Data Collection, CJA, quotas, or the monitor's own data freshness.")

    aep_rows = st.session_state.aep_rows or []
    dc_rows = st.session_state.dc_rows or []
    cja_rows = st.session_state.cja_connections or []
    quota_rows = st.session_state.quota_rows or []
    segment_job_rows = st.session_state.get("segment_job_rows") or []
    query_rows = st.session_state.get("query_rows") or []

    aep_failed = sum(1 for r in aep_rows if (r.get("latest_run") or {}).get("status") in {"failed", "error"})
    dc_issues = sum(r.get("extension_issue_count", 0) + r.get("library_issue_count", 0) for r in dc_rows)
    cja_issues = sum(1 for r in cja_rows if r.get("has_issue"))
    quota_issues = sum(1 for r in quota_rows if r.get("is_high"))
    segment_job_failures = sum(1 for r in segment_job_rows if r.get("is_bad"))
    query_failures = sum(1 for r in query_rows if r.get("is_bad"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AEP dataflows", len(aep_rows), delta=f"-{aep_failed} failing" if aep_failed else "all healthy", delta_color="inverse" if aep_failed else "off")
    c1.caption(f"Sandbox **{get_active_sandbox()}** · refreshed {format_timestamp(database.latest_checked_at('AEP'))}")
    c2.metric("Data Collection properties", len(dc_rows), delta=f"-{dc_issues} issues" if dc_issues else "all healthy", delta_color="inverse" if dc_issues else "off")
    c2.caption(f"Last refreshed {format_timestamp(database.latest_checked_at('Data Collection'))}")
    c3.metric("CJA connections", len(cja_rows), delta=f"-{cja_issues} issues" if cja_issues else "all healthy", delta_color="inverse" if cja_issues else "off")
    c3.caption(f"Last refreshed {format_timestamp(database.latest_checked_at('CJA'))}")
    c4.metric("Data lifecycle quotas", len(quota_rows), delta=f"-{quota_issues} near limit" if quota_issues else "all healthy", delta_color="inverse" if quota_issues else "off")
    c4.caption("Dataset expiration & consumer-delete identity quotas")

    c5, c6 = st.columns(2)
    c5.metric(
        "Segment jobs (recent)", len(segment_job_rows),
        delta=f"-{segment_job_failures} failed" if segment_job_failures else "all healthy",
        delta_color="inverse" if segment_job_failures else "off",
    )
    c5.caption(f"Sandbox **{get_active_sandbox()}** · refreshed {format_timestamp(database.latest_checked_at('Segments'))} · often the real cause behind a broken destination sync")
    c6.metric(
        "Query Service (recent)", len(query_rows),
        delta=f"-{query_failures} failed" if query_failures else "all healthy",
        delta_color="inverse" if query_failures else "off",
    )
    c6.caption(f"Last refreshed {format_timestamp(database.latest_checked_at('Query Service'))}")

    st.divider()
    st.markdown("#### Recent open alerts")
    open_alerts = database.list_alerts(resolved=False, limit=10)
    if open_alerts.empty:
        st.caption("Nothing open right now.")
    else:
        st.dataframe(
            open_alerts[["created_at", "source", "severity", "title"]],
            use_container_width=True, hide_index=True, key="overview_open_alerts_table",
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
            history = database.read_quota_history(quota_name=row["name"], limit=200)
            if len(history) >= 2:
                with st.expander(f"History & trend — {row['name']}"):
                    history = history.sort_values("checked_at")
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=history["checked_at"], y=history["pct_used"], mode="lines+markers",
                        name="% used", line=dict(color=_BLUE, width=2), marker=dict(size=7),
                    ))
                    fig.update_layout(
                        height=220, margin=dict(l=10, r=10, t=10, b=10),
                        yaxis_title="% used", yaxis_range=[0, max(100, history["pct_used"].max())], xaxis_title=None,
                    )
                    st.plotly_chart(fig, use_container_width=True, key=f"overview_quota_trend_chart_{row['name']}")
                    st.caption(
                        f"A rising trend projected to cross 100% within {settings.alert_quota_trend_days} days "
                        "raises an early warning on the Alerts page, separately from the plain "
                        f"{settings.alert_quota_threshold_pct:.0f}% threshold alert above."
                    )
