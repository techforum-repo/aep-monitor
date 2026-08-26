from __future__ import annotations

"""Customer Journey Analytics API client — connection, data view, and
component (dimension/metric) monitoring, the CJA half of the SDR
("Solution Design Reference") page — see ui/sdr_page.py.

Docs: https://developer.adobe.com/cja-apis/docs/endpoints/

Uses the same shared credential as every other client (settings.adobe_*) —
CJA can be added to the same Developer Console project as AEP/Reactor.
Response shapes here are Adobe's documented fields, parsed defensively; the
raw object is always kept alongside each parsed row.
"""

from typing import Any
from urllib.parse import quote

import httpx

from ..config import settings
from ..utils import safe_dict
from .base import BaseAdobeClient

# Confirmed live: /projects' list response has no envelope with a
# lastPage/totalElements field to stop on (it's a bare JSON array, unlike
# every other CJA list endpoint) — pagination stops when a page comes back
# with fewer than `limit` items instead. Capped defensively in case a
# misbehaving response never does.
_PROJECTS_PAGE_SAFETY_CAP = 1000


class CJAClient(BaseAdobeClient):
    base_url = settings.cja_base_url

    async def list_connections(self, http: httpx.AsyncClient, limit: int = 100) -> list[dict[str, Any]]:
        # Confirmed via Adobe's docs: /connections returns bare {id,
        # idWithoutPrefix} without `name`, `owner`, `isDeleted`, `isDisabled`,
        # or `modified` unless each is explicitly requested via `expansion`
        # (a comma-delimited list) — omitting it was the live bug reported
        # as "displays id not name" (and silently meant the health-status
        # alert below could never fire, since it isn't a default field either).
        data = await self.get(http, "/connections", params={"limit": limit, "expansion": "name,description,owner,isDeleted,isDisabled,modified"})
        items = data.get("content", data.get("data", [])) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return items if isinstance(items, list) else []

    async def list_dataviews(self, http: httpx.AsyncClient, limit: int = 100) -> list[dict[str, Any]]:
        # Same "expansion required or these fields are absent" behavior as
        # /connections above, confirmed via Adobe's docs — `name`, `owner`,
        # and the FK back to the parent connection (`parentDataGroupId`,
        # *not* `connectionId`/`dataConnectionId` as originally guessed)
        # are all opt-in fields, not defaults.
        data = await self.get(http, "/dataviews", params={"limit": limit, "expansion": "name,description,owner,parentDataGroupId"})
        items = data.get("content", data.get("data", [])) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return items if isinstance(items, list) else []

    async def list_dimensions(self, http: httpx.AsyncClient, dataview_id: str, limit: int = 200) -> list[dict[str, Any]]:
        data = await self.get(http, f"/dataviews/{dataview_id}/dimensions", params={"limit": limit})
        items = data.get("content", data.get("data", [])) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return items if isinstance(items, list) else []

    async def list_metrics(self, http: httpx.AsyncClient, dataview_id: str, limit: int = 200) -> list[dict[str, Any]]:
        data = await self.get(http, f"/dataviews/{dataview_id}/metrics", params={"limit": limit})
        items = data.get("content", data.get("data", [])) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return items if isinstance(items, list) else []

    async def list_audit_logs(self, http: httpx.AsyncClient, page_size: int = 50) -> list[dict[str, Any]]:
        # A genuinely separate API namespace from every call above (not
        # under self.base_url's /data path) — confirmed via Adobe's own
        # endpoint docs — so this bypasses self.get()'s base_url prefixing
        # and calls _request() directly with the full URL.
        url = f"{settings.cja_auditlogs_base_url}/auditlogs"
        data = await self._request(http, "GET", url, params={"pageSize": page_size})
        items = data.get("content", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_calculated_metrics(self, http: httpx.AsyncClient) -> list[dict[str, Any]]:
        # A third genuinely separate CJA namespace, same reasoning as Audit
        # Logs above. Org-wide, not filtered by data view — Adobe's docs
        # don't confirm a data-view filter query parameter for this
        # endpoint, so this fetches everything and data.py filters
        # client-side by the confirmed `dataId` response field instead of
        # trusting an unconfirmed request parameter.
        url = settings.cja_calculatedmetrics_base_url
        data = await self._request(http, "GET", url)
        items = data.get("content", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_projects(self, http: httpx.AsyncClient, limit: int = 100) -> list[dict[str, Any]]:
        # A fourth genuinely separate CJA namespace, same reasoning as Audit
        # Logs/Calculated Metrics above. `expansion=definition` does *not*
        # populate `definition` on this list call (confirmed live — see
        # get_project() below for the one that does); this is just id/name/
        # dataId/owner/created, cheap enough to fetch for every project
        # before deciding which ones are worth a full definition fetch.
        result: list[dict[str, Any]] = []
        page = 0
        while True:
            data = await self._request(http, "GET", settings.cja_projects_base_url, params={"page": page, "limit": limit})
            items = data if isinstance(data, list) else []
            result.extend(items)
            if len(items) < limit or page >= _PROJECTS_PAGE_SAFETY_CAP:
                break
            page += 1
        return result

    async def get_project(self, http: httpx.AsyncClient, project_id: str) -> dict[str, Any]:
        # expansion=definition only returns the definition here, on the
        # single-project GET — not on list_projects() above, even though
        # Adobe's docs describe expansion as available on both (confirmed
        # live: requesting it on the list call came back with no
        # `definition` field at all).
        url = f"{settings.cja_projects_base_url}/{quote(project_id, safe='')}"
        data = await self._request(http, "GET", url, params={"expansion": "definition"})
        return data if isinstance(data, dict) else {}

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.list_connections(http, limit=1)
        return True


def parse_connection(item: dict[str, Any]) -> dict[str, Any]:
    # Adobe's connections API has no status enum at all (no "status" or
    # "serviceStatus" field exists — confirmed via docs; earlier code
    # guessed both and, combined with those fields never being requested
    # via `expansion` anyway, meant `status` was always "" and this alert
    # could never fire in live mode). The only documented health signals
    # are the isDeleted/isDisabled booleans, so status is derived from those.
    if item.get("isDeleted"):
        status = "deleted"
    elif item.get("isDisabled"):
        status = "disabled"
    else:
        status = "active"
    return {
        "connection_id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or "(unnamed)"),
        "status": status,
        "has_issue": bool(item.get("isDeleted") or item.get("isDisabled")),
        "updated_at": str(item.get("modified") or ""),
        "raw": item,
    }


def parse_dataview(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataview_id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or "(unnamed)"),
        # parentDataGroupId is the confirmed field (Adobe's docs — a
        # connection's real id is a "data group" id, prefixed "dg_").
        # connectionId/dataConnectionId were the original unconfirmed
        # guesses, kept as a defensive fallback only.
        "connection_id": str(item.get("parentDataGroupId") or item.get("connectionId") or item.get("dataConnectionId") or ""),
        "owner": str(safe_dict(item.get("owner")).get("name") or ""),
        "raw": item,
    }


def parse_dimension(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "component_id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or "(unnamed)"),
        "description": str(item.get("description") or ""),
        "type": str(item.get("type") or ""),
        "source_field": str(item.get("sourceFieldName") or item.get("sourceFieldId") or ""),
        "dataset_type": str(item.get("dataSetType") or ""),
        "approved": bool(item.get("approved")),
        "raw": item,
    }


def parse_metric(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "component_id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or "(unnamed)"),
        "description": str(item.get("description") or ""),
        "type": str(item.get("type") or ""),
        "source_field": str(item.get("sourceFieldName") or ""),
        "dataset_type": str(item.get("dataSetType") or ""),
        "approved": bool(item.get("approved")),
        "raw": item,
    }


def parse_calculated_metric(item: dict[str, Any]) -> dict[str, Any]:
    owner = safe_dict(item.get("owner"))
    return {
        "component_id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or "(unnamed)"),
        "description": str(item.get("description") or ""),
        "type": str(item.get("type") or ""),
        "polarity": str(item.get("polarity") or ""),
        # dataId is confirmed present on the response but Adobe's docs
        # don't explicitly state it's the data view's id — parse_dataview()
        # elsewhere resolves a dataview_id the same way connection_id is
        # resolved for CJA connections, and this field lines up with that
        # same id space in every example seen, but treat the association
        # as reasonably-confident rather than fully confirmed.
        "dataview_id": str(item.get("dataId") or ""),
        "owner": str(owner.get("ownerId") or owner.get("imsUserId") or ""),
        "raw": item,
    }


def parse_project(item: dict[str, Any]) -> dict[str, Any]:
    owner = safe_dict(item.get("owner"))
    return {
        "project_id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or "(unnamed)"),
        "dataview_id": str(item.get("dataId") or ""),
        "owner": str(owner.get("ownerId") or owner.get("imsUserId") or ""),
        "created_at": str(item.get("created") or ""),
        "raw": item,
    }


_ENTITY_WALK_MAX_DEPTH = 40


def extract_entity_references(definition: Any, *, max_depth: int = _ENTITY_WALK_MAX_DEPTH) -> list[dict[str, Any]]:
    """Recursively walks a CJA project's `definition` JSON (from
    get_project()'s expansion=definition) and collects every object Adobe
    tags with `__entity__: true` — confirmed live as the uniform marker
    Adobe puts on any referenced component (a date range and a data view/
    "ReportSuite" were seen; dimensions/metrics/calculated metrics/segments
    are expected to follow the same `{"id", "__entity__": true, "type",
    "__metaData__": {"name"}}` shape wherever they sit in the deeply nested
    panel/subpanel/reportlet tree, but no *populated* real project was
    available to confirm those specific `type` strings — only an empty
    test project's structural pattern was seen).

    Deliberately doesn't hardcode which `type` values count as a
    "component" (e.g. assume "Dimension" vs "Metric" spelling) — every
    entity found is returned regardless of its type, and the caller (see
    data.py's fetch_cja_component_usage()) decides what to do with each
    one. Depth-capped the same way schema_registry.flatten_fields() is,
    for a malformed/cyclical-looking structure."""
    found: list[dict[str, Any]] = []

    def _walk(node: Any, depth: int) -> None:
        if depth > max_depth:
            return
        if isinstance(node, dict):
            if node.get("__entity__") is True:
                meta = safe_dict(node.get("__metaData__"))
                found.append({
                    "id": str(node.get("id") or ""),
                    "type": str(node.get("type") or ""),
                    "name": str(meta.get("name") or node.get("id") or ""),
                })
            for value in node.values():
                _walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                _walk(item, depth + 1)

    _walk(definition, 0)
    return found


def parse_audit_log(item: dict[str, Any]) -> dict[str, Any]:
    user = safe_dict(item.get("user"))
    component = safe_dict(item.get("component"))
    return {
        "log_id": str(item.get("id") or ""),
        "action": str(item.get("action") or ""),
        "actor": str(user.get("email") or user.get("name") or user.get("id") or ""),
        "timestamp": str(item.get("dateCreated") or ""),
        "target": str(component.get("name") or component.get("idType") or component.get("id") or ""),
        "description": str(item.get("description") or ""),
        "raw": item,
    }
