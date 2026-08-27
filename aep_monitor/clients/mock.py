from __future__ import annotations

"""Sample data for demo/offline use, shaped exactly like the raw API
responses (not the parsed rows) — so it flows through the same aep.py /
reactor.py / cja.py / audit.py parse_*() functions the live path uses.
Swapping MOCK_MODE=false changes nothing else in the app.
"""

import copy
from datetime import datetime, timedelta, timezone
from typing import Any


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _millis_ago(minutes_ago: int) -> int:
    """Segment Jobs' creationTime/updateTime are epoch milliseconds
    (confirmed live) — a genuinely different timestamp convention from
    every other client's ISO strings, so mock data needs its own helper
    rather than reusing _iso()."""
    return int((datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).timestamp() * 1000)


# --- AEP Flow Service --------------------------------------------------------

MOCK_FLOWS: list[dict[str, Any]] = [
    {"id": "flow-web-events", "name": "Web SDK — Prod Events", "state": "enabled", "flowSpec": {"id": "spec-web-sdk"}, "createdAt": _iso(60 * 24 * 40)},
    {"id": "flow-crm-batch", "name": "CRM Customer Batch (S3)", "state": "enabled", "flowSpec": {"id": "spec-s3"}, "createdAt": _iso(60 * 24 * 90)},
    {"id": "flow-mobile-events", "name": "Mobile SDK — Prod Events", "state": "enabled", "flowSpec": {"id": "spec-mobile-sdk"}, "createdAt": _iso(60 * 24 * 20)},
    # Deliberately a destination/activation flow, not an ingestion one — the
    # same /flows endpoint returns both undifferentiated (see aep.py's
    # parse_flow() docstring); its name alone reads like ingestion ("Export"
    # sounds outbound but so did "CRM Batch" before you checked), which is
    # exactly the ambiguity connector_name resolves.
    {"id": "flow-loyalty-export", "name": "Loyalty Segment Export", "state": "disabled", "flowSpec": {"id": "spec-google-ads"}, "createdAt": _iso(60 * 24 * 10)},
]

MOCK_FLOW_SPECS: list[dict[str, Any]] = [
    {"id": "spec-web-sdk", "name": "Adobe Experience Platform Web SDK"},
    {"id": "spec-s3", "name": "Amazon S3"},
    {"id": "spec-mobile-sdk", "name": "Adobe Experience Platform Mobile SDK"},
    {"id": "spec-google-ads", "name": "Google Ads Data Connector"},
]

MOCK_RUNS: dict[str, list[dict[str, Any]]] = {
    "flow-web-events": [
        {
            "id": "run-we-3", "flowId": "flow-web-events",
            "metrics": {
                "recordSummary": {"inputCount": 482_113, "outputCount": 482_113, "failedCount": 0},
                "statusSummary": {"status": "success"},
                "durationSummary": {"startedAtUTC": _iso(12), "completedAtUTC": _iso(9)},
            },
        },
    ],
    "flow-crm-batch": [
        {
            "id": "run-crm-9", "flowId": "flow-crm-batch",
            "metrics": {
                "recordSummary": {"inputCount": 18_204, "outputCount": 17_960, "failedCount": 244},
                "statusSummary": {"status": "failed"},
                "durationSummary": {"startedAtUTC": _iso(180), "completedAtUTC": _iso(150)},
            },
        },
    ],
    "flow-mobile-events": [
        {
            "id": "run-me-5", "flowId": "flow-mobile-events",
            "metrics": {
                "recordSummary": {"inputCount": 91_400, "outputCount": 91_400, "failedCount": 0},
                "statusSummary": {"status": "success"},
                "durationSummary": {"startedAtUTC": _iso(30), "completedAtUTC": _iso(27)},
            },
        },
    ],
    "flow-loyalty-export": [
        {
            "id": "run-le-2", "flowId": "flow-loyalty-export",
            "metrics": {
                "recordSummary": {"inputCount": 5_002, "outputCount": 5_002, "failedCount": 0},
                "statusSummary": {"status": "success"},
                "durationSummary": {"startedAtUTC": _iso(60 * 24 * 3), "completedAtUTC": _iso(60 * 24 * 3 - 5)},
            },
        },
    ],
}


# --- Reactor (Data Collection) ----------------------------------------------

MOCK_COMPANIES: list[dict[str, Any]] = [{"id": "CO12345", "attributes": {"name": "Acme Corp"}}]

MOCK_PROPERTIES: list[dict[str, Any]] = [
    {"id": "PR1", "attributes": {"name": "acme.com — Web"}},
    {"id": "PR2", "attributes": {"name": "Acme Mobile App"}},
]

