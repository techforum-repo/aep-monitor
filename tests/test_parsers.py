from __future__ import annotations

"""parse_*() functions across all four API clients — defensive parsing of
raw (possibly incomplete or oddly-shaped) API responses into the consistent
row shapes the UI/database/alerts layers depend on. Every field-name
fallback here exists because a real Adobe response was observed (or
documented) to vary; these tests pin that behavior down."""

import json

from aep_monitor.clients import aep, audit, catalog, cja, observability, query_service, quota, reactor, schema_registry, segmentation, user_management


# --- AEP Flow Service ---------------------------------------------------------

def test_parse_flow_falls_back_to_id_when_name_missing():
    flow = aep.parse_flow({"id": "flow-1", "state": "enabled"})
    assert flow["flow_name"] == "flow-1"
    assert flow["flow_id"] == "flow-1"


def test_parse_flow_extracts_flow_spec_id_for_connector_resolution():
    flow = aep.parse_flow({"id": "flow-1", "state": "enabled", "flowSpec": {"id": "spec-s3", "version": "1.0"}})
    assert flow["flow_spec_id"] == "spec-s3"


def test_parse_flow_flow_spec_id_is_empty_when_missing():
    flow = aep.parse_flow({"id": "flow-1", "state": "enabled"})
    assert flow["flow_spec_id"] == ""


def test_parse_flow_spec_falls_back_to_empty_name_when_missing():
    spec = aep.parse_flow_spec({"id": "spec-1"})
    assert spec["flow_spec_id"] == "spec-1"
    assert spec["name"] == ""


def test_parse_run_extracts_status_records_and_falls_back_on_missing_summaries():
    run = aep.parse_run({
        "id": "run-1", "flowId": "flow-1",
        "metrics": {
            "recordSummary": {"inputCount": 100, "outputCount": 90, "failedCount": 10},
            "statusSummary": {"status": "success"},
        },
    })
    assert run["status"] == "success"
    assert run["records_in"] == 100
    assert run["records_failed"] == 10


def test_parse_run_defaults_failed_count_to_zero_and_status_to_unknown():
    run = aep.parse_run({"id": "run-1", "flowId": "flow-1"})
    assert run["records_failed"] == 0
    assert run["status"] == "unknown"


def test_parse_run_does_not_crash_when_assumed_nested_fields_are_plain_strings():
    """Regression: several fields here (metrics, state, statistics,
    recordSummary.input/output) were assumed to be nested objects and
    accessed with `.get()` chains that crash with AttributeError the
    moment a real API response puts a plain string there instead — exactly
    the class of bug that hit Observability Insights in production (see
    test_parse_metrics_response_handles_a_plain_string_metric_field)."""
    run = aep.parse_run({
        "id": "run-1", "flowId": "flow-1",
        "metrics": "not-an-object",
        "state": "not-an-object",
    })
    assert run["status"] == "unknown"
    assert run["records_failed"] == 0


def test_parse_flow_does_not_crash_when_flowspec_is_a_plain_string():
    flow = aep.parse_flow({"id": "flow-1", "flowSpec": "not-an-object"})
    assert flow["state"] == ""


# --- Reactor (Data Collection) ------------------------------------------------

def test_parse_extension_flags_rejected_and_failed_as_issues_but_not_pending():
    rejected = reactor.parse_extension({"id": "e1", "attributes": {"review_status": "rejected"}})
    approved = reactor.parse_extension({"id": "e2", "attributes": {"review_status": "approved"}})
    assert rejected["has_issue"] is True
    assert approved["has_issue"] is False


def _web_sdk_settings(**instance_overrides: object) -> str:
    """A minimal, confirmed-shape Web SDK settings string — datastream ids
    live inside settings.instances[0], not at the top level (see
    _extract_datastream_ids()'s docstring for how this was confirmed live)."""
    return json.dumps({"instances": [{"name": "alloy", **instance_overrides}], "components": {"eventMerge": False}})


def test_parse_extension_extracts_the_production_datastream_id_from_inside_instances():
    """Confirmed live against a real tenant's raw extension response: the
    datastream id is nested inside settings.instances[0], not a top-level
    settings key — the original guess looked at the wrong nesting level
    entirely and found nothing, ever, on any property."""
    ext = reactor.parse_extension({"id": "e1", "attributes": {"settings": _web_sdk_settings(edgeConfigId="abc-123")}})
    assert ext["datastream_ids"] == {"production": "abc-123"}


def test_parse_extension_extracts_the_newer_datastream_id_key_as_a_fallback():
    """Not confirmed live (only edgeConfigId has been seen on a real
    tenant), but checked first in case a different tenant/extension
    version has migrated to Adobe's documented rename."""
    ext = reactor.parse_extension({"id": "e1", "attributes": {"settings": _web_sdk_settings(datastreamId="new-456")}})
    assert ext["datastream_ids"] == {"production": "new-456"}


