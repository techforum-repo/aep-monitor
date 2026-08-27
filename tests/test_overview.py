from __future__ import annotations

"""Overview page's end-to-end data flow Sankey — the node/link-building
function is a pure transformation (no Streamlit, no fetching), tested
directly rather than only through an AppTest render."""

from aep_monitor.ui.overview import _build_lineage_sankey


def test_build_lineage_sankey_collapses_repeated_edges_into_one_weighted_link():
    """Two rows sharing the same dataset->connection hop must produce one
    link with value=2, not two separate links — the whole point of
    aggregating per-path rows into a Sankey rather than rendering one link
    per row."""
    rows = [
        {"dataset": "Loyalty Events", "connection": "Web + Mobile Unified", "dataview": "Executive Dashboard View", "project": "Weekly Report"},
        {"dataset": "Loyalty Events", "connection": "Web + Mobile Unified", "dataview": "Executive Dashboard View", "project": "Deep Dive"},
    ]
    fig = _build_lineage_sankey(rows)
    sankey = fig.data[0]
    labels = list(sankey.node.label)
    assert labels == ["Loyalty Events", "Web + Mobile Unified", "Executive Dashboard View", "Weekly Report", "Deep Dive"]

    dataset_idx, conn_idx, dv_idx = labels.index("Loyalty Events"), labels.index("Web + Mobile Unified"), labels.index("Executive Dashboard View")
    links = list(zip(sankey.link.source, sankey.link.target, sankey.link.value))
    assert (dataset_idx, conn_idx, 2) in links  # both rows share this hop -> one link, weight 2
    assert (conn_idx, dv_idx, 2) in links


def test_build_lineage_sankey_skips_links_past_a_blank_stage():
    """A dead-end row (e.g. a connection with no data view bound to it)
    must produce a dataset->connection link and nothing past it — no link
    involving an empty stage name."""
    rows = [{"dataset": "CRM Customer Batch", "connection": "CRM Connection", "dataview": "", "project": ""}]
    fig = _build_lineage_sankey(rows)
    sankey = fig.data[0]
    assert list(sankey.node.label) == ["CRM Customer Batch", "CRM Connection"]
    assert len(sankey.link.source) == 1  # only the one real hop, nothing past the blank dataview


def test_build_lineage_sankey_keeps_stage_identity_separate_for_a_name_collision():
    """A project and a dataset happening to share a name must not collapse
    into one Sankey node — nodes are keyed by (stage, name), not name
    alone."""
    rows = [{"dataset": "Shared Name", "connection": "Conn A", "dataview": "DV A", "project": "Shared Name"}]
    fig = _build_lineage_sankey(rows)
    sankey = fig.data[0]
    assert list(sankey.node.label).count("Shared Name") == 2  # one dataset node, one project node


def test_build_lineage_sankey_handles_no_rows_without_raising():
    fig = _build_lineage_sankey([])
    sankey = fig.data[0]
    assert list(sankey.node.label) == []
    assert list(sankey.link.source) == []
