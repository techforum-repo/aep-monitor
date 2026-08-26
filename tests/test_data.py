from __future__ import annotations

"""data.py functions that aren't diff orchestration (see
test_compare_diffs.py for those) and aren't covered by a more specific
test file. Run against mock data (settings.mock_mode defaults True)."""

from aep_monitor import data


def test_fetch_schema_titles_maps_schema_id_to_title():
    """The resolver behind showing a dataset's schema *title* (e.g.
    "Loyalty Events") instead of its raw $id/slug on the Datasets page and
    Compare's Datasets tab — added after a usability gap was reported live:
    both originally showed the truncated $id, not the actual schema name."""
    titles = data.fetch_schema_titles(sandbox="prod")
    assert titles["https://ns.adobe.com/acmecorp/schemas/loyalty-events"] == "Loyalty Events"
    assert titles["https://ns.adobe.com/acmecorp/schemas/web-events"] == "Web SDK Events"


def test_fetch_cja_calculated_metrics_filters_the_org_wide_list_client_side_by_dataview():
    """Calculated Metrics has no documented per-data-view endpoint (unlike
    dimensions/metrics) — fetch_cja_calculated_metrics() fetches the full
    org-wide list and filters client-side by the confirmed dataId field.
    This pins that filtering actually happens: dv-exec should only see its
    own 2 calculated metrics, not dv-mktg's 1."""
    dv_exec = data.fetch_cja_calculated_metrics("dv-exec")
    dv_mktg = data.fetch_cja_calculated_metrics("dv-mktg")
    assert {m["name"] for m in dv_exec} == {"Conversion Rate", "Average Order Value"}
    assert {m["name"] for m in dv_mktg} == {"Cost per Lead"}


def test_fetch_cja_calculated_metrics_returns_empty_for_an_unknown_dataview():
    assert data.fetch_cja_calculated_metrics("not-a-real-dataview") == []


def test_fetch_schema_field_labels_filters_by_field_path_not_source_schema():
    """Confirmed live: a label descriptor's xdm:sourceSchema is a *field
    group* id, not the composite schema's own $id (and there's no way to
    resolve which field groups compose a schema — no `allOf` on the
    resolved schema response). fetch_schema_field_labels() matches by
    field path instead — this pins that a path belonging to Loyalty
    Events' own fields comes back labeled, while a label descriptor for a
    path that isn't in the schema's field list (mock data includes one,
    deliberately, on an unrelated field group) is correctly excluded even
    though it's still an xdm:descriptorLabel."""
    loyalty_paths = {"_acmecorp.loyaltyId", "_acmecorp.pointsBalance", "_acmecorp.tier", "timestamp"}
    labels = data.fetch_schema_field_labels(loyalty_paths)
    # loyaltyId carries 3 codes (one descriptor's own xdm:labels array can
    # hold several) — pins that all of them come through, not just the first.
    assert labels == {"_acmecorp.loyaltyId": ["core/I2", "custom/Restricted", "custom/Confidential"], "_acmecorp.pointsBalance": ["core/C1"]}


def test_fetch_schema_field_labels_returns_empty_when_no_known_path_matches():
    assert data.fetch_schema_field_labels({"some.field.web-events.doesnt.have"}) == {}
    assert data.fetch_schema_field_labels(set()) == {}


def test_fetch_cja_component_usage_filters_projects_by_dataview_and_counts_usage():
    """dv-exec has 2 mock projects; "Conversion Rate" is referenced by both,
    "Page"/"Visits"/"Average Order Value" by one each. dv-mktg's project
    must not leak into dv-exec's usage counts."""
    usage = data.fetch_cja_component_usage("dv-exec")
    assert usage["cm-conv-rate"]["projects"] == ["Executive Weekly Report", "Conversion Deep Dive"]
    assert usage["variables/page"]["projects"] == ["Executive Weekly Report"]
    assert usage["cm-aov"]["projects"] == ["Conversion Deep Dive"]
    assert "cm-cost-per-lead" not in usage  # belongs to dv-mktg's project, not dv-exec's


def test_fetch_cja_component_usage_excludes_report_suite_and_date_range_noise():
    """The data view ("ReportSuite") and date range on every panel are also
    __entity__-tagged in the real response but aren't "components" in the
    sense this feature means — they must not show up as usage entries."""
    usage = data.fetch_cja_component_usage("dv-exec")
    assert "dv-exec" not in usage
    assert all(v["type"] not in {"ReportSuite", "DateRange"} for v in usage.values())


def test_fetch_cja_component_usage_returns_empty_for_a_dataview_with_no_projects():
    assert data.fetch_cja_component_usage("not-a-real-dataview") == {}


def test_fetch_cja_project_entity_references_returns_raw_unfiltered_rows():
    """The debug-view function behind Component Usage's "Raw entity
    references" expander — unlike fetch_cja_component_usage(), this
    includes ReportSuite/DateRange entities and tags each row with which
    project it came from, so a real mismatch is diagnosable without
    needing a live round-trip."""
    refs = data.fetch_cja_project_entity_references("dv-exec")
    assert len(refs) == 7  # 2 projects: 4 refs (incl. ReportSuite) + 3 refs
    assert any(r["type"] == "ReportSuite" for r in refs)  # excluded from the aggregated view, present here
    ids_by_project = {}
    for r in refs:
        ids_by_project.setdefault(r["project_name"], set()).add(r["id"])
    assert "cm-aov" in ids_by_project["Conversion Deep Dive"]
    assert "cm-aov" not in ids_by_project["Executive Weekly Report"]


def test_aggregate_component_usage_matches_what_fetch_cja_component_usage_returns():
    """aggregate_component_usage() is the pure aggregation step
    fetch_cja_component_usage() itself is now built from (refactored so
    the SDR page's debug view can reuse one fetch for both the raw and
    aggregated display, instead of fetching twice) — pins that running it
    manually on the raw references produces the identical result."""
    refs = data.fetch_cja_project_entity_references("dv-exec")
    assert data.aggregate_component_usage(refs) == data.fetch_cja_component_usage("dv-exec")