MOCK_EXTENSIONS: dict[str, list[dict[str, Any]]] = {
    "PR1": [
        # "settings" is a JSON-*encoded string* here, not a nested object —
        # confirmed via Adobe's own docs example response shape (see
        # clients/reactor.py's _extract_datastream_ids() docstring).
        # Reported live: a property configures a *different* datastream per
        # environment, not just one — production's id matches
        # datastream_map.sample.json's first entry (-> "Loyalty Events"),
        # staging matches its second entry (-> "Web SDK Events"), and
        # development is deliberately left unmapped to also demonstrate
        # that case out of the box, same as every other mock-first feature.
        {
            "id": "EX1",
            "attributes": {
                "name": "Adobe Experience Platform Web SDK", "published": True, "review_status": "approved",
                "settings": (
                    "{\"datastreamId\": \"00000000-0000-0000-0000-000000000000\", "
                    "\"stagingDatastreamId\": \"11111111-1111-1111-1111-111111111111\", "
                    "\"developmentEdgeConfigId\": \"33333333-3333-3333-3333-333333333333\", "
                    "\"edgeDomain\": \"edge.acmecorp.com\"}"
                ),
            },
        },
        {"id": "EX2", "attributes": {"name": "Core", "published": True, "review_status": "approved"}},
        {"id": "EX3", "attributes": {"name": "Custom Consent Extension", "published": False, "review_status": "rejected"}},
    ],
    "PR2": [
        {"id": "EX4", "attributes": {"name": "Adobe Experience Platform Mobile SDK", "published": True, "review_status": "approved"}},
    ],
}

MOCK_LIBRARIES: dict[str, list[dict[str, Any]]] = {
    "PR1": [
        {"id": "LB1", "attributes": {"name": "Production", "state": "published", "build_date": _iso(60 * 6)}},
        {"id": "LB2", "attributes": {"name": "Staging — Consent Rework", "state": "failed", "build_date": _iso(45)}},
    ],
    "PR2": [
        {"id": "LB3", "attributes": {"name": "Production", "state": "published", "build_date": _iso(60 * 24)}},
    ],
}

MOCK_RULES: dict[str, list[dict[str, Any]]] = {
    "PR1": [
        {"id": "RL1", "attributes": {"name": "Page View — All Pages", "enabled": True, "published": True}},
        {"id": "RL2", "attributes": {"name": "Checkout Complete", "enabled": True, "published": True}},
    ],
    "PR2": [
        {"id": "RL3", "attributes": {"name": "App Launch", "enabled": True, "published": True}},
    ],
}

# stage is exactly one of development/staging/production per Adobe's docs;
# PR1's production build deliberately failed so the DC page and alerts.py
# have a real bad case to demonstrate, PR2's is healthy for contrast.
MOCK_ENVIRONMENTS: dict[str, list[dict[str, Any]]] = {
    "PR1": [
        {"id": "EN1", "attributes": {"name": "Development", "stage": "development", "status": "succeeded"}},
        {"id": "EN2", "attributes": {"name": "Staging", "stage": "staging", "status": "succeeded"}},
        {"id": "EN3", "attributes": {"name": "Production", "stage": "production", "status": "failed"}},
    ],
    "PR2": [
        {"id": "EN4", "attributes": {"name": "Development", "stage": "development", "status": "succeeded"}},
        {"id": "EN5", "attributes": {"name": "Production", "stage": "production", "status": "succeeded"}},
    ],
}

MOCK_DATA_ELEMENTS: dict[str, list[dict[str, Any]]] = {
    "PR1": [
        {"id": "DE1", "attributes": {"name": "Cart Total", "enabled": True, "published": True, "dirty": False, "review_status": "approved"}},
        {"id": "DE2", "attributes": {"name": "Consent Status", "enabled": True, "published": False, "dirty": True, "review_status": "unsubmitted"}},
    ],
    "PR2": [
        {"id": "DE3", "attributes": {"name": "App Version", "enabled": True, "published": True, "dirty": False, "review_status": "approved"}},
    ],
}

# JSON:API shape, matching every other Reactor mock in this section.
MOCK_DC_AUDIT_EVENTS: list[dict[str, Any]] = [
    {"id": "ae-dc-1", "type": "audit_events", "attributes": {
        "attributed_to_display_name": "Jordan Lee", "attributed_to_email": "jordan.lee@acme.com",
        "created_at": _iso(20), "display_name": "Custom Consent Extension", "type_of": "extension.updated",
    }},
    {"id": "ae-dc-2", "type": "audit_events", "attributes": {
        "attributed_to_display_name": "Sam Ortiz", "attributed_to_email": "sam.ortiz@acme.com",
        "created_at": _iso(180), "display_name": "Production", "type_of": "library.published",
    }},
]


# --- CJA ---------------------------------------------------------------------

