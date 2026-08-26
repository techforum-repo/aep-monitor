from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import data, database
from ..poller import refresh_aep
from ..utils import safe_csv
from .shared import format_timestamp, get_active_sandbox, mark_cache_sandbox, refresh_button, render_friendly_error, sandbox_changed_since_cache, status_pill

# dataviz reference palette: sequential blue for volume, reserved status red for failures.
_BLUE = "#2a78d6"
_RED = "#d03b3b"


def _ensure_loaded() -> None:
    if st.session_state.aep_rows is None or sandbox_changed_since_cache("aep_rows", get_active_sandbox()):
        _do_refresh()


def _do_refresh() -> None:
    active_sandbox = get_active_sandbox()
    try:
        st.session_state.aep_rows = refresh_aep(sandbox=active_sandbox)
        mark_cache_sandbox("aep_rows", active_sandbox)
        st.session_state["_aep_error"] = None
    except Exception as exc:
        st.session_state["_aep_error"] = exc


def render() -> None:
    st.markdown("### AEP — Dataflow ingestion health")
    st.caption(f"Flow Service API: run status, record volume, and failures per dataflow. Sandbox: **{get_active_sandbox()}**.")
    st.caption(
        "⚠️ This list is every flow /flows returns, undifferentiated — both inbound ingestion (a source landing "
        "data into AEP) and outbound activation (an AEP segment exporting to a destination) are the same object "
        "with no direction field. The **Connector** column is the only way to tell them apart today; see README's "
        "Known Limitations for why automatic classification isn't implemented."
    )

    if refresh_button("Refresh from Adobe", key="aep_refresh"):
        _do_refresh()
    _ensure_loaded()

    error = st.session_state.get("_aep_error")
    if error is not None:
        if render_friendly_error(error, key="aep_retry", context="Fetching flows and runs"):
            _do_refresh()
            st.rerun()
        return

    rows = st.session_state.aep_rows or []
    st.caption(f"Last refreshed {format_timestamp(database.latest_checked_at('AEP'))}")

    if not rows:
        st.info("No dataflows found for this sandbox/credential.")
        return

    table = pd.DataFrame([
        {
            "Flow": r["flow_name"],
            "Connector": r.get("connector_name") or "—",
            "State": r["state"],
            "Latest run": status_pill((r.get("latest_run") or {}).get("status", "no runs yet")),
            "Records in": (r.get("latest_run") or {}).get("records_in"),
            "Records failed": (r.get("latest_run") or {}).get("records_failed"),
            "flow_id": r["flow_id"],
        }
        for r in rows
    ])
    st.dataframe(table.drop(columns=["flow_id"]), use_container_width=True, hide_index=True, key="aep_flows_table")
    st.download_button("Download as CSV", safe_csv(table.drop(columns=["flow_id"])), "aep_flows.csv", "text/csv")

    st.divider()
    st.markdown("#### Flow detail & trend")
    names_by_id = {r["flow_id"]: r["flow_name"] for r in rows}
    selected_id = st.selectbox("Choose a flow", list(names_by_id.keys()), format_func=lambda fid: names_by_id[fid])
    selected_row = next(r for r in rows if r["flow_id"] == selected_id)

    with st.expander("Recent runs (raw)"):
        for run in selected_row.get("runs", []):
            st.json(run["raw"], expanded=False)

    history = database.read_aep_history(flow_id=selected_id, limit=200)
    if history.empty or len(history) < 2:
        st.caption("Not enough history yet — keep refreshing (or run poller_cli.py on a schedule) to build a trend.")
    else:
        history = history.sort_values("checked_at")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=history["checked_at"], y=history["records_in"], mode="lines+markers",
            name="Records in", line=dict(color=_BLUE, width=2), marker=dict(size=8),
        ))
        fig.add_trace(go.Scatter(
            x=history["checked_at"], y=history["records_failed"], mode="lines+markers",
            name="Records failed", line=dict(color=_RED, width=2), marker=dict(size=8),
        ))
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            yaxis_title="Records", xaxis_title=None,
        )
        st.plotly_chart(fig, use_container_width=True, key="aep_history_chart")

    st.divider()
    _render_observability()


def _do_refresh_observability() -> None:
    active_sandbox = get_active_sandbox()
    try:
        st.session_state.observability_metrics = data.fetch_observability_metrics(days=7, sandbox=active_sandbox)
        mark_cache_sandbox("observability_metrics", active_sandbox)
        st.session_state["_observability_error"] = None
    except Exception as exc:
        st.session_state["_observability_error"] = exc


def _render_observability() -> None:
    st.markdown("#### Org-wide health (Observability Insights, last 7 days)")
    st.caption(
        "Adobe's own sandbox-wide metrics API — independent of this app's per-flow polling above, "
        "and covers the whole sandbox rather than just the flows /flows returned."
    )
    if refresh_button("Refresh org-wide metrics", key="observability_refresh"):
        _do_refresh_observability()
    if st.session_state.observability_metrics is None or sandbox_changed_since_cache("observability_metrics", get_active_sandbox()):
        _do_refresh_observability()

    error = st.session_state.get("_observability_error")
    if error is not None:
        render_friendly_error(error, key="observability_retry", context="Fetching Observability Insights metrics")
        return

    metrics = st.session_state.observability_metrics or {}
    if not metrics:
        st.caption("No data returned.")
        return

    fig = go.Figure()
    colors = {"timeseries.ingestion.dataset.recordsuccess.count": _BLUE, "timeseries.ingestion.dataset.batchfailed.count": _RED}
    for name, points in metrics.items():
        if not points:
            continue
        df = pd.DataFrame(points)
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["value"], mode="lines+markers", name=name.replace("timeseries.ingestion.dataset.", ""),
            line=dict(color=colors.get(name, _BLUE), width=2), marker=dict(size=7),
        ))
    fig.update_layout(
        height=280, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis_title="Count", xaxis_title=None,
    )
    st.plotly_chart(fig, use_container_width=True, key="aep_observability_chart")
    with st.expander("Raw response"):
        st.json(metrics, expanded=False)
