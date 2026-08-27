from __future__ import annotations

"""Overview page's end-to-end data flow flowchart — the node/edge-building
function is a pure transformation (no Streamlit, no fetching, returns a
plain Graphviz DOT string) tested directly rather than only through an
AppTest render (Streamlit's AppTest can't introspect a graphviz_chart's
actual content any more than it could a plotly_chart's — see
tests/test_app_pages.py).

Schema, Dataset, Connection, Data View, Project — the five CJA-side stages
(a dataset's own schema binding, already resolved elsewhere in this app —
see fetch_cja_dataset_lineage()'s docstring) — plus Website Domain,
Property, Datastream merged in from a second, differently-shaped input
(fetch_property_datastream_edges()) on request ("include this also to the
diagram and remove the separate section"), joined onto the same Dataset
node by name.

This was a Plotly Sankey originally — replaced after a real, reproducible
rendering defect: scoped to one connection, most stages boil down to
exactly one path, and Plotly draws a link with nothing to compare its flow
against as a solid, unlabeled grey block spanning the full node height (see
_build_lineage_flowchart()'s docstring). A plain flowchart (boxes + arrows,
via Graphviz) never had that failure mode to begin with, since it was never
trying to encode flow volume as link width in the first place — which is
also exactly why Domain/Property/Datastream, originally kept out of the
Sankey for a related reason (a 1-node stage next to a many-node one looked
visually broken on a *proportional* chart), could be folded back in here
without reintroducing that problem."""

import re

from aep_monitor.ui.overview import _build_lineage_flowchart, _relevant_property_edges, _sandbox_relevant_connection_names


def _row(schema="sch", dataset="ds", connection="conn", dataview="dv", project="proj"):
    return {"schema": schema, "dataset": dataset, "connection": connection, "dataview": dataview, "project": project}


def _edge(prop="acme.com — Web", domains=None, environment="production", datastream="Prod Web Datastream (production)", dataset="Loyalty Events"):
    return {"property": prop, "domains": domains if domains is not None else ["www.acme.com"], "environment": environment, "datastream": datastream, "dataset": dataset}


def _node_id(dot: str, label: str) -> str:
    """The auto-generated node id (n0, n1, ...) whose label is exactly
    `label` — node ids are an implementation detail assigned in row-
    encounter order, so tests locate a node by its label, never a
    hardcoded id."""
    m = re.search(r'(n\d+) \[label="' + re.escape(label) + r'"', dot)
    assert m, f"no node labeled {label!r} in:\n{dot}"
    return m.group(1)


def _edge_label(dot: str, a: str, b: str) -> str | None:
    """None if the edge a->b exists with no label (path count of 1); the
    "×N" text if it carries one. Raises if the edge doesn't exist at all."""
    m = re.search(rf'\b{a} -> {b}\b(?: \[label="(×\d+)"\])?;', dot)
    assert m, f"no edge {a} -> {b} in:\n{dot}"
    return m.group(1)


def test_flowchart_collapses_repeated_edges_into_one_labeled_edge():
    """Two rows sharing the same hops must produce one edge labeled "×2",
    not two separate edges — the whole point of aggregating per-path rows
    rather than rendering one edge per row."""
    rows = [
        _row(schema="Loyalty Schema", dataset="Loyalty Events", connection="Web + Mobile Unified", dataview="Executive Dashboard View", project="Weekly Report"),
        _row(schema="Loyalty Schema", dataset="Loyalty Events", connection="Web + Mobile Unified", dataview="Executive Dashboard View", project="Deep Dive"),
    ]
    dot = _build_lineage_flowchart(rows)
    for label in ["Loyalty Schema", "Loyalty Events", "Web + Mobile Unified", "Executive Dashboard View", "Weekly Report", "Deep Dive"]:
        _node_id(dot, label)  # every node exists at all, raises otherwise

    schema, dataset, conn, dv = (_node_id(dot, n) for n in ["Loyalty Schema", "Loyalty Events", "Web + Mobile Unified", "Executive Dashboard View"])
    assert _edge_label(dot, schema, dataset) == "×2"  # both rows share this hop -> one edge, count 2
    assert _edge_label(dot, dataset, conn) == "×2"
    assert _edge_label(dot, conn, dv) == "×2"
    # The two rows diverge at Project — two separate, unlabeled (count-1) edges out of the Data View node.
    weekly, deep_dive = _node_id(dot, "Weekly Report"), _node_id(dot, "Deep Dive")
    assert _edge_label(dot, dv, weekly) is None
    assert _edge_label(dot, dv, deep_dive) is None


