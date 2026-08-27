from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import alerts, data, database
from ..config import settings
from ..errors import friendly_error
from ..poller import refresh_all
from .shared import format_timestamp, get_active_sandbox, mark_cache_sandbox, refresh_button, sandbox_changed_since_cache

_BLUE = "#2a78d6"

# Display name per refresh_all() leg key — used to label a per-product
# warning when that leg's fetch failed (see _do_refresh()'s docstring).
_LEG_LABELS = {
    "aep": "AEP", "dc": "Data Collection", "cja": "CJA", "quota": "Quota",
    "segments": "Segments", "query_service": "Query Service",
}


def _ensure_loaded() -> None:
    if st.session_state.aep_rows is None or sandbox_changed_since_cache("aep_rows", get_active_sandbox()):
        _do_refresh()


def _do_refresh() -> None:
    """refresh_all() isolates each of its six legs in its own try/except —
    a failing one (e.g. Segments erroring on a bad request) still returns
    an empty list for that leg plus its exception under results["errors"],
    rather than raising and losing every *other* leg's already-fetched
    data too (a real live bug this app previously had: Quota's own fetch
    had already succeeded, but its result was silently lost because
    Segments raised before refresh_all() could ever return). This function
    never needs its own try/except as a result — every leg is guaranteed a
    result, successful or not."""
    active_sandbox = get_active_sandbox()
    results = refresh_all(sandbox=active_sandbox)
    st.session_state["_overview_errors"] = results.get("errors") or {}
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

    leg_errors = st.session_state.get("_overview_errors") or {}
    if leg_errors:
        failed_names = ", ".join(_LEG_LABELS.get(name, name) for name in leg_errors)
        st.warning(
            f"⚠️ **{failed_names}** failed to refresh — showing the rest of this page with whatever was last "
            "successfully fetched for those. Click \"Refresh everything\" to retry, or open that product's own "
            "page for a full error box."
        )
        with st.expander("Error details"):
            for name, exc in leg_errors.items():
                st.markdown(f"**{_LEG_LABELS.get(name, name)}**: {friendly_error(exc).title}")
                st.code(str(exc))

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

    _render_lineage()


def _do_refresh_lineage() -> None:
    active_sandbox = get_active_sandbox()
    try:
        st.session_state["lineage_rows"] = data.fetch_cja_dataset_lineage(sandbox=active_sandbox)
        mark_cache_sandbox("lineage_rows", active_sandbox)
        st.session_state["_lineage_error"] = None
    except Exception as exc:
        st.session_state["_lineage_error"] = exc


# One fixed color per pipeline stage, applied to every node at that stage —
# not a cycled/generated palette — so a viewer learns "blue = dataset"
# once and it holds across every Sankey render, not just this session.
_LINEAGE_STAGE_COLORS = {"dataset": "#2a78d6", "connection": "#3fae5c", "dataview": "#e8871a", "project": "#9089fa"}


def _build_lineage_sankey(rows: list[dict]) -> go.Figure:
    """Turns fetch_cja_dataset_lineage()'s flat per-path rows into a
    plotly Sankey's node/link arrays. A node is keyed by (stage, name) —
    not name alone — so a coincidental name collision across stages (e.g.
    a project happening to share a name with a dataset) can never merge
    two conceptually different nodes into one; multiple rows contributing
    the same stage-to-stage edge are collapsed into one link whose value
    is the count of paths through it, rather than one link per row."""
    node_index: dict[tuple[str, str], int] = {}
    node_labels: list[str] = []
    node_colors: list[str] = []

    def _node(stage: str, name: str) -> int | None:
        if not name:
            return None
        key = (stage, name)
        if key not in node_index:
            node_index[key] = len(node_labels)
            node_labels.append(name)
            node_colors.append(_LINEAGE_STAGE_COLORS[stage])
        return node_index[key]

    link_counts: dict[tuple[int, int], int] = {}
    for row in rows:
        stage_nodes = [
            _node("dataset", row["dataset"]), _node("connection", row["connection"]),
            _node("dataview", row["dataview"]), _node("project", row["project"]),
        ]
        for a, b in zip(stage_nodes, stage_nodes[1:]):
            if a is not None and b is not None:
                link_counts[(a, b)] = link_counts.get((a, b), 0) + 1

    fig = go.Figure(go.Sankey(
        node=dict(label=node_labels, color=node_colors, pad=15, thickness=16),
        link=dict(source=[a for a, _ in link_counts], target=[b for _, b in link_counts], value=list(link_counts.values())),
    ))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), font_size=12)
    return fig


def _render_lineage() -> None:
    st.divider()
    st.markdown("#### End-to-end data flow")
    st.caption(
        "AEP Dataset → CJA Connection → CJA Data View → CJA Project, using confirmed API links: a connection's "
        "own `dataSets` field, its data views' parent-connection binding, and a project's data-view binding. "
        "Data Collection properties are listed separately below, **not** connected into this flow — there's no "
        "public API for Datastream configuration (which property's Web SDK datastream sends to which dataset), "
        "so that link can't be discovered programmatically; only whoever configured it knows the mapping."
    )
    if st.session_state.get("lineage_rows") is None or sandbox_changed_since_cache("lineage_rows", get_active_sandbox()):
        _do_refresh_lineage()

    error = st.session_state.get("_lineage_error")
    if error is not None:
        st.warning(f"Couldn't build the data flow: {error}")
    else:
        rows = st.session_state.get("lineage_rows") or []
        if not rows:
            st.caption("No datasets, connections, data views, or projects found to chart.")
        else:
            st.plotly_chart(_build_lineage_sankey(rows), use_container_width=True, key="overview_lineage_sankey")

    st.markdown("###### Data Collection properties (not linked above)")
    dc_rows = st.session_state.dc_rows or []
    if not dc_rows:
        st.caption("No Data Collection properties found.")
    else:
        st.dataframe(
            pd.DataFrame([
                {
                    "Property": r["property_name"],
                    "Extensions": r["extension_count"],
                    "Rules": r["rule_count"],
                    "Data elements": r["data_element_count"],
                    "Issues": r["extension_issue_count"] + r["library_issue_count"],
                }
                for r in dc_rows
            ]),
            use_container_width=True, hide_index=True, key="overview_dc_lineage_table",
        )
