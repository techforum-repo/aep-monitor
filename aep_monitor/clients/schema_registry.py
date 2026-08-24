from __future__ import annotations

"""AEP Schema Registry client — the AEP half of the SDR ("Solution Design
Reference") page, see ui/sdr_page.py: a live, browsable/exportable list of
what's actually defined in your tenant's XDM schemas, generated from the
real schema registry rather than a hand-maintained document that drifts
out of date.

Docs: https://experienceleague.adobe.com/en/docs/experience-platform/xdm/api/schemas
Confirmed base URL: https://platform.adobe.io/data/foundation/schemaregistry

Only tenant-defined schemas are listed (`/tenant/schemas`), not Adobe's
built-in global/industry schemas (`/global/schemas`) — the tenant ones are
what an org actually customized and is the part worth documenting.
"""

from typing import Any
from urllib.parse import quote

import httpx

from ..config import settings
from .base import BaseAdobeClient

# Resolves $ref/allOf so the returned schema's "properties" tree is already
# flattened-into-one-object (no unresolved references to chase) — the
# tradeoff parse_schema.flatten_fields() below is written against.
_FULL_SCHEMA_ACCEPT = "application/vnd.adobe.xed-full+json; version=1"
# Lighter weight for the summary list — id/title only, no full field tree.
_SUMMARY_ACCEPT = "application/vnd.adobe.xed-id+json"
# Requests expanded descriptor objects (not just links to fetch one by
# one) from GET /tenant/descriptors — see list_label_descriptors()'s
# docstring for how confirmed this shape actually is.
_DESCRIPTOR_LIST_ACCEPT = "application/vnd.adobe.xdm+json"


class SchemaRegistryClient(BaseAdobeClient):
    base_url = settings.aep_schema_registry_base_url

    def _extra_headers(self) -> dict[str, str]:
        return {"x-sandbox-name": settings.adobe_sandbox}

    async def list_schemas(self, http: httpx.AsyncClient, limit: int = 300, sandbox: str | None = None) -> list[dict[str, Any]]:
        extra: dict[str, str | None] = {"Accept": _SUMMARY_ACCEPT}
        if sandbox:
            extra["x-sandbox-name"] = sandbox
        data = await self.get(http, "/tenant/schemas", params={"limit": limit}, extra_headers=extra)
        # The exact envelope key wasn't pinned down from docs alone
        # (Adobe's registry endpoints have used "results" in some places,
        # "resources" in others) — try both before giving up.
        items = (data.get("results") or data.get("resources") or data.get("data") or []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def get_schema(self, http: httpx.AsyncClient, schema_id: str, sandbox: str | None = None) -> dict[str, Any]:
        # $id/meta:altId values are full URLs — Schema Registry expects
        # them URL-encoded in the path per Adobe's documented convention.
        path = f"/tenant/schemas/{quote(schema_id, safe='')}"
        extra: dict[str, str | None] = {"Accept": _FULL_SCHEMA_ACCEPT}
        if sandbox:
            extra["x-sandbox-name"] = sandbox
        data = await self.get(http, path, extra_headers=extra)
        return data if isinstance(data, dict) else {}

    async def list_label_descriptors(self, http: httpx.AsyncClient, sandbox: str | None = None) -> list[dict[str, Any]]:
        # Confirmed live (not documented anywhere found — the docs' own
        # `property`/`orderby`/`limit`/`start` list undersells what
        # `property` does): `property` is a repeatable RQL-style filter,
        # `property=<field>==<value>`, ANDed across repeats — e.g. Adobe's
        # own UI issues `?property=xdm:sourceSchema==...&property=@type==
        # xdm:descriptorLabel` under the hood. This uses only the `@type`
        # half — NOT `xdm:sourceSchema` — because that field turns out to
        # be a *field group* id (e.g. ".../mixins/xxxx"), not the composite
        # schema's own $id (also confirmed live), so filtering by it here
        # would require first resolving which field groups compose a given
        # schema — information the "full resolved" schema response doesn't
        # expose (no `allOf` present, confirmed live). data.py's
        # fetch_schema_field_labels() instead matches by field *path*
        # against the schema's own already-flattened field list, which
        # sidesteps that resolution problem entirely. `limit: 300` is
        # confirmed live as this endpoint's actual max — Adobe returned a
        # real HTTP 400 "Query limit out of range... valid query limit is
        # 0 - 300" for the 500 this app originally sent (borrowed from the
        # general schema registry docs' max page size elsewhere, which
        # turned out not to apply to this endpoint specifically). Pagination
        # beyond 300 isn't implemented (its mechanics — an "xdm-v2+json"
        # Accept variant — aren't confirmed), so a sandbox with 300+ label
        # descriptors specifically could miss some — see README Known
        # Limitations.
        extra: dict[str, str | None] = {"Accept": _DESCRIPTOR_LIST_ACCEPT}
        if sandbox:
            extra["x-sandbox-name"] = sandbox
        data = await self.get(http, "/tenant/descriptors", params={"limit": 300, "property": "@type==xdm:descriptorLabel"}, extra_headers=extra)
        return extract_label_descriptors(data)

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.list_schemas(http, limit=1)
        return True


def extract_label_descriptors(data: Any) -> list[dict[str, Any]]:
    """Pulls the xdm:descriptorLabel entries out of a /tenant/descriptors
    response. A standalone function (not inlined into
    list_label_descriptors() above) so data.py's mock-mode branch can run
    mock.MOCK_DESCRIPTORS through this exact same extraction instead of a
    separately-shaped mock, matching this app's rule that mock data flows
    through the same parsing as a live response.

    Confirmed live (Adobe's own docs never showed a worked example of this
    "expanded objects" list format, only the link-only list and the
    single-descriptor-by-id shapes): grouped by `@type`, same as the
    link-only format, but with full descriptor objects instead of link
    strings — `{"xdm:descriptorLabel": [{...}, {...}], ...}`. The
    flat-array branch below is kept only as a defensive fallback, not
    because it's expected."""
    if isinstance(data, dict):
        grouped = data.get("xdm:descriptorLabel")
        if isinstance(grouped, list):
            return [item for item in grouped if isinstance(item, dict)]
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and item.get("@type") == "xdm:descriptorLabel"]
    return []