def test_flowchart_skips_edges_past_a_blank_stage():
    """A dead-end row (e.g. a connection with no data view bound to it)
    must produce edges up through the last real stage and nothing past
    it — no node, no edge, for an empty stage name."""
    rows = [_row(schema="Loyalty Schema", dataset="CRM Customer Batch", connection="CRM Connection", dataview="", project="")]
    dot = _build_lineage_flowchart(rows)
    assert dot.count("label=") == 3  # exactly 3 nodes, no edge labels (both edges have count 1)
    schema, dataset, conn = (_node_id(dot, n) for n in ["Loyalty Schema", "CRM Customer Batch", "CRM Connection"])
    assert _edge_label(dot, schema, dataset) is None
    assert _edge_label(dot, dataset, conn) is None


def test_flowchart_keeps_stage_identity_separate_for_a_name_collision():
    """A project and a dataset happening to share a name must not collapse
    into one node — nodes are keyed by (stage, name), not name alone."""
    rows = [_row(dataset="Shared Name", connection="Conn A", dataview="DV A", project="Shared Name")]
    dot = _build_lineage_flowchart(rows)
    assert dot.count('label="Shared Name"') == 2  # one dataset node, one project node


def test_flowchart_handles_no_rows_without_raising():
    dot = _build_lineage_flowchart([])
    assert "label=" not in dot
    assert dot.startswith("digraph lineage {")
    assert dot.rstrip().endswith("}")


def test_unresolved_datasets_collapse_into_one_shared_node():
    """Reported live: a real org's permission gap can produce dozens of
    unresolved dataset ids, each previously its own node — a wall of long,
    near-identical, illegible labels. They must collapse into one."""
    rows = [
        _row(dataset="6a7b3a1986a09a43ac8382 (unresolved)", connection="c1"),
        _row(dataset="6a63bdca7427c4b81c59896e (unresolved)", connection="c1"),
        _row(dataset="6a7cc19b525459f9fb1bd12b (unresolved)", connection="c2"),
        _row(dataset="Loyalty Events", connection="c2"),  # a genuinely resolved name must stay its own node
    ]
    dot = _build_lineage_flowchart(rows)
    assert dot.count('label="Unresolved dataset"') == 1
    _node_id(dot, "Loyalty Events")
    assert "(unresolved)" not in dot  # raw ids never reach the chart itself


def test_unresolved_dataset_node_carries_the_combined_edge_count():
    """The three unresolved rows below share one "Unresolved dataset" node
    (see the test above) — its two outgoing edges (to c1, to c2) must
    still carry the right combined counts, not get silently dropped or
    merged into each other by the aggregation."""
    rows = [
        _row(dataset="a (unresolved)", connection="c1"),
        _row(dataset="b (unresolved)", connection="c1"),
        _row(dataset="c (unresolved)", connection="c2"),
    ]
    dot = _build_lineage_flowchart(rows)
    unresolved, c1, c2 = _node_id(dot, "Unresolved dataset"), _node_id(dot, "c1"), _node_id(dot, "c2")
    assert _edge_label(dot, unresolved, c1) == "×2"
    assert _edge_label(dot, unresolved, c2) is None  # count 1 -> no label, but the edge itself still exists


def test_two_datasets_sharing_one_schema_fan_into_the_same_schema_node():
    """The actual reason Schema was added as its own stage: two otherwise-
    unrelated datasets governed by the same schema should visibly converge
    on one shared schema node, not look like two disconnected pipelines."""
    rows = [_row(schema="Loyalty Schema", dataset="Loyalty Events"), _row(schema="Loyalty Schema", dataset="CRM Customer Batch")]
    dot = _build_lineage_flowchart(rows)
    assert dot.count('label="Loyalty Schema"') == 1  # one schema node, not one per dataset
    _node_id(dot, "CRM Customer Batch")