def test_parse_extension_extracts_staging_and_development_overrides_too():
    """Confirmed live: a single property configures a genuinely different
    datastream per environment via edgeConfigId/stagingEdgeConfigId/
    developmentEdgeConfigId, all inside the same instance object."""
    ext = reactor.parse_extension({
        "id": "e1",
        "attributes": {"settings": _web_sdk_settings(
            edgeConfigId="prod-1", stagingEdgeConfigId="staging-1", developmentEdgeConfigId="dev-1",
        )},
    })
    assert ext["datastream_ids"] == {"production": "prod-1", "staging": "staging-1", "development": "dev-1"}


def test_parse_extension_suffixes_environment_keys_when_multiple_instances_exist():
    """Rare (the confirmed-live example has exactly one instance), but the
    Web SDK extension does support configuring more than one — merged
    into one result, distinguished by instance name only when there's
    more than one to distinguish."""
    settings = json.dumps({"instances": [
        {"name": "alloy", "edgeConfigId": "prod-main"},
        {"name": "alloy2", "edgeConfigId": "prod-secondary"},
    ]})
    ext = reactor.parse_extension({"id": "e1", "attributes": {"settings": settings}})
    assert ext["datastream_ids"] == {"production (alloy)": "prod-main", "production (alloy2)": "prod-secondary"}


def test_parse_extension_datastream_ids_is_empty_for_a_non_web_sdk_extension():
    ext = reactor.parse_extension({"id": "e1", "attributes": {"name": "Core"}})
    assert ext["datastream_ids"] == {}


def test_parse_extension_datastream_ids_is_empty_when_settings_has_no_instances_list():
    """A non-Web-SDK extension's settings (e.g. "{}", or some other
    extension's own config) has no "instances" key at all — must degrade
    to empty, not crash trying to iterate a missing/wrong-typed value."""
    assert reactor.parse_extension({"id": "e1", "attributes": {"settings": "{}"}})["datastream_ids"] == {}
    assert reactor.parse_extension({"id": "e1", "attributes": {"settings": "{\"dataLayerName\": \"adobeDataLayer\"}"}})["datastream_ids"] == {}
    assert reactor.parse_extension({"id": "e1", "attributes": {"settings": "{\"instances\": \"not-a-list\"}"}})["datastream_ids"] == {}


def test_parse_extension_does_not_crash_on_malformed_settings():
    assert reactor.parse_extension({"id": "e1", "attributes": {"settings": "not valid json"}})["datastream_ids"] == {}
    assert reactor.parse_extension({"id": "e1", "attributes": {"settings": 42}})["datastream_ids"] == {}
    assert reactor.parse_extension({"id": "e1", "attributes": {"settings": "[1,2,3]"}})["datastream_ids"] == {}


def test_parse_rule_component_extracts_a_datastream_override():
    comp = reactor.parse_rule_component(
        {"id": "rc1", "attributes": {"name": "Send event", "delegate_descriptor_id": "adobe-alloy::actions::send-event", "settings": '{"datastreamIdOverride": "override-123"}'}},
        rule_id="r1", rule_name="Sensitive Page Rule",
    )
    assert comp["datastream_override_id"] == "override-123"
    assert comp["rule_id"] == "r1"
    assert comp["rule_name"] == "Sensitive Page Rule"


def test_parse_rule_component_datastream_override_is_empty_for_a_component_with_no_override():
    """The overwhelming majority of rule components (a condition, a
    non-override action) carry no datastream override at all — must
    degrade to "", not guess or crash, so callers can filter on it."""
    comp = reactor.parse_rule_component({"id": "rc1", "attributes": {"name": "Set Variable"}}, rule_id="r1", rule_name="Some Rule")
    assert comp["datastream_override_id"] == ""


def test_parse_rule_component_does_not_crash_on_malformed_settings():
    assert reactor.parse_rule_component({"id": "rc1", "attributes": {"settings": "not valid json"}}, rule_id="r1", rule_name="X")["datastream_override_id"] == ""
    assert reactor.parse_rule_component({"id": "rc1", "attributes": {"settings": 42}}, rule_id="r1", rule_name="X")["datastream_override_id"] == ""
    assert reactor.parse_rule_component({"id": "rc1", "attributes": None}, rule_id="r1", rule_name="X")["datastream_override_id"] == ""


def test_parse_library_flags_failed_and_rejected_states_as_bad():
    failed = reactor.parse_library({"id": "l1", "attributes": {"name": "Staging", "state": "failed"}})
    published = reactor.parse_library({"id": "l2", "attributes": {"name": "Prod", "state": "published"}})
    assert failed["is_bad"] is True
    assert published["is_bad"] is False
    assert published["is_good"] is True


def test_parse_property_extracts_domains():
    """`domains` is a top-level array of strings on the same property
    attributes Adobe's Properties endpoint already returns (confirmed via
    docs: required for web properties) — no extra call needed."""
    web = reactor.parse_property({"id": "p1", "attributes": {"name": "acme.com — Web", "domains": ["www.acme.com", "shop.acme.com"]}})
    assert web["domains"] == ["www.acme.com", "shop.acme.com"]

    # A mobile (or otherwise non-web) property just has none — not an error.
    mobile = reactor.parse_property({"id": "p2", "attributes": {"name": "Acme Mobile App"}})
    assert mobile["domains"] == []

    # Defensive against a malformed value (not a list) rather than crashing.
    malformed = reactor.parse_property({"id": "p3", "attributes": {"domains": "not-a-list"}})
    assert malformed["domains"] == []


