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

import httpx

from ..config import settings
from ..utils import safe_dict
from .base import BaseAdobeClient


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
