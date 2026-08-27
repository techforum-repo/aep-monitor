from __future__ import annotations

"""Overview page's end-to-end data flow Sankey — the node/link-building
function is a pure transformation (no Streamlit, no fetching), tested
directly rather than only through an AppTest render.

Schema, Dataset, Connection, Data View, Project — five stages since Schema
was added on top of the original four (a dataset's own schema binding,
already resolved elsewhere in this app — see fetch_cja_dataset_lineage()'s
docstring). Two regressions below (unresolved-dataset collapsing, dynamic
height) were reported live against a real org whose scale — dozens of
connections/projects/unresolved dataset ids — the original ~5-node mock
demo never exercised."""

from aep_monitor.ui.overview import _build_lineage_sankey


def _row(schema="sch", dataset="ds", connection="conn", dataview="dv", project="proj"):
    return {"schema": schema, "dataset": dataset, "connection": connection, "dataview": dataview, "project": project}


def test_build_lineage_sankey_collapses_repeated_edges_into_one_weighted_link():
    """Two rows sharing the same hops must produce one link with value=2,
    not two separate links — the whole point of aggregating per-path rows
    into a Sankey rather than rendering one link per row."""
    rows = [
        _row(schema="Loyalty Schema", dataset="Loyalty Events", connection="Web + Mobile Unified", dataview="Executive Dashboard View", project="Weekly Report"),
        _row(schema="Loyalty Schema", dataset="Loyalty Events", connection="Web + Mobile Unified", dataview="Executive Dashboard View", project="Deep Dive"),
    ]
    fig = _build_lineage_sankey(rows)
    sankey = fig.data[0]
    labels = list(sankey.node.label)
    assert labels == ["Loyalty Schema", "Loyalty Events", "Web + Mobile Unified", "Executive Dashboard View", "Weekly Report", "Deep Dive"]

    schema_idx, dataset_idx, conn_idx, dv_idx = (labels.index(n) for n in ["Loyalty Schema", "Loyalty Events", "Web + Mobile Unified", "Executive Dashboard View"])
    links = list(zip(sankey.link.source, sankey.link.target, sankey.link.value))
    assert (schema_idx, dataset_idx, 2) in links  # both rows share this hop -> one link, weight 2
    assert (dataset_idx, conn_idx, 2) in links
    assert (conn_idx, dv_idx, 2) in links


def test_build_lineage_sankey_skips_links_past_a_blank_stage():
    """A dead-end row (e.g. a connection with no data view bound to it)
    must produce links up through the last real stage and nothing past
    it — no link involving an empty stage name."""
    rows = [_row(schema="Loyalty Schema", dataset="CRM Customer Batch", connection="CRM Connection", dataview="", project="")]
    fig = _build_lineage_sankey(rows)
    sankey = fig.data[0]
    assert list(sankey.node.label) == ["Loyalty Schema", "CRM Customer Batch", "CRM Connection"]
    assert len(sankey.link.source) == 2  # schema->dataset, dataset->connection — nothing past the blank dataview


def test_build_lineage_sankey_keeps_stage_identity_separate_for_a_name_collision():
    """A project and a dataset happening to share a name must not collapse
    into one Sankey node — nodes are keyed by (stage, name), not name
    alone."""
    rows = [_row(dataset="Shared Name", connection="Conn A", dataview="DV A", project="Shared Name")]
    fig = _build_lineage_sankey(rows)
    sankey = fig.data[0]
    assert list(sankey.node.label).count("Shared Name") == 2  # one dataset node, one project node


def test_build_lineage_sankey_handles_no_rows_without_raising():
    fig = _build_lineage_sankey([])
    sankey = fig.data[0]
    assert list(sankey.node.label) == []
    assert list(sankey.link.source) == []


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
    fig = _build_lineage_sankey(rows)
    labels = list(fig.data[0].node.label)
    assert labels.count("Unresolved dataset") == 1
    assert "Loyalty Events" in labels
    assert not any(label.endswith("(unresolved)") for label in labels)  # raw ids never reach the chart itself


def test_unresolved_dataset_node_carries_the_combined_flow_value():
    """The three unresolved rows below share one "Unresolved dataset" node
    (see the test above) — its two outgoing links (to c1, to c2) must
    still carry the right combined counts, not get silently dropped or
    merged into each other by the aggregation."""
    rows = [
        _row(dataset="a (unresolved)", connection="c1"),
        _row(dataset="b (unresolved)", connection="c1"),
        _row(dataset="c (unresolved)", connection="c2"),
    ]
    fig = _build_lineage_sankey(rows)
    labels = list(fig.data[0].node.label)
    unresolved_idx = labels.index("Unresolved dataset")
    c1_idx, c2_idx = labels.index("c1"), labels.index("c2")
    links_from_unresolved = {
        target: value
        for source, target, value in zip(fig.data[0].link.source, fig.data[0].link.target, fig.data[0].link.value)
        if source == unresolved_idx
    }
    assert links_from_unresolved == {c1_idx: 2, c2_idx: 1}