# Shaped like the real response *with* `expansion=name,description,owner,
# isDeleted,isDisabled,modified` applied (list_connections() always requests
# it — see clients/cja.py) — none of these fields exist on a bare /connections
# response otherwise. No "status"/"serviceStatus" field exists on this API at
# all (confirmed via Adobe's docs); isDeleted/isDisabled are the only real
# health signals, which parse_connection() derives a status label from.
# dataSets links each connection to its constituent AEP datasets by id —
# confirmed live via Adobe's docs (see clients/cja.py's parse_connection())
# as the one genuine cross-product link between an AEP dataset and a CJA
# connection. Ids match MOCK_DATASETS below, for the Overview page's
# end-to-end lineage view.
MOCK_CONNECTIONS: list[dict[str, Any]] = [
    {
        "id": "conn-web-mobile", "name": "Web + Mobile Unified", "isDeleted": False, "isDisabled": False, "modified": _iso(60 * 5),
        "dataSets": [
            {"dataSetId": "5f1a2b3c4d5e6f7a8b9c0d1e", "domain": "catalog", "type": "event", "name": "Loyalty Events", "streaming": True},
            {"dataSetId": "6a2b3c4d5e6f7a8b9c0d1e2f", "domain": "catalog", "type": "event", "name": "Web SDK Events", "streaming": True},
        ],
    },
    {
        "id": "conn-crm", "name": "CRM Connection", "isDeleted": False, "isDisabled": True, "modified": _iso(60 * 200),
        "dataSets": [
            {"dataSetId": "7b3c4d5e6f7a8b9c0d1e2f3a", "domain": "catalog", "type": "event", "name": "CRM Customer Batch", "streaming": False},
        ],
    },
]

# Shaped like the real response with expansion=name,description,owner,
# parentDataGroupId applied — the FK back to the parent connection is
# `parentDataGroupId`, not `connectionId`/`dataConnectionId` as originally
# guessed (see parse_dataview()).
MOCK_DATAVIEWS: list[dict[str, Any]] = [
    {"id": "dv-exec", "name": "Executive Dashboard View", "parentDataGroupId": "conn-web-mobile", "owner": {"name": "Data Team"}},
    {"id": "dv-mktg", "name": "Marketing Attribution View", "parentDataGroupId": "conn-web-mobile", "owner": {"name": "Marketing Analytics"}},
]

# Keyed by dataview id, matching list_dimensions()/list_metrics()'s real shape.
# dv-mktg deliberately overlaps partially with dv-exec (shares "Marketing
# Channel" but with a different type, has its own "Campaign" dimension,
# lacks "Page") so the Compare page's CJA Data Views tab has a real,
# illustrative diff to show in mock mode — not just "everything only in A".
MOCK_DIMENSIONS: dict[str, list[dict[str, Any]]] = {
    "dv-exec": [
        {"id": "variables/page", "name": "Page", "description": "Page name from the Web SDK", "type": "string", "sourceFieldName": "web.webPageDetails.name", "dataSetType": "event", "approved": True},
        {"id": "variables/marketingchannel", "name": "Marketing Channel", "description": "First-touch marketing channel", "type": "string", "sourceFieldName": "marketing.trackingCode", "dataSetType": "event", "approved": True},
    ],
    "dv-mktg": [
        {"id": "variables/marketingchannel", "name": "Marketing Channel", "description": "First-touch marketing channel", "type": "enum", "sourceFieldName": "marketing.trackingCode", "dataSetType": "event", "approved": True},
        {"id": "variables/campaign", "name": "Campaign", "description": "Campaign name", "type": "string", "sourceFieldName": "marketing.campaignName", "dataSetType": "event", "approved": False},
    ],
}

MOCK_METRICS: dict[str, list[dict[str, Any]]] = {
    "dv-exec": [
        {"id": "metrics/visits", "name": "Visits", "description": "Count of visits", "type": "int", "sourceFieldName": "", "dataSetType": "event", "approved": True},
        {"id": "metrics/revenue", "name": "Revenue", "description": "Order revenue", "type": "currency", "sourceFieldName": "commerce.order.priceTotal", "dataSetType": "event", "approved": True},
    ],
    "dv-mktg": [
        {"id": "metrics/revenue", "name": "Revenue", "description": "Order revenue", "type": "currency", "sourceFieldName": "commerce.order.priceTotal", "dataSetType": "event", "approved": True},
    ],
}