def test_reactor_parsers_do_not_crash_when_attributes_is_missing_or_not_an_object():
    assert reactor.parse_property({"id": "p1"})["property_name"] == "p1"
    assert reactor.parse_extension({"id": "e1", "attributes": None})["has_issue"] is False
    assert reactor.parse_rule({"id": "r1", "attributes": "not-an-object"})["name"] == "r1"
    assert reactor.parse_library({"id": "l1", "attributes": 42})["state"] == ""
    assert reactor.parse_environment({"id": "en1", "attributes": None})["is_bad"] is False
    assert reactor.parse_data_element({"id": "de1", "attributes": "not-an-object"})["has_issue"] is False


def test_parse_environment_flags_failed_status_as_bad():
    failed = reactor.parse_environment({"id": "en1", "attributes": {"name": "Production", "stage": "production", "status": "failed"}})
    succeeded = reactor.parse_environment({"id": "en2", "attributes": {"name": "Production", "stage": "production", "status": "succeeded"}})
    assert failed["is_bad"] is True
    assert failed["stage"] == "production"
    assert succeeded["is_bad"] is False
    assert succeeded["is_good"] is True


def test_parse_data_element_flags_dirty_as_an_issue():
    dirty = reactor.parse_data_element({"id": "de1", "attributes": {"name": "Consent", "dirty": True, "published": False, "review_status": "unsubmitted"}})
    clean = reactor.parse_data_element({"id": "de2", "attributes": {"name": "Version", "dirty": False, "published": True, "review_status": "approved"}})
    assert dirty["has_issue"] is True
    assert clean["has_issue"] is False


def test_parse_data_element_flags_rejected_review_status_as_an_issue_even_when_not_dirty():
    rejected = reactor.parse_data_element({"id": "de1", "attributes": {"name": "X", "dirty": False, "published": False, "review_status": "rejected"}})
    assert rejected["has_issue"] is True


def test_parse_audit_event_extracts_reactors_confirmed_field_names():
    event = reactor.parse_audit_event({"id": "ae1", "attributes": {
        "attributed_to_email": "jordan.lee@acme.com", "type_of": "extension.updated",
        "created_at": "2026-08-24T00:00:00Z", "display_name": "Custom Consent Extension",
    }})
    assert event["actor"] == "jordan.lee@acme.com"
    assert event["action"] == "extension.updated"
    assert event["target"] == "Custom Consent Extension"


# --- CJA -----------------------------------------------------------------------

def test_parse_connection_flags_deleted_and_disabled_as_issues():
    """Adobe's connections API has no status enum ("status"/"serviceStatus"
    don't exist — confirmed via docs); isDeleted/isDisabled are the only
    real health signals, and this is what parse_connection() derives
    `status`/`has_issue` from instead."""
    deleted = cja.parse_connection({"id": "c1", "name": "x", "isDeleted": True, "isDisabled": False})
    assert deleted["has_issue"] is True
    assert deleted["status"] == "deleted"

    disabled = cja.parse_connection({"id": "c2", "name": "x", "isDeleted": False, "isDisabled": True})
    assert disabled["has_issue"] is True
    assert disabled["status"] == "disabled"

    healthy = cja.parse_connection({"id": "c3", "name": "x", "isDeleted": False, "isDisabled": False})
    assert healthy["has_issue"] is False
    assert healthy["status"] == "active"


def test_parse_connection_falls_back_to_id_when_name_is_absent():
    """Regression: /connections omits `name` entirely unless requested via
    the `expansion` query param — confirmed via Adobe's docs. This is the
    fallback for a genuinely nameless item, not the common case (see
    clients/cja.py's list_connections(), which always requests it now)."""
    row = cja.parse_connection({"id": "c1"})
    assert row["name"] == "c1"


def test_parse_dataview_does_not_crash_when_owner_is_a_plain_string():
    row = cja.parse_dataview({"id": "d1", "name": "x", "owner": "not-an-object"})
    assert row["owner"] == ""


def test_parse_dataview_resolves_connection_id_from_parent_data_group_id():
    """Regression: the FK back to the parent connection is
    `parentDataGroupId` (confirmed via Adobe's docs), not `connectionId`/
    `dataConnectionId` as originally guessed — that guess meant the Data
    views table's "Connection" column could never resolve to a name even
    once `name` itself was fixed."""
    row = cja.parse_dataview({"id": "d1", "name": "x", "parentDataGroupId": "dg_abc123"})
    assert row["connection_id"] == "dg_abc123"


def test_parse_dimension_extracts_source_field_and_approval():
    row = cja.parse_dimension({
        "id": "variables/page", "name": "Page", "description": "Page name",
        "type": "string", "sourceFieldName": "web.webPageDetails.name", "approved": True,
    })
    assert row["name"] == "Page"
    assert row["source_field"] == "web.webPageDetails.name"
    assert row["approved"] is True


