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




def test_fetch_cja_dataset_lineage_builds_the_full_confirmed_chain():
    """Loyalty Events/Web SDK Events -> Web + Mobile Unified -> both mock
    data views -> their projects should each produce a full five-stage
    row (schema included), using resolved names throughout (never a raw id)."""
    rows = data.fetch_cja_dataset_lineage(sandbox="prod")
    full_chains = [r for r in rows if r["dataset"] == "Loyalty Events" and r["project"] == "Executive Weekly Report"]
    assert len(full_chains) == 1
    row = full_chains[0]
    assert row == {
        "schema": "Loyalty Events", "dataset": "Loyalty Events", "connection": "Web + Mobile Unified",
        "dataview": "Executive Dashboard View", "project": "Executive Weekly Report",
    }


def test_fetch_cja_dataset_lineage_resolves_a_shared_schema_across_two_datasets():
    """CRM Customer Batch and Loyalty Events are bound to the *same* mock
    schema (loyalty-events) — the whole reason Schema was added as its own
    stage: seeing that two otherwise-unrelated datasets share governance
    at the schema level, not just a coincidence of two identical labels."""
    rows = data.fetch_cja_dataset_lineage(sandbox="prod")
    by_dataset = {r["dataset"]: r["schema"] for r in rows}
    assert by_dataset["Loyalty Events"] == "Loyalty Events"
    assert by_dataset["CRM Customer Batch"] == "Loyalty Events"


def test_fetch_cja_dataset_lineage_shows_a_dead_end_instead_of_dropping_it():
    """CRM Connection's dataset (CRM Customer Batch) has no data view bound
    to it in mock data — that must still produce a row (dataset ->
    connection, with dataview/project left blank), not silently vanish."""
    rows = data.fetch_cja_dataset_lineage(sandbox="prod")
    crm_rows = [r for r in rows if r["connection"] == "CRM Connection"]
    assert len(crm_rows) == 1
    assert crm_rows[0]["dataset"] == "CRM Customer Batch"
    assert crm_rows[0]["dataview"] == ""
    assert crm_rows[0]["project"] == ""


def test_fetch_cja_dataset_lineage_flags_a_dataset_id_it_cant_resolve(monkeypatch):
    """A connection's dataset_ids can reference a dataset from a different
    sandbox than the one being viewed (Datasets are sandbox-scoped, CJA
    Connections are org-wide) — that must show up flagged as unresolved,
    not silently as a bare id or dropped. An unresolved dataset also has no
    schema to show at all (blank, not guessed)."""
    web_mobile = dict(mock_module.MOCK_CONNECTIONS[0])
    web_mobile["dataSets"] = [{"dataSetId": "not-a-real-dataset-id", "domain": "catalog", "type": "event", "name": "Ghost Dataset"}]
    patched_connections = [web_mobile, mock_module.MOCK_CONNECTIONS[1]]
    monkeypatch.setattr(mock_module, "MOCK_CONNECTIONS", patched_connections)

    rows = data.fetch_cja_dataset_lineage(sandbox="prod")
    matching = [r for r in rows if r["connection"] == "Web + Mobile Unified"]
    assert matching  # sanity: the connection itself still resolved
    assert all(r["dataset"] == "not-a-real-dataset-id (unresolved)" for r in matching)
    assert all(r["schema"] == "" for r in matching)


