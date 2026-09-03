from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import alerts, data, database
from ..config import settings
from ..datastream_map import datastream_map_source
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
    # Reported live as a real bug: the lineage chart and
    # property_datastream_edges were previously only ever recomputed on a
    # *sandbox change* (see _render_lineage()'s own trigger condition) —
    # clicking "Refresh everything" silently left both stale. That's
    # exactly the wrong behavior for datastream_map.json specifically: a
    # human edits that file directly (no API call, no cache-busting signal
    # of its own) and would reasonably expect the button literally named
    # "Refresh everything" to pick up the change. Called after dc_rows
    # above so fetch_property_datastream_edges() (inside
    # _do_refresh_lineage()) sees this refresh's properties, not last
    # cycle's.
    _do_refresh_lineage()


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


def _sandbox_relevant_connection_names(rows: list[dict]) -> list[str]:
    """Which connections count as "belonging to" the currently active
    sandbox — an inference, not something Adobe's API states directly
    (Connections are org-wide and carry no sandbox field of their own to
    check). Deliberately strict: a connection counts as relevant only if
    at least one of its datasets actually resolved in this sandbox. A
    connection with no configured dataset_ids at all, or whose only
    datasets are unresolved here, has nothing tying it to this specific
    sandbox and is excluded — it's still reachable via
    ui/overview.py's "Show connections with no resolved data in this
    sandbox too" checkbox, never permanently lost."""
    all_names = sorted({row["connection"] for row in rows if row["connection"]})
    return [
        name for name in all_names
        if any(r["dataset"] and r["dataset"] != "—" and not r["dataset"].endswith("(unresolved)") for r in rows if r["connection"] == name)
    ]


def _do_refresh_lineage() -> None:
    active_sandbox = get_active_sandbox()
    try:
        st.session_state["lineage_rows"] = data.fetch_cja_dataset_lineage(sandbox=active_sandbox)
        # Cached alongside lineage_rows (same sandbox-change trigger, same
        # cache-marker key) rather than fetched inline in _render_lineage()
        # — fetch_property_datastream_edges() calls fetch_datasets(), a
        # live Catalog Service call in live mode; computing it fresh on
        # every Streamlit rerun (every widget click) would needlessly
        # repeat that call far more often than the sandbox actually changes.
        st.session_state["property_datastream_edges"] = data.fetch_property_datastream_edges(
            st.session_state.dc_rows or [], sandbox=active_sandbox,
        )
        # Not re-run automatically — see fetch_rule_datastream_overrides()'s
        # own "deliberately not part of refresh_all()" docstring for the
        # per-property × per-rule API cost — but a stale result computed
        # against a *different* sandbox would silently misreport whether
        # each override resolves (dataset resolution is single-sandbox
        # scoped, same gap as property_datastream_edges above), so it's
        # cleared back to "not searched yet" here rather than left showing
        # last sandbox's answer under this one's label.
        st.session_state["rule_datastream_override_edges"] = None
        mark_cache_sandbox("lineage_rows", active_sandbox)
        st.session_state["_lineage_error"] = None
    except Exception as exc:
        st.session_state["_lineage_error"] = exc


def _render_rule_datastream_overrides() -> None:
    """A rule's own action (e.g. Web SDK's "Send event") can override a
    property's *default* datastream for just the events matching that
    rule — invisible to the Property → Datastream extraction above, which
    only ever reads the extension's own default settings (see
    data.fetch_rule_datastream_overrides()'s docstring for the full
    story). Not run automatically: a real N properties × M rules amount
    of extra Reactor calls, for a fact that's rare by construction — run
    only on request, typically to explain one specific datastream/dataset
    that stays unconnected above despite a real datastream_map.json entry
    for it."""
    dc_rows = st.session_state.dc_rows or []
    with st.expander("Rule-based datastream overrides", expanded=False):
        st.caption(
            "Searches every rule on every Data Collection property for an action that overrides the property's "
            "default datastream (not run automatically — see the button below). A match is merged into the "
            "diagram and debug table above as one more Property → Datastream edge, labeled with the rule that "
            "sets it, distinct from the property's own default datastream."
        )
        if st.button("Search rules for datastream overrides", key="overview_search_rule_overrides", disabled=not dc_rows):
            with st.spinner("Checking every rule's own actions for a datastream override..."):
                st.session_state["rule_datastream_override_edges"] = data.fetch_rule_datastream_overrides(
                    dc_rows, sandbox=get_active_sandbox(),
                )
        override_edges = st.session_state.get("rule_datastream_override_edges")
        if override_edges is None:
            st.caption("Not searched yet in this sandbox.")
        elif not override_edges:
            st.caption("No rule found overriding a datastream, across every rule on every property.")
        else:
            # No separate results table here on purpose (there used to be
            # one) — a match is embedded straight into the diagram/debug
            # table below as its own Property → Rule → Datastream node
            # chain instead, so there's exactly one place to look, not two
            # disagreeing views of the same fact.
            st.caption(
                f"Found {len(override_edges)} rule-based override(s) — each now shown as its own "
                "**Property → Rule → Datastream** chain in the diagram and debug table below, distinct from a "
                "property's own default Datastream node."
            )