def test_figure_height_grows_with_the_busiest_stage_node_count():
    """Reported live: a fixed 380px height crushed a real org's dozens of
    distinct projects into overlapping, unreadable labels — height must
    scale with however many distinct nodes the densest stage actually has."""
    small = _build_lineage_sankey([_row(project=f"p{i}") for i in range(3)])
    large = _build_lineage_sankey([_row(project=f"p{i}") for i in range(40)])
    assert large.layout.height > small.layout.height


def test_figure_height_has_a_floor_for_a_small_org():
    fig = _build_lineage_sankey([_row()])
    assert fig.layout.height >= 380


def test_two_datasets_sharing_one_schema_fan_into_the_same_schema_node():
    """The actual reason Schema was added as its own stage: two otherwise-
    unrelated datasets governed by the same schema should visibly converge
    on one shared schema node, not look like two disconnected pipelines."""
    rows = [_row(schema="Loyalty Schema", dataset="Loyalty Events"), _row(schema="Loyalty Schema", dataset="CRM Customer Batch")]
    fig = _build_lineage_sankey(rows)
    labels = list(fig.data[0].node.label)
    assert labels.count("Loyalty Schema") == 1  # one schema node, not one per dataset
    assert "CRM Customer Batch" in labels


def test_node_hover_text_is_prefixed_with_its_stage():
    """The legend above the chart covers the color mapping at a glance;
    hover is what actually confirms it for one specific node without
    cross-referencing back to the legend."""
    rows = [_row(schema="Loyalty Schema", dataset="Loyalty Events", connection="Web + Mobile Unified", dataview="Executive Dashboard View", project="Weekly Report")]
    fig = _build_lineage_sankey(rows)
    hover = list(fig.data[0].node.customdata)
    assert "Schema: Loyalty Schema" in hover
    assert "Dataset: Loyalty Events" in hover
    assert "Connection: Web + Mobile Unified" in hover
    assert "Data View: Executive Dashboard View" in hover
    assert "Project: Weekly Report" in hover


def test_an_unresolved_dataset_has_no_schema_node_but_the_rest_of_the_chain_still_renders():
    """A blank schema (an unresolved dataset has no schema to show — see
    fetch_cja_dataset_lineage()'s docstring) must not break the rest of
    the chain — dataset -> connection -> ... still needs to render."""
    rows = [_row(schema="", dataset="ghost-id (unresolved)")]
    fig = _build_lineage_sankey(rows)
    labels = list(fig.data[0].node.label)
    assert "Unresolved dataset" in labels
    assert "conn" in labels  # the rest of the chain, unaffected by the missing schema stage


def test_property_edges_merge_into_the_same_dataset_node_as_the_cja_side_chain():
    """The whole point of joining on dataset *name*: a property's
    Datastream feeding "Loyalty Events" must land on the exact same node
    the CJA-side Schema -> Dataset chain already created for it, not a
    second, disconnected "Loyalty Events" node."""
    rows = [_row(schema="Loyalty Schema", dataset="Loyalty Events")]
    property_edges = [{"property": "acme.com — Web", "datastream": "Prod Web Datastream", "dataset": "Loyalty Events"}]

    fig = _build_lineage_sankey(rows, property_edges)

    labels = list(fig.data[0].node.label)
    assert labels.count("Loyalty Events") == 1  # one shared node, not two
    assert "acme.com — Web" in labels
    assert "Prod Web Datastream" in labels


def test_an_unmapped_datastream_gets_a_node_but_no_link_into_dataset():
    """A datastream with no dataset (unmapped, per
    fetch_property_datastream_edges()) still shows up as its own node —
    visible, not silently dropped — but has nothing to link into."""
    property_edges = [{"property": "acme.com — Web", "datastream": "abc-123 (unmapped)", "dataset": ""}]

    fig = _build_lineage_sankey([], property_edges)

    labels = list(fig.data[0].node.label)
    assert "abc-123 (unmapped)" in labels
    assert len(fig.data[0].link.source) == 1  # property -> datastream only, nothing past it


def test_build_lineage_sankey_works_with_no_property_edges_at_all():
    """property_edges is optional — every call site that existed before
    this feature was added passes none at all, and must keep working
    unchanged (no Property/Datastream nodes conjured from nothing)."""
    fig = _build_lineage_sankey([_row()])
    labels = list(fig.data[0].node.label)
    assert labels == ["sch", "ds", "conn", "dv", "proj"]