def test_fetch_property_datastream_edges_resolves_the_full_mock_chain():
    """PR1's mock Web SDK extensions carry four environment-specific
    datastream ids across two separate extensions (EX1, EX5) — both
    configure "production" but with genuinely different ids, staging and
    development come from EX1 alone. Production/staging/EX5's secondary
    all match entries in datastream_map.sample.json (-> "Loyalty Events" /
    "Web SDK Events" / "Loyalty Events" again), development is
    deliberately left unmapped — mock mode should demonstrate the whole
    Property -> Datastream -> Dataset chain, the two-extensions-one-
    environment case, and the unmapped case, out of the box."""
    dc_rows = data.fetch_dc()
    edges = data.fetch_property_datastream_edges(dc_rows, sandbox="prod")
    by_env = {e["environment"]: e for e in edges if e["property"] == "acme.com — Web"}

    # Two separate extensions (EX1, EX5) both configure "production" with
    # different ids — see fetch_property_datastream_edges()'s docstring —
    # so both must produce their own row, suffixed to stay distinguishable,
    # rather than the second one silently disappearing.
    assert by_env["production (EX1)"]["datastream"] == "Prod Web Datastream (production (EX1))"
    assert by_env["production (EX1)"]["dataset"] == "Loyalty Events"
    assert by_env["production (EX1)"]["mapped"] is True
    assert by_env["production (EX1)"]["mapped_dataset_id"] == "5f1a2b3c4d5e6f7a8b9c0d1e"  # raw id, for debug comparison
    assert by_env["production (EX1)"]["domains"] == ["www.acmecorp.com", "shop.acmecorp.com"]  # PR1's mock domains, passed through

    assert by_env["production (EX5)"]["datastream"] == "Secondary Prod Web Datastream (production (EX5))"
    assert by_env["production (EX5)"]["dataset"] == "Loyalty Events"  # a second, real datastream feeding the same dataset
    assert by_env["production (EX5)"]["mapped"] is True

    assert by_env["staging"]["datastream"] == "Staging Web Datastream (staging)"
    assert by_env["staging"]["dataset"] == "Web SDK Events"
    assert by_env["staging"]["mapped"] is True

    assert by_env["development"]["mapped"] is False
    assert by_env["development"]["dataset"] == ""
    assert by_env["development"]["mapped_dataset_id"] == ""  # nothing to compare — never mapped at all
    assert "unmapped" in by_env["development"]["datastream"]

    # PR2 (mobile) carries its own single-environment datastream too,
    # matching datastream_map.sample.json's third entry — exercising the
    # "no website domain" case all the way through the chain, since a
    # mobile property has none.
    mobile_edges = [e for e in edges if e["property"] == "Acme Mobile App"]
    assert len(mobile_edges) == 1
    assert mobile_edges[0]["domains"] == []
    # "Mobile App Events" is deliberately not part of any CJA connection —
    # see MOCK_DATASETS' comment — demonstrating that this mapping still
    # resolves even though no connection will ever surface it.
    assert mobile_edges[0]["dataset"] == "Mobile App Events"
    assert mobile_edges[0]["mapped"] is True

    # datastream_map.sample.json's fifth entry ("Legacy CRM Datastream") is
    # deliberately never extracted from any mock property's extensions at
    # all — a real mapping to a real dataset, but no live property claims
    # it any more. Must still surface with property="" rather than
    # vanishing entirely.
    orphan_edges = [e for e in edges if e["datastream_id"] == "55555555-5555-5555-5555-555555555555"]
    assert len(orphan_edges) == 1
    assert orphan_edges[0]["property"] == ""
    assert orphan_edges[0]["domains"] == []
    assert orphan_edges[0]["environment"] == ""
    assert orphan_edges[0]["datastream"] == "Legacy CRM Datastream (no property)"
    assert orphan_edges[0]["dataset"] == "CRM Customer Batch"
    assert orphan_edges[0]["mapped"] is True


def test_fetch_property_datastream_edges_orphan_mapping_is_not_duplicated_when_a_property_does_claim_it(monkeypatch):
    """The orphan pass only fires for a datastream_map.json id that no
    property's extraction actually found — an id a real property *does*
    carry must appear exactly once (from the property walk), never a
    second time from the orphan pass too."""
    monkeypatch.setattr(mock_module, "MOCK_EXTENSIONS", {
        **mock_module.MOCK_EXTENSIONS,
        "PR1": [{
            "id": "EX1",
            "attributes": {
                "name": "adobe-alloy",
                "settings": '{"instances": [{"name": "alloy", "edgeConfigId": "55555555-5555-5555-5555-555555555555"}]}',
            },
        }],
    })
    dc_rows = data.fetch_dc()

    edges = data.fetch_property_datastream_edges(dc_rows, sandbox="prod")

    matching = [e for e in edges if e["datastream_id"] == "55555555-5555-5555-5555-555555555555"]
    assert len(matching) == 1
    assert matching[0]["property"] == "acme.com — Web"  # claimed by a real property, not the orphan pass


def test_fetch_property_datastream_edges_orphan_mapping_flags_an_unresolvable_dataset(monkeypatch):
    """An orphan mapping's own dataset_id can itself fail to resolve
    (wrong sandbox, deleted dataset, typo) — same "(unresolved)" fallback
    as every other dataset lookup in this function, not a crash."""
    monkeypatch.setattr(data, "load_datastream_map", lambda: {
        "orphan-id": {"name": "Orphan Datastream", "dataset_id": "not-a-real-dataset-id"},
    })

    dc_rows = data.fetch_dc()
    edges = data.fetch_property_datastream_edges(dc_rows, sandbox="prod")

    orphan = next(e for e in edges if e["datastream_id"] == "orphan-id")
    assert orphan["dataset"] == "not-a-real-dataset-id (unresolved)"