def test_parse_metric_falls_back_to_id_when_name_missing():
    row = cja.parse_metric({"id": "metrics/visits", "type": "int"})
    assert row["name"] == "metrics/visits"
    assert row["approved"] is False


def test_parse_calculated_metric_extracts_data_id_as_dataview_id():
    row = cja.parse_calculated_metric({
        "id": "cm1", "name": "Conversion Rate", "description": "Orders / Visits",
        "type": "percent", "polarity": "positive", "dataId": "dv-exec",
        "owner": {"ownerId": 12345},
    })
    assert row["dataview_id"] == "dv-exec"
    assert row["polarity"] == "positive"
    assert row["owner"] == "12345"


def test_parse_calculated_metric_does_not_crash_when_owner_is_not_an_object():
    row = cja.parse_calculated_metric({"id": "cm1", "owner": "not-an-object"})
    assert row["owner"] == ""


def test_parse_project_extracts_data_id_as_dataview_id():
    row = cja.parse_project({
        "id": "proj1", "name": "Executive Weekly Report", "dataId": "dv-exec",
        "owner": {"ownerId": "jordan.lee@acme.com"}, "created": "2026-08-01T00:00:00Z",
    })
    assert row["project_id"] == "proj1"
    assert row["dataview_id"] == "dv-exec"
    assert row["owner"] == "jordan.lee@acme.com"


def test_parse_project_resolves_owner_full_name_over_the_opaque_id():
    """expansion=ownerFullName is meant to resolve a project's owner to a
    display name instead of the opaque imsUserId/ownerId this endpoint
    returns by default (confirmed live: owner.name came back null without
    it) — pins that the top-level ownerFullName field (matching the
    expansion's own name) takes priority over the opaque id when present."""
    row = cja.parse_project({
        "id": "proj1", "ownerFullName": "Jordan Lee",
        "owner": {"ownerId": "391C5A0C536B86680A490D44@techacct.adobe.com", "name": None},
    })
    assert row["owner"] == "Jordan Lee"


def test_parse_project_falls_back_to_owner_name_when_no_top_level_owner_full_name():
    """Not confirmed from a real populated example which field
    expansion=ownerFullName actually lands in — owner.name is the other
    plausible spot (it's the field that came back null without the
    expansion), checked as a second attempt before falling back to the
    opaque id."""
    row = cja.parse_project({"id": "proj1", "owner": {"name": "Jordan Lee", "ownerId": "391C5A0C..."}})
    assert row["owner"] == "Jordan Lee"


def test_parse_project_falls_back_to_id_when_name_is_absent():
    row = cja.parse_project({"id": "proj1"})
    assert row["name"] == "proj1"


def test_extract_entity_references_finds_entities_at_any_nesting_depth():
    """Confirmed live: Adobe tags any referenced component with
    `__entity__: true` wherever it sits in the deeply nested panel/
    subPanel/reportlet tree — the walker must find one buried several
    levels deep, not just at the top level."""
    definition = {
        "workspaces": [{
            "panels": [{
                "reportSuite": {"id": "dv-exec", "__entity__": True, "type": "ReportSuite", "__metaData__": {"name": "Executive Dashboard View"}},
                "subPanels": [{
                    "reportlet": {"columnTree": {"nodes": [
                        {"id": "variables/page", "__entity__": True, "type": "Dimension", "__metaData__": {"name": "Page"}},
                    ]}},
                }],
            }],
        }],
    }
    refs = cja.extract_entity_references(definition)
    ids = {r["id"] for r in refs}
    assert ids == {"dv-exec", "variables/page"}
    page_ref = next(r for r in refs if r["id"] == "variables/page")
    assert page_ref["type"] == "Dimension"
    assert page_ref["name"] == "Page"


def test_extract_entity_references_ignores_dicts_without_the_entity_marker():
    definition = {"workspaces": [{"panels": [{"id": "panel-1", "name": "Freeform", "position": {"x": 0, "y": 0}}]}]}
    assert cja.extract_entity_references(definition) == []


def test_extract_entity_references_falls_back_to_id_when_metadata_name_missing():
    row = cja.extract_entity_references({"id": "cm-1", "__entity__": True, "type": "CalculatedMetric"})
    assert row[0]["name"] == "cm-1"


def test_extract_entity_references_handles_non_dict_input_without_raising():
    assert cja.extract_entity_references(None) == []
    assert cja.extract_entity_references("not-a-definition") == []
    assert cja.extract_entity_references([]) == []


def test_extract_entity_references_stops_at_max_depth_instead_of_hanging():
    definition: dict = {}
    cursor = definition
    for i in range(60):
        cursor["nested"] = {}
        cursor = cursor["nested"]
    cursor["leaf"] = {"id": "too-deep", "__entity__": True, "type": "Dimension"}
    assert cja.extract_entity_references(definition, max_depth=10) == []


def test_parse_audit_log_extracts_user_and_component_sub_objects():
    row = cja.parse_audit_log({
        "id": "al1", "dateCreated": "2026-08-24T00:00:00Z", "action": "EDIT",
        "description": "Updated calculated metric: Conversion Rate",
        "user": {"id": "jordan.lee@acme.com", "email": "jordan.lee@acme.com"},
        "component": {"id": "cm1", "idType": "CALCULATED_METRIC", "name": "Conversion Rate"},
    })
    assert row["actor"] == "jordan.lee@acme.com"
    assert row["target"] == "Conversion Rate"
    assert row["action"] == "EDIT"


