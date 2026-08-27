from __future__ import annotations

"""_build_lineage_sankey() — pure data-transformation logic (no Streamlit
calls) behind Overview's "End-to-end data flow" chart, so it's tested
directly here rather than only through test_app_pages.py's AppTest smoke
suite. Both regressions pinned here were reported live against a real org
whose scale (dozens of connections/projects) the ~5-node mock demo never
exercised — see _build_lineage_sankey()'s own docstring."""

from aep_monitor.ui.overview import _build_lineage_sankey


def _row(dataset="ds", connection="conn", dataview="dv", project="proj"):
    return {"dataset": dataset, "connection": connection, "dataview": dataview, "project": project}


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


def test_a_dataset_named_exactly_like_a_project_does_not_merge_nodes():
    """Nodes are keyed by (stage, name), not name alone — a coincidental
    cross-stage name collision must never merge two conceptually different
    entities into one node."""
    rows = [_row(dataset="Shared Name", project="Shared Name")]
    fig = _build_lineage_sankey(rows)
    assert list(fig.data[0].node.label).count("Shared Name") == 2