# One fixed color per pipeline stage, applied to every node at that stage —
# not a cycled/generated palette — so a viewer learns "blue = dataset"
# once and it holds across every flowchart render, not just this session.
# Teal for schema deliberately avoids the reserved status-red/green hues
# (see ui/shared.py's _GOOD/_WARNING/_BAD_STATES) — this palette is a
# stage identity, not a health signal, and must never be confused with one.
# Every color is checked (WCAG relative-luminance contrast) against the
# fixed black node text below — all eight clear 4.5:1 (see
# _LINEAGE_NODE_TEXT_COLOR).
#
# Domain/Property/Datastream (Reactor + the git-ignored
# datastream_map.json — see data.fetch_property_datastream_edges()) used
# to be excluded from this diagram entirely, shown in their own
# collapsed-by-default table instead — reported live as a real usability
# problem on the Sankey this diagram replaced: those stages almost always
# collapse to a single node each, which Plotly rendered as a huge,
# mostly-empty solid block sitting right next to the genuinely dense
# fan-out further along (Data View -> Project), visually unbalanced in a
# way inherent to mixing a 1-node stage with a many-node one on a
# proportional-flow chart. That specific failure mode doesn't apply to a
# plain boxes-and-arrows flowchart — a 1-node stage is just a small box,
# not a rendering problem — so on request ("can we include this also to
# the diagram and remove the separate section") they're merged back in,
# joined onto the same Dataset node the CJA-side chain already creates by
# dataset *name* (see _build_lineage_flowchart()). Only the always-
# unfiltered "Debug" table survives separately (_render_property_
# datastream_debug()) — that one serves a genuinely different purpose the
# diagram can't (troubleshooting extraction/mapping directly against a
# real tenant's raw ids), not scoped to one connection at all.
_LINEAGE_STAGE_COLORS = {
    "domain": "#d66a97", "property": "#b8846a", "rule": "#c17a3a", "datastream": "#a89530",
    "schema": "#1fada6", "dataset": "#2a78d6", "connection": "#3fae5c", "dataview": "#e8871a", "project": "#9089fa",
}
# Same order as the pipeline itself (left to right) — used for both the
# legend and each node's hover text, so "which color is which stage" never
# has to be inferred or memorized from the caption alone. "Rule" only ever
# appears between Property and Datastream when a rule (not the property's
# own default Web SDK config) is what's overriding the datastream — see
# _build_lineage_flowchart()'s docstring and data.fetch_rule_datastream_
# overrides().
_LINEAGE_STAGE_LABELS = {
    "domain": "Website Domain", "property": "Property", "rule": "Rule (datastream override)", "datastream": "Datastream",
    "schema": "Schema", "dataset": "Dataset", "connection": "Connection", "dataview": "Data View", "project": "Project",
}


def _render_lineage_legend() -> None:
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:.35rem;margin-right:1rem;font-size:.85rem">'
        f'<span style="width:.7rem;height:.7rem;border-radius:50%;background:{_LINEAGE_STAGE_COLORS[stage]};display:inline-block"></span>'
        f'{label}</span>'
        for stage, label in _LINEAGE_STAGE_LABELS.items()
    )
    st.markdown(f'<div style="margin-bottom:.4rem">{chips}</div>', unsafe_allow_html=True)


