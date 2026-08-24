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