def test_parse_audit_log_does_not_crash_when_user_or_component_missing():
    row = cja.parse_audit_log({"id": "al1", "action": "CREATE"})
    assert row["actor"] == ""
    assert row["target"] == ""


# --- Quota -----------------------------------------------------------------------

def test_parse_quota_computes_percentage_used():
    row = quota.parse_quota({"name": "datasetExpirationQuota", "consumed": 42, "quota": 500})
    assert row["pct_used"] == 8.4


def test_parse_quota_is_high_uses_the_configured_threshold(monkeypatch):
    from aep_monitor.clients import quota as quota_module
    monkeypatch.setattr(quota_module.settings, "alert_quota_threshold_pct", 80.0)
    just_under = quota.parse_quota({"name": "x", "consumed": 79, "quota": 100})
    at_threshold = quota.parse_quota({"name": "x", "consumed": 80, "quota": 100})
    assert just_under["is_high"] is False
    assert at_threshold["is_high"] is True


def test_parse_quota_handles_a_zero_quota_without_dividing_by_zero():
    row = quota.parse_quota({"name": "x", "consumed": 0, "quota": 0})
    assert row["pct_used"] == 0.0
    assert row["is_high"] is False


# --- Observability Insights ----------------------------------------------------

def test_parse_metrics_response_sorts_datapoints_ascending_by_timestamp():
    raw = {"metricResponses": [{"name": "m1", "datapoints": [
        {"timestamp": "2026-08-20T00:00:00.000Z", "value": 30},
        {"timestamp": "2026-08-18T00:00:00.000Z", "value": 10},
        {"timestamp": "2026-08-19T00:00:00.000Z", "value": 20},
    ]}]}
    points = observability.parse_metrics_response(raw)["m1"]
    assert [p["value"] for p in points] == [10, 20, 30]
    assert points[-1]["value"] == 30  # "latest value" callers depend on this


def test_parse_metrics_response_puts_missing_timestamps_first_without_raising():
    raw = {"metricResponses": [{"name": "m1", "datapoints": [
        {"timestamp": "2026-08-19T00:00:00.000Z", "value": 20},
        {"timestamp": None, "value": -1},
    ]}]}
    points = observability.parse_metrics_response(raw)["m1"]
    assert points[0]["value"] == -1
    assert points[-1]["value"] == 20


def test_parse_metrics_response_handles_an_empty_or_malformed_envelope():
    assert observability.parse_metrics_response({}) == {}
    assert observability.parse_metrics_response({"metricResponses": "not-a-list"}) == {}


def test_parse_metrics_response_handles_a_plain_string_metric_field():
    """The exact live bug: a real Observability Insights response put the
    metric name directly as a string under entry["metric"], where the
    parser had assumed a nested {"name": ...} object
    (`entry.get("metric").get("name")`) — crashing with `'str' object has
    no attribute 'get'` in production. The string value must still be
    usable as the metric name, not just silently dropped."""
    raw = {"metricResponses": [{"metric": "timeseries.ingestion.dataset.recordsuccess.count", "datapoints": []}]}
    result = observability.parse_metrics_response(raw)
    assert "timeseries.ingestion.dataset.recordsuccess.count" in result


def test_parse_metrics_response_ignores_non_dict_entries_and_the_top_level_response():
    assert observability.parse_metrics_response("a plain string") == {}
    assert observability.parse_metrics_response({"metricResponses": ["not-a-dict", None]}) == {}


# --- Audit -----------------------------------------------------------------------

def test_parse_event_uses_adobes_confirmed_real_field_names():
    """Regression: reported live as 'Audit Log not displaying despite the
    permission being granted' — the real cause was two bugs, this one
    being that the confirmed real field names (assetName, userEmail) are
    different from what was originally guessed (target, actor)."""
    event = audit.parse_event({
        "id": "ae1", "action": "schema.updated", "userEmail": "jordan.lee@acme.com",
        "timestamp": "2026-08-24T00:00:00Z", "assetName": "XDM Individual Profile",
    })
    assert event["actor"] == "jordan.lee@acme.com"
    assert event["target"] == "XDM Individual Profile"


def test_parse_event_falls_back_across_known_field_name_variants():
    event = audit.parse_event({"eventId": "e1", "actionType": "schema.updated", "userEmail": "a@b.com"})
    assert event["event_id"] == "e1"
    assert event["action"] == "schema.updated"
    assert event["actor"] == "a@b.com"


def test_parse_event_does_not_crash_when_user_is_a_plain_string():
    event = audit.parse_event({"eventId": "e1", "user": "not-an-object"})
    assert event["actor"] == ""


