from __future__ import annotations

"""data.py functions that aren't diff orchestration (see
test_compare_diffs.py for those) and aren't covered by a more specific
test file. Run against mock data (settings.mock_mode defaults True)."""

from datetime import datetime, timedelta, timezone

from aep_monitor import data, database
from aep_monitor.clients import mock as mock_module


def test_fetch_schema_titles_maps_schema_id_to_title():
    """The resolver behind showing a dataset's schema *title* (e.g.
    "Loyalty Events") instead of its raw $id/slug on the Datasets page and
    Compare's Datasets tab — added after a usability gap was reported live:
    both originally showed the truncated $id, not the actual schema name."""
    titles = data.fetch_schema_titles(sandbox="prod")
    assert titles["https://ns.adobe.com/acmecorp/schemas/loyalty-events"] == "Loyalty Events"
    assert titles["https://ns.adobe.com/acmecorp/schemas/web-events"] == "Web SDK Events"


def test_fetch_flow_spec_titles_maps_flow_spec_id_to_connector_name():
    titles = data.fetch_flow_spec_titles()
    assert titles["spec-s3"] == "Amazon S3"
    assert titles["spec-google-ads"] == "Google Ads Data Connector"


def test_fetch_aep_resolves_connector_name_onto_each_flow():
    """The Connector column's data source — see aep_page.py and
    clients/aep.py's parse_flow() docstring for why a flow's connector needs
    surfacing at all (GET /flows doesn't distinguish ingestion from
    outbound activation flows)."""
    rows = data.fetch_aep()
    by_id = {r["flow_id"]: r for r in rows}
    assert by_id["flow-crm-batch"]["connector_name"] == "Amazon S3"
    assert by_id["flow-loyalty-export"]["connector_name"] == "Google Ads Data Connector"


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


def test_fetch_segments_returns_parsed_definitions():
    segments = data.fetch_segments()
    assert any(s["name"] == "High-Value Loyalty Members" for s in segments)


def test_fetch_segment_jobs_resolves_segment_name_from_segment_id():
    jobs = data.fetch_segment_jobs()
    by_id = {j["job_id"]: j for j in jobs}
    assert by_id["job-1"]["segment_name"] == "High-Value Loyalty Members"
    assert by_id["job-2"]["is_bad"] is True


def test_fetch_queries_returns_parsed_rows(temp_db):
    # temp_db: fetch_queries() now also resolves "Run by" via
    # fetch_user_display_names(), which reads/writes the user directory
    # cache table.
    queries = data.fetch_queries()
    by_id = {q["query_id"]: q for q in queries}
    assert by_id["q-1"]["is_bad"] is False
    assert by_id["q-2"]["is_bad"] is True


def test_fetch_queries_includes_sql_text_and_client_type(temp_db):
    """The actual query detail — dropped entirely until this was added
    (and initially still broken live, since sql lives under `request.sql`,
    not top-level — see query_service_page.py's "Query detail" section and
    parse_query()'s docstring)."""
    queries = data.fetch_queries()
    by_id = {q["query_id"]: q for q in queries}
    assert "loyalty_events" in by_id["q-1"]["sql"]
    assert by_id["q-1"]["db_name"] == "prod:all"
    assert by_id["q-1"]["client_type"] == "Adobe Query Service Scheduler"


def test_fetch_query_schedules_returns_parsed_rows():
    schedules = data.fetch_query_schedules()
    assert schedules[0]["enabled"] is True
    assert schedules[0]["name"] == "Daily loyalty rollup"


def test_fetch_user_display_names_resolves_mock_users(temp_db):
    names = data.fetch_user_display_names()
    assert names["u-jordan-lee"] == "Jordan Lee"


def test_fetch_queries_resolves_run_by_and_flags_a_technical_account_as_unresolved(temp_db):
    """"acp-scheduler" (q-1's userId) has no matching MOCK_USERS entry — a
    technical/service account genuinely may not appear in the org
    directory (see clients/user_management.py) — must show flagged as
    unresolved, not blend in as if it were a real name."""
    queries = data.fetch_queries()
    by_id = {q["query_id"]: q for q in queries}
    assert by_id["q-2"]["user_display_name"] == "Jordan Lee"
    assert "unresolved" in by_id["q-1"]["user_display_name"]


def test_fetch_user_display_names_does_not_refetch_while_the_cache_is_fresh(temp_db, monkeypatch):
    """The core reason this cache exists at all: User Management API's own
    rate limit (25 req/min) is the strictest of any API this app talks
    to — refetching on every call the way every other resolver does would
    risk it for no benefit, since the org directory rarely changes."""
    data.fetch_user_display_names()  # first call: populates the cache
    monkeypatch.setattr(mock_module, "MOCK_USERS", [{"id": "u-jordan-lee", "email": "x", "firstname": "Changed", "lastname": "Name"}])

    names = data.fetch_user_display_names()  # cache is still fresh -> must not have refetched

    assert names["u-jordan-lee"] == "Jordan Lee"  # the original value, not "Changed Name"


def test_fetch_user_display_names_refetches_once_the_cache_goes_stale(temp_db, monkeypatch):
    old_fetch_time = (datetime.now(timezone.utc) - timedelta(hours=999)).isoformat()
    monkeypatch.setattr(database, "_now", lambda: old_fetch_time)
    data.fetch_user_display_names()  # populates the cache, stamped as old

    monkeypatch.setattr(database, "_now", lambda: datetime.now(timezone.utc).isoformat())
    monkeypatch.setattr(mock_module, "MOCK_USERS", [{"id": "u-jordan-lee", "email": "x", "firstname": "Changed", "lastname": "Name"}])

    names = data.fetch_user_display_names()  # cache is now stale (999h > default 12h) -> must refetch

    assert names["u-jordan-lee"] == "Changed Name"


def test_fetch_user_display_names_degrades_to_empty_on_a_fetch_failure_instead_of_raising(temp_db, monkeypatch):
    """A missing/unconfigured User Management API grant is a real, expected
    case (see README) — it must degrade every userId to unresolved, not
    break Query Service's own page."""
    def _boom(rows):
        raise RuntimeError("403 Forbidden — User Management API not granted")

    monkeypatch.setattr(database, "replace_user_directory", _boom)

    names = data.fetch_user_display_names()  # must not raise

    assert names == {}