# A flat list with a dataId field, matching the real /calculatedmetrics
# response shape (org-wide, not grouped per data view like
# MOCK_DIMENSIONS/MOCK_METRICS above) — data.py filters this client-side
# by dataId, the same way it'll filter the real org-wide list live.
MOCK_CALCULATED_METRICS: list[dict[str, Any]] = [
    {"id": "cm-conv-rate", "name": "Conversion Rate", "description": "Orders / Visits", "type": "percent", "polarity": "positive", "dataId": "dv-exec", "owner": {"ownerId": 12345}},
    {"id": "cm-aov", "name": "Average Order Value", "description": "Revenue / Orders", "type": "currency", "polarity": "positive", "dataId": "dv-exec", "owner": {"ownerId": 12345}},
    {"id": "cm-cost-per-lead", "name": "Cost per Lead", "description": "Ad spend / Leads", "type": "currency", "polarity": "negative", "dataId": "dv-mktg", "owner": {"ownerId": 67890}},
]

# Shaped like the confirmed real /projects list response — a bare array,
# not a {"content": [...]} envelope like every other CJA list endpoint
# (see clients/cja.py's list_projects() docstring).
# owner.name is null and owner.ownerId/imsUserId are opaque ids — matching
# a real response without `expansion=ownerFullName` — with the resolved
# display name only appearing in the top-level `ownerFullName` field
# expansion adds (see list_projects()'s docstring for why that field's
# placement isn't fully confirmed from a real populated example; parse_project()
# checks both plausible spots defensively).
MOCK_PROJECTS: list[dict[str, Any]] = [
    {"id": "proj-exec-1", "name": "Executive Weekly Report", "description": "", "type": "project", "dataId": "dv-exec", "owner": {"imsUserId": "391C5A0C536B86680A490D44@techacct.adobe.com", "ownerId": "391C5A0C536B86680A490D44@techacct.adobe.com", "name": None, "type": "imsUser"}, "ownerFullName": "Jordan Lee", "created": _iso(60 * 24 * 20)},
    {"id": "proj-exec-2", "name": "Conversion Deep Dive", "description": "", "type": "project", "dataId": "dv-exec", "owner": {"imsUserId": "EDDA4A2E6995C6800A495F90@f6de294463f5897c495fa8.e", "ownerId": "EDDA4A2E6995C6800A495F90@f6de294463f5897c495fa8.e", "name": None, "type": "imsUser"}, "ownerFullName": "Sam Ortiz", "created": _iso(60 * 24 * 5)},
    {"id": "proj-mktg-1", "name": "Campaign Performance", "description": "", "type": "project", "dataId": "dv-mktg", "owner": {"imsUserId": "EDDA4A2E6995C6800A495F90@f6de294463f5897c495fa8.e", "ownerId": "EDDA4A2E6995C6800A495F90@f6de294463f5897c495fa8.e", "name": None, "type": "imsUser"}, "ownerFullName": "Sam Ortiz", "created": _iso(60 * 24 * 10)},
]


def _mock_entity(entity_id: str, entity_type: str, name: str) -> dict[str, Any]:
    return {"id": entity_id, "__entity__": True, "type": entity_type, "__metaData__": {"name": name}}


# Shaped like the confirmed real get_project(expansion=definition) response
# — a `definition` object whose deeply nested panel/subPanel/reportlet tree
# holds component references tagged `__entity__: true` (confirmed live on
# an empty test project's date-range/data-view entries; the exact `type`
# strings for a Dimension/Metric/CalculatedMetric reference specifically
# weren't confirmed from a real populated project, so these are this app's
# best-effort naming, not verified against a live example — see
# extract_entity_references()'s docstring). Deliberately built so some
# MOCK_DIMENSIONS/MOCK_METRICS/MOCK_CALCULATED_METRICS entries are
# referenced here and some aren't (e.g. "Marketing Channel" and "Revenue"
# are never referenced by any project) — so mock mode demonstrates both
# "used in N projects" and "unused" cases, not just the happy path.
MOCK_PROJECT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "proj-exec-1": {"workspaces": [{"id": "ws-1", "name": "", "panels": [{
        "id": "panel-1", "name": "Freeform", "reportSuite": _mock_entity("dv-exec", "ReportSuite", "Executive Dashboard View"),
        "subPanels": [{"id": "sub-1", "reportlet": {"columnTree": {"nodes": [
            _mock_entity("variables/page", "Dimension", "Page"),
            _mock_entity("metrics/visits", "Metric", "Visits"),
            _mock_entity("cm-conv-rate", "CalculatedMetric", "Conversion Rate"),
        ]}}}],
    }]}]},
    "proj-exec-2": {"workspaces": [{"id": "ws-2", "name": "", "panels": [{
        "id": "panel-2", "name": "Freeform", "reportSuite": _mock_entity("dv-exec", "ReportSuite", "Executive Dashboard View"),
        "subPanels": [{"id": "sub-2", "reportlet": {"columnTree": {"nodes": [
            _mock_entity("cm-conv-rate", "CalculatedMetric", "Conversion Rate"),
            _mock_entity("cm-aov", "CalculatedMetric", "Average Order Value"),
        ]}}}],
    }]}]},
    "proj-mktg-1": {"workspaces": [{"id": "ws-3", "name": "", "panels": [{
        "id": "panel-3", "name": "Freeform", "reportSuite": _mock_entity("dv-mktg", "ReportSuite", "Marketing Attribution View"),
        "subPanels": [{"id": "sub-3", "reportlet": {"columnTree": {"nodes": [
            _mock_entity("variables/campaign", "Dimension", "Campaign"),
            _mock_entity("cm-cost-per-lead", "CalculatedMetric", "Cost per Lead"),
        ]}}}],
    }]}]},
}