def test_extract_events_reads_the_real_hal_style_embedded_envelope():
    """Regression: the second half of the live 'no events displayed, no
    error' report — events sit under _embedded.events (HAL-style), not a
    top-level events/data/items key as originally guessed. With the old
    guess, a real response parsed to an empty list silently: no
    exception, nothing for friendly_error() to catch, the page just said
    'No audit events returned' as if there genuinely were none."""
    raw = {"_embedded": {"events": [{"id": "e1"}, {"id": "e2"}]}, "page": {"size": 2}}
    events = audit._extract_events(raw)
    assert [e["id"] for e in events] == ["e1", "e2"]


def test_extract_events_falls_back_to_originally_guessed_top_level_keys():
    assert [e["id"] for e in audit._extract_events({"events": [{"id": "e1"}]})] == ["e1"]
    assert [e["id"] for e in audit._extract_events({"data": [{"id": "e1"}]})] == ["e1"]


def test_extract_events_handles_malformed_input_without_raising():
    assert audit._extract_events("not-a-dict") == []
    assert audit._extract_events({}) == []
    assert audit._extract_events({"_embedded": {"events": "not-a-list"}}) == []


# --- Catalog (AEP datasets) -------------------------------------------------------

def test_parse_dataset_takes_id_and_item_as_separate_arguments():
    # Confirmed real shape: Catalog's list response is keyed by dataset id
    # (an object, not an array) — the id only exists as the dict key, never
    # inside the value itself. parse_dataset() reflects that by taking both
    # explicitly rather than assuming a self-contained "id" field like every
    # other parser in this codebase.
    row = catalog.parse_dataset("5f1a2b3c", {"name": "Loyalty Events", "description": "x"})
    assert row["dataset_id"] == "5f1a2b3c"
    assert row["name"] == "Loyalty Events"


def test_parse_dataset_reads_enabled_true_out_of_the_tag_string_list():
    # Confirmed real shape: tags.unifiedProfile is a list of strings like
    # ["enabled:true"], not a boolean — a naive bool(tags.get("unifiedProfile"))
    # would incorrectly read True for ANY non-empty list, including
    # ["enabled:false"].
    row = catalog.parse_dataset("id1", {"tags": {"unifiedProfile": ["enabled:true"], "unifiedIdentity": ["enabled:false"]}})
    assert row["profile_enabled"] is True
    assert row["identity_enabled"] is False


def test_parse_dataset_defaults_enablement_to_false_when_tags_are_absent():
    row = catalog.parse_dataset("id1", {"name": "x"})
    assert row["profile_enabled"] is False
    assert row["identity_enabled"] is False


def test_parse_dataset_extracts_schema_id_from_schema_ref():
    row = catalog.parse_dataset("id1", {"schemaRef": {"id": "https://ns.adobe.com/acmecorp/schemas/loyalty-events", "contentType": "application/vnd.adobe.xed+json"}})
    assert row["schema_id"] == "https://ns.adobe.com/acmecorp/schemas/loyalty-events"


def test_parse_dataset_does_not_crash_when_tags_or_schema_ref_are_not_objects():
    row = catalog.parse_dataset("id1", {"tags": "not-an-object", "schemaRef": "not-an-object"})
    assert row["profile_enabled"] is False
    assert row["schema_id"] == ""


# --- Schema Registry (AEP) -------------------------------------------------------

def test_parse_schema_summary_uses_meta_alt_id_when_dollar_id_is_absent():
    row = schema_registry.parse_schema_summary({"meta:altId": "abc123", "title": "Loyalty Events"})
    assert row["schema_id"] == "abc123"
    assert row["title"] == "Loyalty Events"


def test_flatten_fields_produces_dotted_paths_for_nested_objects():
    schema = {
        "properties": {
            "timestamp": {"type": "string"},
            "_acmecorp": {
                "type": "object",
                "properties": {
                    "loyaltyId": {"type": "string", "title": "Loyalty ID"},
                    "pointsBalance": {"type": "integer"},
                },
            },
        }
    }
    fields = schema_registry.flatten_fields(schema)
    paths = {f["path"] for f in fields}
    assert paths == {"timestamp", "_acmecorp.loyaltyId", "_acmecorp.pointsBalance"}
    loyalty_id = next(f for f in fields if f["path"] == "_acmecorp.loyaltyId")
    assert loyalty_id["title"] == "Loyalty ID"


def test_flatten_fields_recurses_into_array_item_objects_with_bracket_marker():
    schema = {"properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "sku": {"type": "string"},
    }}}}}
    fields = schema_registry.flatten_fields(schema)
    assert fields[0]["path"] == "items[].sku"


def test_flatten_fields_is_sorted_and_handles_non_dict_input_without_raising():
    assert schema_registry.flatten_fields("not-a-schema") == []
    assert schema_registry.flatten_fields({}) == []
    schema = {"properties": {"z_field": {"type": "string"}, "a_field": {"type": "string"}}}
    fields = schema_registry.flatten_fields(schema)
    assert [f["path"] for f in fields] == ["a_field", "z_field"]