def test_node_tooltip_is_prefixed_with_its_stage():
    """The legend above the chart covers the color mapping at a glance;
    the tooltip (a plain browser title on the SVG node, Graphviz's
    equivalent of the Sankey's node hover this replaced) is what actually
    confirms it for one specific node without cross-referencing back to
    the legend."""
    rows = [_row(schema="Loyalty Schema", dataset="Loyalty Events", connection="Web + Mobile Unified", dataview="Executive Dashboard View", project="Weekly Report")]
    dot = _build_lineage_flowchart(rows)
    assert 'tooltip="Schema: Loyalty Schema"' in dot
    assert 'tooltip="Dataset: Loyalty Events"' in dot
    assert 'tooltip="Connection: Web + Mobile Unified"' in dot
    assert 'tooltip="Data View: Executive Dashboard View"' in dot
    assert 'tooltip="Project: Weekly Report"' in dot


def test_an_unresolved_dataset_has_no_schema_node_but_the_rest_of_the_chain_still_renders():
    """A blank schema (an unresolved dataset has no schema to show — see
    fetch_cja_dataset_lineage()'s docstring) must not break the rest of
    the chain — dataset -> connection -> ... still needs to render."""
    rows = [_row(schema="", dataset="ghost-id (unresolved)")]
    dot = _build_lineage_flowchart(rows)
    _node_id(dot, "Unresolved dataset")
    _node_id(dot, "conn")  # the rest of the chain, unaffected by the missing schema stage


def test_flowchart_charts_only_the_five_cja_stages_when_no_property_edges_given():
    """property_edges is optional — every call site from before it existed
    passes none at all, and must keep working unchanged (no Domain/
    Property/Datastream nodes conjured from nothing)."""
    dot = _build_lineage_flowchart([_row()])
    for label in ["sch", "ds", "conn", "dv", "proj"]:
        _node_id(dot, label)
    assert dot.count("label=") == 5  # exactly the five CJA-side nodes, nothing more


def test_flowchart_joins_a_property_edge_onto_the_same_dataset_node_by_name():
    """The whole point of joining on dataset *name*: a property's
    Datastream feeding "Loyalty Events" must land on the exact same node
    the CJA-side Schema -> Dataset chain already created for it, not a
    second, disconnected "Loyalty Events" node."""
    rows = [_row(schema="Loyalty Schema", dataset="Loyalty Events")]
    edges = [_edge(dataset="Loyalty Events")]
    dot = _build_lineage_flowchart(rows, edges)

    assert dot.count('label="Loyalty Events"') == 1  # one shared node, not two
    dataset = _node_id(dot, "Loyalty Events")
    domain, prop, datastream = (_node_id(dot, n) for n in ["www.acme.com", "acme.com — Web", "Prod Web Datastream (production)"])
    assert _edge_label(dot, domain, prop) is None
    assert _edge_label(dot, prop, datastream) is None
    assert _edge_label(dot, datastream, dataset) is None  # each edge exists, count 1 so no "×N"


def test_flowchart_fans_out_multiple_domains_into_one_property_node():
    """A property configured for more than one web domain gets one small
    box per domain, all feeding the same Property node — not one node
    with every domain crammed into its label."""
    edges = [_edge(domains=["www.acme.com", "shop.acme.com"])]
    dot = _build_lineage_flowchart([], edges)

    prop = _node_id(dot, "acme.com — Web")
    www, shop = _node_id(dot, "www.acme.com"), _node_id(dot, "shop.acme.com")
    assert _edge_label(dot, www, prop) is None
    assert _edge_label(dot, shop, prop) is None


def test_flowchart_property_edges_are_not_scoped_by_this_function_itself():
    """_build_lineage_flowchart() draws exactly what it's given — scoping
    property_edges to the focused connection's own datasets is the
    caller's job (_relevant_property_edges(), tested separately below), so
    an edge whose dataset doesn't appear in `rows` at all still gets its
    own disconnected Domain -> Property -> Datastream -> Dataset chain
    rather than being silently dropped or erroring."""
    edges = [_edge(dataset="Totally Unrelated Dataset")]
    dot = _build_lineage_flowchart([_row()], edges)
    _node_id(dot, "Totally Unrelated Dataset")
    assert dot.count('label="Totally Unrelated Dataset"') == 1