# Matches the confirmed real response shape (content[] with user/component
# sub-objects) — not the auditlogs/api/v1 namespace's own guessed shape,
# since Adobe's docs gave a complete example this time.
MOCK_CJA_AUDIT_LOGS: list[dict[str, Any]] = [
    {
        "id": "cja-al-1", "dateCreated": _iso(10), "action": "EDIT",
        "description": "Updated calculated metric: Conversion Rate",
        "user": {"id": "jordan.lee@acme.com", "idType": "IMS", "name": "Jordan Lee", "email": "jordan.lee@acme.com"},
        "component": {"id": "cm-conv-rate", "idType": "CALCULATED_METRIC", "name": "Conversion Rate"},
    },
    {
        "id": "cja-al-2", "dateCreated": _iso(240), "action": "CREATE",
        "description": "Created data view: Marketing Attribution View",
        "user": {"id": "sam.ortiz@acme.com", "idType": "IMS", "name": "Sam Ortiz", "email": "sam.ortiz@acme.com"},
        "component": {"id": "dv-mktg", "idType": "DATA_VIEW", "name": "Marketing Attribution View"},
    },
]


# --- Schema Registry (AEP) -----------------------------------------------------

MOCK_SCHEMAS: list[dict[str, Any]] = [
    {"$id": "https://ns.adobe.com/acmecorp/schemas/loyalty-events", "title": "Loyalty Events"},
    {"$id": "https://ns.adobe.com/acmecorp/schemas/web-events", "title": "Web SDK Events"},
]

MOCK_SCHEMA_DETAIL: dict[str, dict[str, Any]] = {
    "https://ns.adobe.com/acmecorp/schemas/loyalty-events": {
        "$id": "https://ns.adobe.com/acmecorp/schemas/loyalty-events",
        "title": "Loyalty Events",
        "properties": {
            "timestamp": {"type": "string", "format": "date-time", "title": "Timestamp"},
            "_acmecorp": {
                "type": "object",
                "properties": {
                    "loyaltyId": {"type": "string", "title": "Loyalty ID", "description": "Program member identifier"},
                    "pointsBalance": {"type": "integer", "title": "Points Balance"},
                    "tier": {"type": "string", "title": "Membership Tier", "description": "bronze/silver/gold/platinum"},
                },
            },
        },
    },
}

# Shaped like the real /tenant/descriptors response, confirmed live —
# grouped by @type, each entry a full descriptor object rather than a link
# string. `xdm:sourceSchema` deliberately points at a field-group id
# (".../mixins/...", not ".../schemas/loyalty-events") to mirror what a
# real tenant actually returns (confirmed live: sourceSchema is the field
# group that *defines* the field, not the composite schema that includes
# it) — this is why data.py's fetch_schema_field_labels() matches by field
# *path* against the schema's own flattened fields, not by sourceSchema. A
# non-label descriptor type, and a label descriptor for a path that
# doesn't exist in Loyalty Events' mock schema at all, are both included
# deliberately, so mock mode actually exercises "only xdm:descriptorLabel,
# and only paths this schema actually has" instead of both going untested.
MOCK_DESCRIPTORS: dict[str, list[dict[str, Any]]] = {
    "xdm:descriptorLabel": [
        {
            # Multiple codes on one field, deliberately — mirrors a real
            # tenant's response (a single descriptor's own xdm:labels array
            # can hold several) and is what originally exposed the
            # SDR table's Labels column truncating multi-label cells.
            "@id": "desc-loyaltyid-label", "@type": "xdm:descriptorLabel",
            "xdm:sourceSchema": "https://ns.adobe.com/acmecorp/mixins/loyalty-program-details",
            "xdm:sourceVersion": 1, "xdm:sourceProperty": "/_acmecorp/loyaltyId",
            "xdm:labels": ["core/I2", "custom/Restricted", "custom/Confidential"],
        },
        {
            "@id": "desc-pointsbalance-label", "@type": "xdm:descriptorLabel",
            "xdm:sourceSchema": "https://ns.adobe.com/acmecorp/mixins/loyalty-program-details",
            "xdm:sourceVersion": 1, "xdm:sourceProperty": "/_acmecorp/pointsBalance",
            "xdm:labels": ["core/C1"],
        },
        {
            "@id": "desc-unrelated-label", "@type": "xdm:descriptorLabel",
            "xdm:sourceSchema": "https://ns.adobe.com/acmecorp/mixins/some-other-field-group",
            "xdm:sourceVersion": 1, "xdm:sourceProperty": "/notInAnyMockSchema/someField",
            "xdm:labels": ["core/S2"],
        },
    ],
    "xdm:descriptorIdentity": [
        {
            "@id": "desc-loyaltyid-identity", "@type": "xdm:descriptorIdentity",
            "xdm:sourceSchema": "https://ns.adobe.com/acmecorp/mixins/loyalty-program-details",
            "xdm:sourceVersion": 1, "xdm:sourceProperty": "/_acmecorp/loyaltyId",
        },
    ],
}