def test_flatten_fields_stops_at_max_depth_instead_of_hanging():
    # A pathologically deep (but well-formed) nested schema should still
    # terminate rather than recurse forever.
    schema: dict = {"properties": {}}
    cursor = schema["properties"]
    for i in range(20):
        cursor[f"level{i}"] = {"type": "object", "properties": {}}
        cursor = cursor[f"level{i}"]["properties"]
    cursor["leaf"] = {"type": "string"}
    fields = schema_registry.flatten_fields(schema, max_depth=5)
    assert fields == []  # the leaf sits deeper than max_depth, correctly dropped rather than raising


def test_extract_label_descriptors_keeps_only_the_label_type_from_a_grouped_response():
    """/tenant/descriptors groups by @type — extract_label_descriptors()
    must return only xdm:descriptorLabel, not every descriptor type."""
    grouped = {
        "xdm:descriptorLabel": [{"@type": "xdm:descriptorLabel", "xdm:sourceProperty": "/a"}],
        "xdm:descriptorIdentity": [{"@type": "xdm:descriptorIdentity", "xdm:sourceProperty": "/b"}],
    }
    items = schema_registry.extract_label_descriptors(grouped)
    assert len(items) == 1
    assert items[0]["xdm:sourceProperty"] == "/a"


def test_extract_label_descriptors_handles_a_flat_array_fallback():
    """The grouped-by-@type shape is this app's best-effort reading, not a
    confirmed one (see the docstring) — a flat array is handled too, in
    case that reading turns out wrong against a real tenant."""
    flat = [
        {"@type": "xdm:descriptorLabel", "xdm:sourceProperty": "/a"},
        {"@type": "xdm:descriptorIdentity", "xdm:sourceProperty": "/b"},
    ]
    items = schema_registry.extract_label_descriptors(flat)
    assert len(items) == 1
    assert items[0]["xdm:sourceProperty"] == "/a"


def test_extract_label_descriptors_returns_empty_for_an_unexpected_shape():
    assert schema_registry.extract_label_descriptors(None) == []
    assert schema_registry.extract_label_descriptors("not-a-response") == []
    assert schema_registry.extract_label_descriptors({"xdm:descriptorLabel": "not-a-list"}) == []


def test_parse_label_descriptor_normalizes_the_json_pointer_to_a_dotted_path():
    # xdm:sourceSchema is a field-group id in real responses (confirmed
    # live), not the composite schema's own $id — parse_label_descriptor()
    # just carries the raw value through either way; it's
    # fetch_schema_field_labels() in data.py that knows not to match on it.
    row = schema_registry.parse_label_descriptor({
        "xdm:sourceSchema": "https://ns.adobe.com/acmecorp/mixins/loyalty-program-details",
        "xdm:sourceProperty": "/_acmecorp/loyaltyId",
        "xdm:labels": ["core/I2", "core/C1"],
    })
    assert row["path"] == "_acmecorp.loyaltyId"
    assert row["labels"] == ["core/I2", "core/C1"]
    assert row["source_schema"] == "https://ns.adobe.com/acmecorp/mixins/loyalty-program-details"


def test_parse_label_descriptor_defaults_to_no_labels_when_absent_or_malformed():
    assert schema_registry.parse_label_descriptor({"xdm:sourceProperty": "/a"})["labels"] == []
    assert schema_registry.parse_label_descriptor({"xdm:sourceProperty": "/a", "xdm:labels": "not-a-list"})["labels"] == []


# --- Segmentation Service ---------------------------------------------------

def test_parse_segment_extracts_schema_ref():
    row = segmentation.parse_segment({"id": "seg-1", "name": "High Value", "description": "x", "schema": {"name": "Loyalty Events"}})
    assert row["segment_id"] == "seg-1"
    assert row["schema_ref"] == "Loyalty Events"


def test_parse_segment_falls_back_to_id_when_name_missing():
    row = segmentation.parse_segment({"id": "seg-1"})
    assert row["name"] == "seg-1"
    assert row["schema_ref"] == ""


def test_parse_segment_job_flags_a_failed_job():
    row = segmentation.parse_segment_job({"id": "job-1", "segments": [{"segmentId": "seg-1"}], "status": "FAILED"})
    assert row["status"] == "failed"
    assert row["is_bad"] is True
    assert row["segment_id"] == "seg-1"


def test_parse_segment_job_does_not_flag_a_succeeded_job():
    """Confirmed live: the profile-count field is "segmentedProfileCounter"
    (with the "er"), not "segmentedProfileCount" as originally guessed."""
    row = segmentation.parse_segment_job({"id": "job-1", "status": "SUCCEEDED", "metrics": {"segmentedProfileCounter": 100}})
    assert row["is_bad"] is False
    assert row["segmented_profile_count"] == 100


def test_parse_segment_job_does_not_crash_when_metrics_is_not_an_object():
    row = segmentation.parse_segment_job({"id": "job-1", "status": "SUCCEEDED", "metrics": "not-an-object"})
    assert row["segmented_profile_count"] is None


def test_parse_segment_job_does_not_crash_when_segments_is_missing_or_malformed():
    assert segmentation.parse_segment_job({"id": "job-1", "status": "SUCCEEDED"})["segment_id"] == ""
    assert segmentation.parse_segment_job({"id": "job-1", "status": "SUCCEEDED", "segments": "not-a-list"})["segment_id"] == ""
    assert segmentation.parse_segment_job({"id": "job-1", "status": "SUCCEEDED", "segments": []})["segment_id"] == ""