def test_fetch_property_datastream_edges_keeps_both_when_two_extensions_disagree_on_the_same_environment(monkeypatch):
    """Regression, reported live: two separate extensions on one property
    both configuring "production" but with genuinely *different*
    datastream ids used to silently collapse to whichever extension the
    merge walked first (dict.setdefault()) — the second id vanished with
    no error. Both must now survive as their own row."""
    monkeypatch.setattr(mock_module, "MOCK_EXTENSIONS", {
        **mock_module.MOCK_EXTENSIONS,
        "PR1": [
            {"id": "EXA", "attributes": {"name": "adobe-alloy", "settings": '{"instances": [{"name": "alloy", "edgeConfigId": "id-from-a"}]}'}},
            {"id": "EXB", "attributes": {"name": "adobe-alloy", "settings": '{"instances": [{"name": "alloy", "edgeConfigId": "id-from-b"}]}'}},
        ],
    })
    dc_rows = data.fetch_dc()

    edges = data.fetch_property_datastream_edges(dc_rows, sandbox="prod")

    ids = {e["datastream_id"] for e in edges if e["property"] == "acme.com — Web"}
    assert ids == {"id-from-a", "id-from-b"}  # neither dropped
    environments = {e["environment"] for e in edges if e["property"] == "acme.com — Web"}
    # Both extensions share the same Reactor `name` ("adobe-alloy" — a
    # technical package slug, not a user label), so disambiguation must
    # fall back to each extension's own id, not its (colliding) name.
    assert environments == {"production (EXA)", "production (EXB)"}


def test_fetch_property_datastream_edges_collapses_two_extensions_that_agree_on_the_same_id(monkeypatch):
    """The same environment reported by two extensions with the *exact
    same* datastream id must not manufacture a second, duplicate row —
    only a genuine disagreement should ever trigger the disambiguating
    suffix."""
    monkeypatch.setattr(mock_module, "MOCK_EXTENSIONS", {
        **mock_module.MOCK_EXTENSIONS,
        "PR1": [
            {"id": "EXA", "attributes": {"name": "adobe-alloy", "settings": '{"instances": [{"name": "alloy", "edgeConfigId": "same-id"}]}'}},
            {"id": "EXB", "attributes": {"name": "adobe-alloy", "settings": '{"instances": [{"name": "alloy", "edgeConfigId": "same-id"}]}'}},
        ],
    })
    dc_rows = data.fetch_dc()

    edges = data.fetch_property_datastream_edges(dc_rows, sandbox="prod")

    web_edges = [e for e in edges if e["property"] == "acme.com — Web"]
    assert len(web_edges) == 1
    assert web_edges[0]["environment"] == "production"  # no suffix needed — nothing to disambiguate
    assert web_edges[0]["datastream_id"] == "same-id"


def test_fetch_property_datastream_edges_flags_an_unmapped_datastream(monkeypatch):
    """A datastream id with no entry in the map still produces a row
    (flagged, dataset left blank) rather than being silently dropped."""
    monkeypatch.setattr(mock_module, "MOCK_EXTENSIONS", {
        **mock_module.MOCK_EXTENSIONS,
        "PR1": [{
            "id": "EX1",
            "attributes": {
                "name": "adobe-alloy",
                "settings": '{"instances": [{"name": "alloy", "edgeConfigId": "not-in-the-map"}]}',
            },
        }],
    })
    dc_rows = data.fetch_dc()

    edges = data.fetch_property_datastream_edges(dc_rows, sandbox="prod")

    # Scoped to PR1 — PR2 (mobile) contributes its own, separately-mapped
    # edge regardless (see test_fetch_property_datastream_edges_resolves_
    # the_full_mock_chain), not relevant to this property's own unmapped
    # case.
    pr1_edges = [e for e in edges if e["property"] == "acme.com — Web"]
    assert len(pr1_edges) == 1
    assert pr1_edges[0]["mapped"] is False
    assert pr1_edges[0]["dataset"] == ""
    assert "unmapped" in pr1_edges[0]["datastream"]