def mock_schema_fields_for_sandbox(schema_id: str, sandbox: str) -> dict[str, Any]:
    """The base schema, perturbed for a non-prod sandbox — a field
    in development that prod doesn't have yet, and a changed description
    on an existing field — so the Compare page's Schemas tab has a real,
    illustrative diff to show in mock mode instead of "identical, nothing
    to see" (real schemas *do* vary per sandbox; mock data otherwise
    wouldn't, since the schema registry mocks don't naturally know about
    sandboxes the way the AEP flow/observability mocks do)."""
    base = MOCK_SCHEMA_DETAIL.get(schema_id, {})
    if not base or not sandbox or sandbox == "prod":
        return base
    varied = copy.deepcopy(base)
    tenant_props = varied.get("properties", {}).get("_acmecorp", {}).get("properties", {})
    if isinstance(tenant_props, dict):
        tenant_props["loyaltyTier2"] = {
            "type": "string", "title": "Loyalty Tier (v2)", "description": "New tiering field, in development",
        }
        if "tier" in tenant_props:
            tenant_props["tier"] = {**tenant_props["tier"], "description": "bronze/silver/gold/platinum/diamond"}
    return varied


# --- Catalog (AEP datasets) -------------------------------------------------------
# ID-keyed object, matching the real Catalog Service /dataSets response shape
# (see clients/catalog.py's module docstring — deliberately not an array,
# unlike every other mock in this file).
MOCK_DATASETS: dict[str, dict[str, Any]] = {
    "5f1a2b3c4d5e6f7a8b9c0d1e": {
        "name": "Loyalty Events", "description": "Streaming loyalty program events",
        "schemaRef": {"id": "https://ns.adobe.com/acmecorp/schemas/loyalty-events", "contentType": "application/vnd.adobe.xed+json"},
        "tags": {"unifiedProfile": ["enabled:true"], "unifiedIdentity": ["enabled:true"]},
        "created": _iso(60 * 24 * 90), "updated": _iso(60 * 6),
    },
    "6a2b3c4d5e6f7a8b9c0d1e2f": {
        "name": "Web SDK Events", "description": "Raw web events from the Web SDK datastream",
        "schemaRef": {"id": "https://ns.adobe.com/acmecorp/schemas/web-events", "contentType": "application/vnd.adobe.xed+json"},
        "tags": {"unifiedProfile": ["enabled:true"], "unifiedIdentity": ["enabled:false"]},
        "created": _iso(60 * 24 * 120), "updated": _iso(60 * 2),
    },
    "7b3c4d5e6f7a8b9c0d1e2f3a": {
        "name": "CRM Customer Batch", "description": "Nightly CRM customer profile batch",
        "schemaRef": {"id": "https://ns.adobe.com/acmecorp/schemas/loyalty-events", "contentType": "application/vnd.adobe.xed+json"},
        "tags": {"unifiedProfile": ["enabled:false"], "unifiedIdentity": ["enabled:false"]},
        "created": _iso(60 * 24 * 60), "updated": _iso(60 * 24 * 3),
    },
}


def mock_datasets_for_sandbox(sandbox: str) -> dict[str, dict[str, Any]]:
    """MOCK_DATASETS, perturbed for a non-prod sandbox — Identity Service
    not yet enabled on Loyalty Events there — so the Compare page's
    Datasets tab has a real, illustrative diff to show in mock mode, same
    reasoning as mock_schema_fields_for_sandbox() above. A second,
    independent perturbation (Web SDK Events' description) on a *different*
    dataset demonstrates description diffing distinctly, without changing
    what's true of Loyalty Events specifically (identity_enabled is still
    the only thing that differs for it — see
    test_fetch_dataset_diff_flags_identity_enabled_changed_in_non_prod_sandbox)."""
    if not sandbox or sandbox == "prod":
        return MOCK_DATASETS
    varied = copy.deepcopy(MOCK_DATASETS)
    varied["5f1a2b3c4d5e6f7a8b9c0d1e"]["tags"]["unifiedIdentity"] = ["enabled:false"]
    varied["6a2b3c4d5e6f7a8b9c0d1e2f"]["description"] = "Raw web events from the Web SDK datastream (schema under revision)"
    return varied