def test_parse_segment_job_converts_epoch_millisecond_timestamps():
    """Confirmed live: creationTime/updateTime are epoch milliseconds, not
    ISO strings like startTime/endTime elsewhere in this app — originally
    guessed as ISO strings under the wrong field names entirely."""
    row = segmentation.parse_segment_job({"id": "job-1", "status": "SUCCEEDED", "creationTime": 1700000000000, "updateTime": 1700000060000})
    assert row["started_at"].startswith("2023-11-14")
    assert row["ended_at"].startswith("2023-11-14")


# --- Query Service -----------------------------------------------------------

def test_parse_query_flags_a_failed_query():
    row = query_service.parse_query({"id": "q-1", "name": "x", "state": "FAILED", "errors": [{"code": "E1", "message": "timeout"}]})
    assert row["is_bad"] is True
    assert row["error_message"] == "timeout"


def test_parse_query_extracts_sql_from_the_nested_request_object():
    """Confirmed live via Adobe's own docs example: `sql` (and `dbName`)
    live under `request`, not top-level — the original guess put them
    top-level and always returned "" against a real tenant."""
    row = query_service.parse_query({"id": "q-1", "state": "SUCCESS", "request": {"sql": "SELECT 1", "dbName": "prod:all"}, "client": "Adobe Query Service UI"})
    assert row["sql"] == "SELECT 1"
    assert row["db_name"] == "prod:all"
    assert row["client_type"] == "Adobe Query Service UI"


def test_parse_query_falls_back_to_top_level_sql_for_a_differently_shaped_tenant():
    row = query_service.parse_query({"id": "q-1", "state": "SUCCESS", "sql": "SELECT 1"})
    assert row["sql"] == "SELECT 1"


def test_parse_query_defaults_sql_and_client_type_to_empty_when_absent():
    row = query_service.parse_query({"id": "q-1", "state": "SUCCESS"})
    assert row["sql"] == ""
    assert row["client_type"] == ""


def test_parse_query_error_message_handles_a_list_of_plain_strings_too():
    """Adobe's own docs example only shows an empty errors array, so a
    populated entry's exact shape isn't confirmed — this pins the
    string-list fallback alongside the {message: ...} object case above."""
    row = query_service.parse_query({"id": "q-1", "state": "FAILED", "errors": ["timeout"]})
    assert row["error_message"] == "timeout"


def test_parse_query_has_no_name_field_on_the_real_object_so_falls_back_to_id():
    """Confirmed live: the raw query object has no "name" field at all —
    unlike segments/flows elsewhere in this app. This is the normal path
    here, not an edge case."""
    row = query_service.parse_query({"id": "q-1", "state": "SUCCESS", "request": {"sql": "SELECT 1"}})
    assert row["name"] == "q-1"


def test_parse_query_does_not_flag_a_successful_query():
    row = query_service.parse_query({"id": "q-1", "name": "x", "state": "SUCCESS"})
    assert row["is_bad"] is False


def test_parse_query_falls_back_to_ad_hoc_label_when_name_missing():
    row = query_service.parse_query({"id": "q-1", "state": "SUCCESS"})
    assert row["name"] == "q-1"


def test_parse_query_detects_scheduled_via_schedule_id():
    row = query_service.parse_query({"id": "q-1", "state": "SUCCESS", "scheduleId": "sch-1"})
    assert row["is_scheduled"] is True


def test_parse_schedule_reads_enabled_state_and_query_name():
    row = query_service.parse_schedule({"id": "sch-1", "state": "ENABLED", "query": {"name": "Daily rollup"}})
    assert row["enabled"] is True
    assert row["name"] == "Daily rollup"


def test_parse_schedule_defaults_to_disabled_and_id_as_name():
    row = query_service.parse_schedule({"id": "sch-1"})
    assert row["enabled"] is False
    assert row["name"] == "sch-1"


# --- User Management API ------------------------------------------------------

def test_parse_user_builds_display_name_from_first_and_last_name():
    row = user_management.parse_user({"id": "u1", "email": "jordan.lee@acme.com", "firstname": "Jordan", "lastname": "Lee"})
    assert row["display_name"] == "Jordan Lee"
    assert row["user_id"] == "u1"


def test_parse_user_falls_back_to_email_when_no_name_is_set():
    row = user_management.parse_user({"id": "u1", "email": "jordan.lee@acme.com"})
    assert row["display_name"] == "jordan.lee@acme.com"


def test_parse_user_falls_back_to_username_when_no_name_or_email():
    row = user_management.parse_user({"id": "u1", "username": "jordan.lee"})
    assert row["display_name"] == "jordan.lee"


def test_parse_user_handles_a_missing_id():
    """Confirmed live: id is "optional if unpopulated" per Adobe's own
    docs — a technical/service account entry (if it appears at all) may
    have no id, which must not crash the parser."""
    row = user_management.parse_user({"email": "svc@acme.com"})
    assert row["user_id"] == ""
    assert row["display_name"] == "svc@acme.com"