def parse_label_descriptor(item: dict[str, Any]) -> dict[str, Any]:
    source_property = str(item.get("xdm:sourceProperty") or "")
    labels = item.get("xdm:labels")
    return {
        # Confirmed live: this is a *field group* $id (e.g. ".../mixins/xxxx"),
        # not the composite schema's own $id — kept here for the raw-data
        # trail, but data.py's fetch_schema_field_labels() deliberately
        # doesn't match on it (see list_label_descriptors()'s docstring for
        # why: no way to resolve which field groups compose a given schema).
        "source_schema": str(item.get("xdm:sourceSchema") or ""),
        "source_property": source_property,
        # Descriptor field paths are JSON pointers ("/_bsci/quiz/answerText"
        # — confirmed live), while flatten_fields() below produces dotted
        # paths ("_bsci.quiz.answerText") for the schema fields table —
        # normalized here so the two can be matched directly. Not confirmed
        # for a field nested inside an array (flatten_fields() marks those
        # "arrayField[]...", and JSON Pointer's own convention for indexing
        # into an array wasn't in any live example seen) — such a field's
        # label may not match; see README Known Limitations.
        "path": source_property.strip("/").replace("/", "."),
        "labels": [str(label) for label in labels] if isinstance(labels, list) else [],
        "raw": item,
    }


def parse_schema_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_id": str(item.get("$id") or item.get("meta:altId") or ""),
        "title": str(item.get("title") or "(untitled)"),
        "raw": item,
    }


def flatten_fields(schema: dict[str, Any], *, max_depth: int = 8) -> list[dict[str, Any]]:
    """Walk a resolved XDM schema's `properties` tree into a flat list of
    {path, type, title, description} rows — one per leaf field, dotted path
    for nesting (e.g. `_acmecorp.loyalty.pointsBalance`). Depth-capped
    rather than fully recursive without bound: XDM schemas can nest deeply
    and a malformed/cyclical-looking structure (unexpected given resolved
    $refs, but never verified against a live tenant) shouldn't be able to
    hang the page."""
    rows: list[dict[str, Any]] = []
    if not isinstance(schema, dict):
        return rows

    def _walk(properties: Any, prefix: str, depth: int) -> None:
        if not isinstance(properties, dict) or depth > max_depth:
            return
        for field_name, field_def in properties.items():
            if not isinstance(field_def, dict):
                continue
            path = f"{prefix}.{field_name}" if prefix else str(field_name)
            field_type = field_def.get("type")
            nested_properties = field_def.get("properties")
            items_def = field_def.get("items") if field_type == "array" else None
            items_properties = items_def.get("properties") if isinstance(items_def, dict) else None

            if isinstance(nested_properties, dict):
                _walk(nested_properties, path, depth + 1)
            elif isinstance(items_properties, dict):
                _walk(items_properties, f"{path}[]", depth + 1)
            else:
                rows.append({
                    "path": path,
                    "type": str(field_type or (items_def.get("type") if isinstance(items_def, dict) else "") or ""),
                    "title": str(field_def.get("title") or ""),
                    "description": str(field_def.get("description") or ""),
                })

    _walk(schema.get("properties"), "", 0)
    rows.sort(key=lambda r: r["path"])
    return rows