# --- Observability Insights ---------------------------------------------------

def _mock_observability_response(days: int = 7) -> dict[str, Any]:
    """Shaped like the V2 /metrics response: metricResponses[].datapoints[].
    A rising batchfailed count near the end demonstrates the alert-worthy case."""
    now = datetime.now(timezone.utc)
    success_points = [
        {"timestamp": (now - timedelta(days=days - i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "value": 480_000 + i * 3_000}
        for i in range(days + 1)
    ]
    failed_points = [
        {"timestamp": (now - timedelta(days=days - i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "value": 40 if i < days else 1_800}
        for i in range(days + 1)
    ]
    return {
        "metricResponses": [
            {"name": "timeseries.ingestion.dataset.recordsuccess.count", "datapoints": success_points},
            {"name": "timeseries.ingestion.dataset.batchfailed.count", "datapoints": failed_points},
        ]
    }


MOCK_OBSERVABILITY_METRICS: dict[str, Any] = _mock_observability_response()


# --- Data Lifecycle Quotas -------------------------------------------------------

MOCK_QUOTAS: list[dict[str, Any]] = [
    {"name": "datasetExpirationQuota", "description": "Datasets with an active expiration policy", "consumed": 42, "quota": 500},
    {"name": "dailyConsumerDeleteIdentitiesQuota", "description": "Privacy delete-identity requests today", "consumed": 1840, "quota": 2000},
    {"name": "monthlyConsumerDeleteIdentitiesQuota", "description": "Privacy delete-identity requests this month", "consumed": 12_400, "quota": 50_000},
]


# --- Segmentation Service (Unified Profile) -------------------------------------

MOCK_SEGMENTS: list[dict[str, Any]] = [
    {"id": "seg-high-value", "name": "High-Value Loyalty Members", "description": "Loyalty tier gold/platinum, active in 30d", "schema": {"name": "Loyalty Events"}},
    {"id": "seg-cart-abandon", "name": "Cart Abandoners — 7d", "description": "Added to cart, no purchase within 7 days", "schema": {"name": "Web SDK Events"}},
]

# Shaped exactly like Adobe's own published example response (confirmed
# live — see clients/segmentation.py's parse_segment_job() docstring):
# "segments" is a list of {segmentId}, not a top-level "segmentId" string,
# timestamps are epoch-millisecond "creationTime"/"updateTime" not ISO
# "startTime"/"endTime", and the profile-count field is
# "segmentedProfileCounter" (with the "er"), not "segmentedProfileCount".
# The original mock data guessed all four wrong — exactly the class of gap
# that let a live-only bug (the "sort" param, a completely separate issue)
# ship without mock mode ever exercising the real shape.
MOCK_SEGMENT_JOBS: list[dict[str, Any]] = [
    {
        "id": "job-1", "segments": [{"segmentId": "seg-high-value"}], "status": "SUCCEEDED",
        "metrics": {"segmentedProfileCounter": 184_302},
        "creationTime": _millis_ago(120), "updateTime": _millis_ago(95),
    },
    {
        "id": "job-2", "segments": [{"segmentId": "seg-cart-abandon"}], "status": "FAILED",
        "metrics": {},
        "creationTime": _millis_ago(60), "updateTime": _millis_ago(55),
    },
]


# --- Query Service ---------------------------------------------------------------

MOCK_QUERIES: list[dict[str, Any]] = [
    # Shaped exactly like Adobe's own published example response (see
    # clients/query_service.py's parse_query() docstring) — note there's no
    # top-level "sql" or "name" field, and "id-2"'s error lives in an
    # "errors" array, not an "errorMsg" string; the original mock data
    # guessed all three wrong, which is exactly why it never caught the
    # live bug this shape now pins down.
    {
        "id": "q-1", "state": "SUCCESS",
        "request": {
            "dbName": "prod:all",
            "sql": "SELECT tier, COUNT(DISTINCT loyaltyId) AS members, SUM(pointsBalance) AS total_points\n"
                   "FROM loyalty_events\nWHERE _acmecorp.eventDate >= current_date - INTERVAL '1' DAY\nGROUP BY tier;",
        },
        "client": "Adobe Query Service Scheduler", "errors": [], "rowCount": 402_118, "elapsedTime": 14_200,
        "created": _iso(30), "updated": _iso(29), "userId": "acp-scheduler", "scheduleId": "sch-1",
        "_links": {"referenced_datasets": [{"id": "ds-loyalty-events", "href": "https://platform.adobe.io/data/foundation/catalog/dataSets/ds-loyalty-events"}]},
    },
    {
        "id": "q-2", "state": "FAILED",
        "request": {"dbName": "prod:all", "sql": "SELECT * FROM web_events w JOIN loyalty_events l ON w._acmecorp.loyaltyId = l._acmecorp.loyaltyId;"},
        "client": "Adobe Query Service UI", "errors": [{"code": "0A500", "message": "Query exceeded configured timeout"}],
        # An opaque id, not an email — matches one of MOCK_USERS below so
        # the "Run by" resolution has something real to demonstrate.
        # "q-1"'s "acp-scheduler" deliberately has no match anywhere: a
        # technical/service account very plausibly has no User Management
        # API directory entry at all (see clients/user_management.py's
        # module docstring) — an unresolved id there is the *expected*
        # outcome, not a bug, and mock mode should show that honestly too.
        "rowCount": None, "elapsedTime": 601_000, "created": _iso(180), "updated": _iso(170), "userId": "u-jordan-lee",
    },
]

MOCK_SCHEDULES: list[dict[str, Any]] = [
    {"id": "sch-1", "state": "ENABLED", "query": {"name": "Daily loyalty rollup"}},
]

# --- User Management API (org directory, for Query Service's "Run by") ---------
# Shaped like Adobe's own published example response (confirmed live — see
# clients/user_management.py's module docstring): "id" is the org-scoped
# user id, "firstname"/"lastname" build the display name, matching
# parse_user()'s own preference order.
MOCK_USERS: list[dict[str, Any]] = [
    {"id": "u-jordan-lee", "email": "jordan.lee@acme.com", "username": "jordan.lee", "firstname": "Jordan", "lastname": "Lee", "type": "federatedID"},
    {"id": "u-priya-shah", "email": "priya.shah@acme.com", "username": "priya.shah", "firstname": "Priya", "lastname": "Shah", "type": "federatedID"},
]


# --- Compare page: Sandboxes tab (mock variation) -------------------------------
# Real per-sandbox data naturally differs; static mock data doesn't, so the
# Sandboxes tab would otherwise show identical numbers for every sandbox in
# mock mode. A small deterministic (seeded by name, not random) variation
# makes the comparison demonstrable without touching MOCK_FLOWS/MOCK_RUNS
# used elsewhere.

def mock_aep_summary_for_sandbox(sandbox: str) -> dict[str, Any]:
    seed = sum(ord(c) for c in sandbox)
    flow_count = len(MOCK_FLOWS)
    failing_count = 1 if "prod" not in sandbox.lower() else 0
    # "prod" stays clean; anything else gets a small, name-seeded amount of
    # trouble, so a non-prod sandbox visibly looks worse in the comparison.
    records_failed = 244 if failing_count else (seed % 50)
    return {"sandbox": sandbox, "flow_count": flow_count, "failing_count": failing_count, "records_failed": records_failed}


def mock_observability_summary_for_sandbox(sandbox: str) -> dict[str, Any]:
    seed = sum(ord(c) for c in sandbox)
    base = _mock_observability_response(days=1)
    success = base["metricResponses"][0]["datapoints"][-1]["value"] + seed * 50
    failed = 40 if "prod" in sandbox.lower() else 400 + (seed % 500)
    return {"sandbox": sandbox, "recordsuccess": success, "batchfailed": failed}


# --- Audit ---------------------------------------------------------------------

# Raw event objects (as they appear inside the real API's `_embedded.events`
# array — see clients/audit.py's docstring for why this matters: the
# original version of this mock data was shaped like the *parsed* row
# instead of the raw API response, which meant it validated the parser
# against its own wrong guess instead of reality, and a real envelope
# mismatch shipped undetected until reported live.
MOCK_AUDIT_EVENTS: list[dict[str, Any]] = [
    {"id": "ae1", "action": "schema.updated", "userEmail": "jordan.lee@acme.com", "timestamp": _iso(15), "assetName": "XDM Individual Profile", "assetType": "schema"},
    {"id": "ae2", "action": "dataset.created", "userEmail": "sam.ortiz@acme.com", "timestamp": _iso(120), "assetName": "Loyalty Events", "assetType": "dataset"},
    {"id": "ae3", "action": "policy.updated", "userEmail": "jordan.lee@acme.com", "timestamp": _iso(600), "assetName": "Data Usage Labeling", "assetType": "policy"},
]