def test_fetch_property_datastream_edges_returns_nothing_for_a_property_with_no_extensions_at_all(monkeypatch):
    """A property with zero extensions (as opposed to PR2, which has one
    that itself carries a datastream — see the full-chain test above)
    contributes no row, not an error."""
    monkeypatch.setattr(mock_module, "MOCK_EXTENSIONS", {**mock_module.MOCK_EXTENSIONS, "PR2": []})
    dc_rows = data.fetch_dc()
    edges = data.fetch_property_datastream_edges(dc_rows, sandbox="prod")
    assert not any(e["property"] == "Acme Mobile App" for e in edges)


def test_fetch_rule_datastream_overrides_finds_the_one_mock_override():
    """Mock's RL4 ("Sensitive Page — Route to Restricted Stream", on PR1)
    is the only mock rule component carrying a datastream override — every
    other mock rule (RL1, RL2, RL3) has no components at all, proving this
    only surfaces rules that actually override something, not every rule
    on every property."""
    dc_rows = data.fetch_dc()

    overrides = data.fetch_rule_datastream_overrides(dc_rows, sandbox="prod")

    assert len(overrides) == 1
    row = overrides[0]
    assert row["rule_name"] == "Sensitive Page — Route to Restricted Stream"
    assert row["property"] == "acme.com — Web"
    assert row["environment"] == "production"
    assert row["datastream_id"] == "66666666-6666-6666-6666-666666666666"
    assert row["mapped"] is True
    assert row["dataset"] == "Web Events — Sensitive (Restricted)"
    # This exact datastream has no extension config anywhere — before this
    # override is found, fetch_property_datastream_edges() alone puts it
    # in its own "(no property)" fallback, same symptom reported live.
    default_edges = data.fetch_property_datastream_edges(dc_rows, sandbox="prod")
    orphan = next(e for e in default_edges if e["datastream_id"] == "66666666-6666-6666-6666-666666666666")
    assert orphan["property"] == ""


def test_fetch_rule_datastream_overrides_flags_an_unmapped_override(monkeypatch):
    """An override to a datastream id with no datastream_map.json entry
    still produces a row (flagged, dataset left blank), same "never
    silently dropped" treatment fetch_property_datastream_edges() already
    gives an unmapped default datastream."""
    monkeypatch.setattr(mock_module, "MOCK_RULE_COMPONENTS", {
        "RL4": [{"id": "rc1", "attributes": {"settings": '{"datastreamIdOverride": "not-in-the-map"}'}}],
    })
    dc_rows = data.fetch_dc()

    overrides = data.fetch_rule_datastream_overrides(dc_rows, sandbox="prod")

    assert len(overrides) == 1
    assert overrides[0]["mapped"] is False
    assert overrides[0]["dataset"] == ""
    assert "unmapped" in overrides[0]["datastream"]


def test_fetch_rule_datastream_overrides_gives_one_row_per_environment(monkeypatch):
    """Reported live: the override is per-environment/sandbox, the same
    shape as the extension's own default instances[] config — a rule
    overriding both production and staging must produce two rows, not
    one collapsed row, same as fetch_property_datastream_edges() already
    does for a property's default datastream."""
    monkeypatch.setattr(mock_module, "MOCK_RULE_COMPONENTS", {
        "RL4": [{"id": "rc1", "attributes": {"settings": '{"datastreamIdOverride": "prod-override", "stagingDatastreamIdOverride": "staging-override"}'}}],
    })
    dc_rows = data.fetch_dc()

    overrides = data.fetch_rule_datastream_overrides(dc_rows, sandbox="prod")

    environments = {r["environment"]: r["datastream_id"] for r in overrides}
    assert environments == {"production": "prod-override", "staging": "staging-override"}
    assert all(r["rule_name"] == "Sensitive Page — Route to Restricted Stream" for r in overrides)


def test_fetch_rule_datastream_overrides_ignores_rule_components_with_no_override(monkeypatch):
    """A rule component that isn't a datastream override at all (a
    condition, a "Set Variable" action, ...) contributes nothing — the
    search only ever surfaces rules that actually override something."""
    monkeypatch.setattr(mock_module, "MOCK_RULE_COMPONENTS", {
        "RL4": [{"id": "rc1", "attributes": {"name": "Set Variable"}}],
    })
    dc_rows = data.fetch_dc()
    overrides = data.fetch_rule_datastream_overrides(dc_rows, sandbox="prod")
    assert overrides == []