def test_flowchart_edge_with_no_property_skips_property_and_domain_stages():
    """An orphan datastream_map.json entry (matched to no live property —
    see fetch_property_datastream_edges()'s "no property" case) has
    property="" and domains=[]. It must still get its own Datastream node
    linked straight to Dataset — just without a Property or Domain node
    anywhere in the chart, not an empty/blank node standing in for one."""
    edges = [{"property": "", "domains": [], "environment": "", "datastream": "Legacy Datastream (no property)", "dataset": "CRM Customer Batch"}]
    dot = _build_lineage_flowchart([], edges)

    datastream = _node_id(dot, "Legacy Datastream (no property)")
    dataset = _node_id(dot, "CRM Customer Batch")
    assert _edge_label(dot, datastream, dataset) is None  # the one real edge, count 1
    assert dot.count("label=") == 2  # exactly the two nodes — no Property, no Domain


def test_flowchart_anchor_chain_skips_a_stage_with_no_nodes_at_all():
    """Regression this app's own docstring calls out: without an explicit
    same-rank anchor per stage, Graphviz is free to place a stage with no
    real *edge* into an adjacent one (here, no row has a Data View at all)
    wherever its layout engine likes. The anchor chain must skip straight
    from Connection to Project, not leave a phantom Data View anchor with
    nothing in its rank."""
    rows = [_row(dataview="", project="")]
    dot = _build_lineage_flowchart(rows)
    assert "anchor_dataview" not in dot
    assert "anchor_schema -> anchor_dataset -> anchor_connection [style=invis];" in dot
    assert "{rank=same; anchor_dataview" not in dot


def test_sandbox_relevant_connections_requires_an_actual_resolved_dataset():
    """Regression: a connection with no configured datasets at all used to
    always count as "relevant" (nothing to mismatch on) — reported live
    as too lenient for "only connections associated to the selected
    sandbox." A connection needs at least one dataset that actually
    resolved here to count now."""
    rows = [
        _row(connection="has-real-data", dataset="Loyalty Events"),
        _row(connection="no-datasets-configured", dataset="—"),
        _row(connection="only-unresolved", dataset="abc123 (unresolved)"),
    ]
    assert _sandbox_relevant_connection_names(rows) == ["has-real-data"]


def test_sandbox_relevant_connections_includes_a_connection_with_at_least_one_real_dataset():
    """A connection can have both a resolved and an unresolved dataset —
    one real hit is enough to count as relevant."""
    rows = [
        _row(connection="mixed", dataset="Loyalty Events"),
        _row(connection="mixed", dataset="abc123 (unresolved)"),
    ]
    assert _sandbox_relevant_connection_names(rows) == ["mixed"]


def test_sandbox_relevant_connections_returns_empty_when_nothing_qualifies():
    rows = [_row(connection="only-unresolved", dataset="abc123 (unresolved)")]
    assert _sandbox_relevant_connection_names(rows) == []


def test_relevant_property_edges_keeps_only_edges_whose_dataset_is_visible():
    """The "only show the datastream that maps to the corresponding
    sandbox" scoping: an edge mapped to a dataset the focused connection
    doesn't resolve must be excluded, even though the edge itself
    extracted/mapped just fine."""
    visible_rows = [_row(dataset="Loyalty Events"), _row(dataset="Web SDK Events")]
    edges = [
        _edge(dataset="Loyalty Events"),
        _edge(dataset="CRM Customer Batch"),  # not one of this connection's datasets
        _edge(dataset=""),  # never mapped at all
    ]
    assert _relevant_property_edges(edges, visible_rows) == [edges[0]]


def test_relevant_property_edges_empty_when_nothing_matches():
    visible_rows = [_row(dataset="CRM Customer Batch")]
    edges = [_edge(dataset="Loyalty Events")]
    assert _relevant_property_edges(edges, visible_rows) == []