_LINEAGE_STAGE_ORDER = ["domain", "property", "rule", "datastream", "schema", "dataset", "connection", "dataview", "project"]
# The CJA-side chain proper — fetch_cja_dataset_lineage() rows carry
# exactly these five keys. Kept separate from _LINEAGE_STAGE_ORDER (which
# also includes the three upstream stages merged in from property_edges,
# a differently-shaped input — see _build_lineage_flowchart()) so the CJA
# row walk below can't accidentally try to read row["domain"] and KeyError.
_CJA_ROW_STAGES = ["schema", "dataset", "connection", "dataview", "project"]

# Graphviz's default black text on these mid-saturation fills is a poor
# ratio on the warmer ones — measured (WCAG relative-luminance contrast)
# against every stage color rather than eyeballed: black text clears 4.5:1
# on all five (4.76-7.91), white clears none of them (2.65-4.42) — so every
# node uses black text, not per-stage guessing.
_LINEAGE_NODE_TEXT_COLOR = "#111827"


def _dot_escape(value: str) -> str:
    """Escape a value for use inside a double-quoted DOT string literal —
    Graphviz's own quoting rules, just backslash and the quote itself."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_lineage_flowchart(rows: list[dict], property_edges: list[dict] | None = None, show_path_counts: bool = True) -> str:
    """Turns fetch_cja_dataset_lineage()'s flat per-path `rows` (Schema ->
    Dataset -> Connection -> Data View -> Project — the five confirmed-API
    hops) plus fetch_property_datastream_edges()'s flat `property_edges`
    (Website domain(s) -> Property -> Datastream -> Dataset — closed via
    Reactor + the git-ignored datastream_map.json, see that function's own
    docstring) into one Graphviz DOT flowchart — boxes per node, arrows per
    confirmed link, rendered via Streamlit's built-in st.graphviz_chart (no
    new dependency: it takes a raw DOT string directly, confirmed against
    this app's installed Streamlit version).

    The two inputs join on the one field they share: a *dataset name*. A
    property_edges entry whose `dataset` matches a dataset name already
    created by the `rows` walk lands on that exact same node — one merged
    chain, not two disconnected ones — since _node() below is keyed by
    (stage, name) regardless of which input produced it. `property_edges`
    is expected pre-filtered by the caller (_render_lineage()) to just the
    dataset(s) the focused connection actually resolves — this function
    itself does no connection-scoping, so an unfiltered call would draw
    every property in the org whether or not it feeds this connection.

    Domain/Property/Datastream used to be excluded from this diagram
    entirely (their own separate, collapsed table) — reported live as a
    real usability problem on the Plotly Sankey this diagram replaced:
    those stages almost always collapse to a single node each, which
    Plotly rendered as a huge, mostly-empty solid block next to the
    genuinely dense fan-out further along — visually unbalanced in a way
    inherent to a *proportional-flow* chart mixing a 1-node stage with a
    many-node one. A plain boxes-and-arrows flowchart never had that
    failure mode (a 1-node stage is just a small box), so on request
    they're merged back in here; see _LINEAGE_STAGE_COLORS's own comment
    for the fuller history. A `domains` list fans out to one edge per
    domain into the same Property node — a property with two domains gets
    two small boxes feeding one, not one node with two names crammed in.

    A `property_edges` entry carrying `rule_name` (from
    data.fetch_rule_datastream_overrides(), merged in by _render_lineage()
    alongside fetch_property_datastream_edges()'s own edges) routes
    through its own Rule node — Property -> Rule -> Datastream — instead
    of a direct Property -> Datastream edge, so a rule's own action
    overriding the datastream (rather than the property's own default Web
    SDK config) is visibly a different shape in the diagram, not just
    different text on the same edge.

    A link's path count shows as a small "×N" edge label only when it's
    more than one and show_path_counts is True (the default) — nothing
    here is a volume metric, every edge is just "N paths go through
    here", so a Sankey's proportional link-width encoding was never
    actually the point; this says the same thing more plainly and,
    unlike a Sankey, never degrades at low N (a link with nothing to
    compare its flow against used to render as an unlabeled solid grey
    block spanning the full node height — confirmed live and by
    re-rendering the exact figure standalone as a real, deterministic
    rendering defect, not a screenshot glitch). show_path_counts=False
    keeps the same collapsed-edge structure (still one arrow, not N) and
    drops just the label — for a viewer the fan-in count reads as noise
    for, not a rendering fallback.

    A node is keyed by (stage, name) — not name alone — so a coincidental
    name collision across stages (e.g. a project happening to share a name
    with a dataset) can never merge two conceptually different nodes into
    one; multiple rows/edges contributing the same stage-to-stage link are
    collapsed into one, not one per row.

    Every unresolved dataset id collapses into one shared "Unresolved
    dataset" node rather than one node per raw id — reported live that a
    real org's permission/sandbox gaps can produce dozens of them, and a
    wall of long, near-identical GUID labels was unreadable; the specific
    raw ids are still listed in the caption under the chart in
    _render_lineage(). An unresolved dataset row has no schema to show
    either (blank, not guessed) — schema resolution is a different, much
    less lossy fallback (see fetch_cja_dataset_lineage()'s docstring), so
    it's never folded into that same collapsed node.

    Each node's tooltip is prefixed with its stage ("Schema: X", not just
    "X") — Graphviz SVG tooltips are a plain browser title attribute; the
    color legend above the chart (_render_lineage_legend()) covers the
    same mapping at a glance.

    Stage order (left to right) is enforced independently of which real
    links exist, via an invisible same-rank anchor chained across only the
    stages actually present for these rows — without it, Graphviz's
    layout is free to place a stage with no *edge* into an adjacent stage
    wherever it likes (e.g. a connection with no data view at all, or no
    property_edges at all for this connection), which at this app's
    real-world scale reliably produced a misordered chart in testing."""
    node_index: dict[tuple[str, str], str] = {}
    node_lines: list[str] = []
    nodes_per_stage: dict[str, list[str]] = {stage: [] for stage in _LINEAGE_STAGE_ORDER}

    def _node(stage: str, name: str) -> str | None:
        if not name:
            return None
        display_name = "Unresolved dataset" if stage == "dataset" and name.endswith("(unresolved)") else name
        key = (stage, display_name)
        if key not in node_index:
            node_id = f"n{len(node_index)}"
            node_index[key] = node_id
            nodes_per_stage[stage].append(node_id)
            tooltip = _dot_escape(f"{_LINEAGE_STAGE_LABELS[stage]}: {display_name}")
            label = _dot_escape(display_name)
            node_lines.append(f'{node_id} [label="{label}", tooltip="{tooltip}", fillcolor="{_LINEAGE_STAGE_COLORS[stage]}"];')
        return node_index[key]

    edge_counts: dict[tuple[str, str], int] = {}

    def _link(a: str | None, b: str | None) -> None:
        if a is not None and b is not None:
            edge_counts[(a, b)] = edge_counts.get((a, b), 0) + 1

    for row in rows:
        stage_nodes = [_node(stage, row[stage]) for stage in _CJA_ROW_STAGES]
        for a, b in zip(stage_nodes, stage_nodes[1:]):
            _link(a, b)

    for edge in property_edges or []:
        dataset_node = _node("dataset", edge["dataset"])
        datastream_node = _node("datastream", edge["datastream"])
        property_node = _node("property", edge["property"])
        _link(datastream_node, dataset_node)
        # An edge from data.fetch_rule_datastream_overrides() carries
        # `rule_name` — a rule's own action overriding the datastream,
        # not the property's own default Web SDK config
        # (fetch_property_datastream_edges() edges never set this key at
        # all, so .get() here is the only branch condition needed). Routed
        # through its own Rule node instead of a direct Property ->
        # Datastream edge, so a rule-based override reads as visibly
        # distinct from a property's default datastream at a glance, not
        # just as text buried in the datastream's own label.
        rule_name = edge.get("rule_name")
        if rule_name:
            rule_node = _node("rule", rule_name)
            _link(property_node, rule_node)
            _link(rule_node, datastream_node)
        else:
            _link(property_node, datastream_node)
        for domain in edge["domains"]:
            _link(_node("domain", domain), property_node)

    edge_lines = [
        f'{a} -> {b} [label="×{count}"];' if (count > 1 and show_path_counts) else f"{a} -> {b};"
        for (a, b), count in edge_counts.items()
    ]

    # Only the stages that actually have a node for these rows join the
    # anchor chain — an empty stage (e.g. no data view at all for this
    # connection) simply isn't a link in it, so surrounding stages still
    # anchor directly to each other instead of leaving a phantom gap.
    present_stages = [stage for stage in _LINEAGE_STAGE_ORDER if nodes_per_stage[stage]]
    anchor_ids = {stage: f"anchor_{stage}" for stage in present_stages}
    rank_lines = [
        f'{{rank=same; {anchor_ids[stage]}; {"; ".join(nodes_per_stage[stage])};}}'
        for stage in present_stages
    ]
    anchor_decl = "; ".join(f'{aid} [style=invis, shape=point, width=0]' for aid in anchor_ids.values())
    anchor_chain = " -> ".join(anchor_ids[stage] for stage in present_stages)

    dot = [
        "digraph lineage {",
        "rankdir=LR;",
        # Fixed white, not transparent — measured (WCAG contrast) against
        # both a light and a dark Streamlit theme: transparent lets the
        # edge label/arrow grey sit directly on whatever page background
        # is behind it, and the shade that reads fine on white (contrast
        # 5.98:1) drops to 3.16:1 on Streamlit's dark theme background,
        # under the 4.5:1 minimum. A fixed white card sidesteps needing to
        # detect the viewer's theme at all, and matches what the Plotly
        # Sankey this replaced already did anyway (its own default
        # paper_bgcolor is white, never overridden).
        'bgcolor="#ffffff";',
        'node [shape=box, style="filled,rounded", fontname="Helvetica,Arial,sans-serif", fontsize=11, '
        f'fontcolor="{_LINEAGE_NODE_TEXT_COLOR}", color="#00000030", margin="0.16,0.09"];',
        'edge [color="#9aa3b2", fontname="Helvetica,Arial,sans-serif", fontsize=10, fontcolor="#5b6472", arrowsize=0.7];',
    ]
    if anchor_decl:
        dot.append(f"{anchor_decl};")
    if anchor_chain:
        dot.append(f"{anchor_chain} [style=invis];")
    dot.extend(rank_lines)
    dot.extend(node_lines)
    dot.extend(edge_lines)
    dot.append("}")
    return "\n".join(dot)


def _relevant_property_edges(property_edges: list[dict], visible_rows: list[dict]) -> list[dict]:
    """property_edges filtered to just the dataset(s) the focused
    connection (visible_rows) actually resolves — the "only show the
    datastream that maps to the corresponding sandbox" scoping, now
    feeding _build_lineage_flowchart() directly rather than a separate
    table (see _LINEAGE_STAGE_COLORS's comment for why that table was
    folded back into the diagram). A pure function (property_edges passed
    in, not read from st.session_state here) so tests can exercise the
    filter directly; _render_lineage() reads session state once and passes
    it to both this and the debug table."""
    visible_dataset_names = {r["dataset"] for r in visible_rows if r["dataset"]}
    return [e for e in property_edges if e["dataset"] in visible_dataset_names]


def _render_property_datastream_debug(property_edges: list[dict]) -> None:
    """The always-unfiltered escape hatch: every Property -> Datastream ->
    Dataset value this app extracted/matched, regardless of which
    connection (if any) actually uses it, or whether it mapped at all —
    added specifically so a mapping that *should* show up in the diagram
    above but doesn't can be checked directly against real extracted
    values instead of guessing further. The diagram itself only ever shows
    the subset scoped to the focused connection (_relevant_property_edges())
    — this is the one place the full list is always visible."""
    with st.expander("Debug: every Property → Datastream → Dataset value extracted/matched, unfiltered", expanded=False):
        st.caption(f"Reading the datastream→dataset mapping from `{datastream_map_source()}`.")
        if not property_edges:
            st.caption("No Web SDK datastream ids were extracted from any Data Collection property at all.")
        else:
            st.dataframe(
                pd.DataFrame([
                    {
                        "Website domain(s)": ", ".join(e["domains"]) or "—",
                        # Blank for a datastream_map.json entry no live
                        # property actually claims (see
                        # fetch_property_datastream_edges()'s "no property"
                        # case) — "—", not an empty cell, so it reads as
                        # "none" rather than looking like missing data.
                        "Property": e["property"] or "—",
                        # Blank for every row except one from
                        # fetch_rule_datastream_overrides() — the rule
                        # whose own action overrides the datastream,
                        # rather than the property's own default Web SDK
                        # config (see _build_lineage_flowchart()'s Rule
                        # node).
                        "Rule": e.get("rule_name") or "—",
                        "Environment": e["environment"] or "—",
                        "Datastream": e["datastream"],
                        "Datastream ID (extracted)": e["datastream_id"],
                        "In map file?": "Yes" if e["mapped"] else "No",
                        "Dataset ID (from map)": e["mapped_dataset_id"] or "—",
                        "Resolved dataset name": e["dataset"] or "(not mapped)",
                    }
                    for e in property_edges
                ]),
                use_container_width=True, hide_index=True, key="overview_lineage_property_debug",
            )


def _render_lineage() -> None:
    st.divider()
    st.markdown("#### End-to-end data flow")
    st.caption(
        "Website Domain → (Data Collection) Property → Datastream → XDM Schema → AEP Dataset → CJA Connection → "
        "CJA Data View → CJA Project. The right five hops are confirmed API links: a dataset's own schema "
        "binding, a connection's own `dataSets` field, its data views' parent-connection binding, and a "
        "project's data-view binding. The left three hops close a real gap Adobe doesn't expose via any "
        "documented API — a property's own Web SDK datastream id (Reactor's own public API) joined to its "
        "destination dataset via one small, git-ignored, human-maintained file (`datastream_map.json`; see "
        "README) — shown only for the property/datastream(s) that actually feed *this* connection's own "
        "dataset(s); a property whose datastream maps elsewhere (or not at all yet) stays out of the picture "
        "for this connection, and the unfiltered debug table below still lists every extracted value regardless. "
        "A mapped datastream with no live property behind it at all (the property was deleted/reconfigured "
        "since the mapping was written, or it was never tied to one) still shows, feeding its dataset directly "
        "with no Property/Domain boxes upstream of it. "
        "Every unresolved dataset id collapses into one shared node, and the chart is always scoped to one "
        "connection at a time (pick it below) — a real org's full, unfiltered pipeline is reliably too dense to "
        "read at once. Hover any node, or check the legend above the chart, for which color is which stage."
    )
    if st.session_state.get("lineage_rows") is None or sandbox_changed_since_cache("lineage_rows", get_active_sandbox()):
        _do_refresh_lineage()

    error = st.session_state.get("_lineage_error")
    if error is not None:
        st.warning(f"Couldn't build the data flow: {error}")
    else:
        rows = st.session_state.get("lineage_rows") or []
        if not rows:
            if not (st.session_state.cja_connections or []):
                # The single most common reason this is empty, by far —
                # worth naming directly rather than a generic empty state,
                # since it's easy to mistake for a bug in this view when
                # it's actually upstream: the lineage walk starts from
                # connections, so zero connections means zero rows no
                # matter what datasets/data views/projects exist.
                st.info(
                    "No CJA connections visible to this credential — almost always the same product-administration "
                    "gap the CJA page's own \"No connections found\" note explains (Adobe's API returns 0 "
                    "connections, no error, for a technical account without that privilege), not a bug in this "
                    "view. See README Known Limitations for how to grant it."
                )
            else:
                st.caption("No datasets, data views, or projects found to chart, despite having visible connections.")
        else:
            # Reported live against a real org: an unfiltered chart with
            # dozens of connections/projects is a wall of crushed labels no
            # amount of static tuning alone fixes — a mock demo's ~2
            # connections never surfaced this. Always scoped to exactly one
            # connection's own pipeline now — an "All connections" option
            # was tried first, but at real-org scale it's never actually
            # the legible choice, just a tempting way to land back on the
            # crushed view it exists to get away from, so it's removed
            # rather than merely defaulted-away-from.
            all_connection_names = sorted({row["connection"] for row in rows if row["connection"]})
            sandbox_relevant_names = _sandbox_relevant_connection_names(rows)
            show_all = st.checkbox(
                "Show connections with no resolved data in this sandbox too", key="overview_lineage_show_all_connections",
                help="Off by default: a connection's datasets not resolving here usually just means its real data lives in a different sandbox.",
            )
            # Never silently strand the viewer with an empty picker — if
            # every connection happens to mismatch this sandbox, fall back
            # to the full list rather than rendering a selectbox with
            # nothing in it.
            connection_names = all_connection_names if (show_all or not sandbox_relevant_names) else sandbox_relevant_names
            focus = st.selectbox(
                "Focus on connection", connection_names, key="overview_lineage_focus",
                help="Scoped to one connection's own pipeline — a real org's full, unfiltered graph is reliably too dense to read at once.",
            )
            st.caption(
                f"Filtered to connections with at least one dataset resolving in sandbox **{get_active_sandbox()}** "
                "(the sidebar's AEP sandbox switcher) — an inference, not something Adobe's API states directly, "
                "since connections themselves are org-wide and carry no sandbox of their own. Switch the sidebar "
                "sandbox, not this picker, if a connection you expect to see is missing."
            )
            visible_rows = [r for r in rows if r["connection"] == focus]
            property_edges = st.session_state.get("property_datastream_edges") or []
            _render_rule_datastream_overrides()
            override_edges = st.session_state.get("rule_datastream_override_edges") or []
            # A datastream found via a rule override is, by construction,
            # also sitting in property_edges' own "(no property)" fallback
            # (fetch_property_datastream_edges() has no way to know a rule
            # explains it) — drop that now-explained duplicate rather than
            # showing the same datastream twice, once orphaned and once
            # correctly attached; same one-row-per-fact principle
            # fetch_property_datastream_edges() itself already applies
            # between its own property walk and orphan pass (see its
            # docstring's "orphan mapping is not duplicated" case).
            overridden_ids = {e["datastream_id"] for e in override_edges}
            property_edges = [e for e in property_edges if not (e["property"] == "" and e["datastream_id"] in overridden_ids)] + override_edges
            relevant_edges = _relevant_property_edges(property_edges, visible_rows)

            show_path_counts = st.checkbox(
                "Show path counts (×N) on edges", value=False, key="overview_lineage_show_path_counts",
                help="Off by default: ×N is how many rows collapsed into that one arrow, not a volume metric — "
                "easy to misread as one at a glance. Turn on if you actually want the fan-in count.",
            )

            _render_lineage_legend()
            st.graphviz_chart(
                _build_lineage_flowchart(visible_rows, relevant_edges, show_path_counts=show_path_counts),
                use_container_width=True,
            )

            unresolved_ids = sorted({row["dataset"] for row in visible_rows if row["dataset"].endswith("(unresolved)")})
            if unresolved_ids:
                st.caption(
                    f"{len(unresolved_ids)} dataset id(s) shown above as one \"Unresolved dataset\" node — "
                    "raw ids: " + ", ".join(unresolved_ids[:10]) + (f", and {len(unresolved_ids) - 10} more" if len(unresolved_ids) > 10 else "") + ". "
                    f"Try a different **sidebar** AEP sandbox (currently **{get_active_sandbox()}**) if you expect these to resolve — "
                    "a connection's dataset ids aren't guaranteed to live in the same sandbox as the one currently selected."
                )

            _render_property_datastream_debug(property_edges)

    st.markdown("###### Data Collection properties")
    dc_rows = st.session_state.dc_rows or []
    if not dc_rows:
        st.caption("No Data Collection properties found.")
    else:
        st.caption(
            "A property with a mapped Web SDK datastream feeding the focused connection's own dataset(s) also "
            "appears in the chart above — a property can configure a *different* datastream per environment "
            "(production/staging/development), each its own node there. Every property, mapped or not, is "
            "listed below regardless of which connection is focused."
        )
        datastreams_by_property: dict[str, list[str]] = {}
        for e in st.session_state.get("property_datastream_edges") or []:
            datastreams_by_property.setdefault(e["property"], []).append(e["datastream"])
        st.dataframe(
            pd.DataFrame([
                {
                    "Property": r["property_name"],
                    # A mobile (or otherwise non-web) property carries no
                    # `domains` at all per Adobe's own docs — not an error,
                    # just nothing to show here.
                    "Website domain(s)": ", ".join(r.get("domains") or []) or "—",
                    "Datastream": ", ".join(datastreams_by_property.get(r["property_name"], [])) or "—",
                    "Extensions": r["extension_count"],
                    "Rules": r["rule_count"],
                    "Data elements": r["data_element_count"],
                    "Issues": r["extension_issue_count"] + r["library_issue_count"],
                }
                for r in dc_rows
            ]),
            use_container_width=True, hide_index=True, key="overview_dc_lineage_table",
        )
