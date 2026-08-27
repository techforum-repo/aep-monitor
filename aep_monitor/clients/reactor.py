from __future__ import annotations

"""Reactor API client — Adobe Data Collection (Tags/Launch) monitoring.

Docs: https://experienceleague.adobe.com/en/docs/experience-platform/tags/api/overview

Reactor speaks JSON:API — every list response is `{"data": [{"id", "type",
"attributes": {...}}]}`. Parsing stays defensive throughout: attribute names
(`published`, `review_status`, `state`) are Adobe's documented ones but this
has not been exercised against a live tenant in this session, so the raw
JSON:API object is always kept alongside each parsed row.

`list_audit_events()`/`parse_audit_event()` are the least stable part of
this client — Adobe's own docs for `/audit_events` say plainly "the
implementation... is in flux" as the feature evolves, so field names
(`attributed_to_email`, `type_of`, ...) are more likely to drift here
than anywhere else in this file.
"""

import json
from typing import Any

import httpx

from ..config import settings
from ..utils import safe_dict
from .base import BaseAdobeClient


class ReactorClient(BaseAdobeClient):
    base_url = settings.reactor_base_url

    def _extra_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.api+json;revision=1",
            "Content-Type": "application/vnd.api+json",
        }

    async def list_companies(self, http: httpx.AsyncClient) -> list[dict[str, Any]]:
        data = await self.get(http, "/companies")
        items = data.get("data", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_properties(self, http: httpx.AsyncClient, company_id: str) -> list[dict[str, Any]]:
        data = await self.get(http, f"/companies/{company_id}/properties")
        items = data.get("data", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_extensions(self, http: httpx.AsyncClient, property_id: str) -> list[dict[str, Any]]:
        data = await self.get(http, f"/properties/{property_id}/extensions")
        items = data.get("data", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_rules(self, http: httpx.AsyncClient, property_id: str) -> list[dict[str, Any]]:
        data = await self.get(http, f"/properties/{property_id}/rules")
        items = data.get("data", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_libraries(self, http: httpx.AsyncClient, property_id: str) -> list[dict[str, Any]]:
        data = await self.get(http, f"/properties/{property_id}/libraries")
        items = data.get("data", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_environments(self, http: httpx.AsyncClient, property_id: str) -> list[dict[str, Any]]:
        data = await self.get(http, f"/properties/{property_id}/environments")
        items = data.get("data", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_data_elements(self, http: httpx.AsyncClient, property_id: str) -> list[dict[str, Any]]:
        data = await self.get(http, f"/properties/{property_id}/data_elements")
        items = data.get("data", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_audit_events(self, http: httpx.AsyncClient, page_size: int = 50) -> list[dict[str, Any]]:
        # Adobe's own docs for this one say "the implementation of the
        # /audit_events endpoint is in flux" — treat this as the least
        # stable Reactor endpoint in this app, same caution as Audit Query.
        data = await self.get(http, "/audit_events", params={"page[size]": page_size})
        items = data.get("data", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.list_companies(http)
        return True


_BAD_LIBRARY_STATES = {"failed", "rejected"}
_GOOD_LIBRARY_STATES = {"published", "approved"}


def parse_property(item: dict[str, Any]) -> dict[str, Any]:
    attrs = safe_dict(item.get("attributes"))
    return {
        "property_id": str(item.get("id") or ""),
        "property_name": str(attrs.get("name") or item.get("id") or "(unnamed)"),
        "raw": item,
    }


def _extract_datastream_ids(attrs: dict[str, Any]) -> dict[str, str]:
    """{environment: datastream_id} for every environment override this
    Web SDK extension's settings actually carry — confirmed via Adobe's
    docs that Reactor's extensions *list* response (not just the
    single-item GET) already includes each extension's full `settings`
    attribute, so no extra per-extension call is needed to get it.

    `settings` is a JSON-*encoded string* per Adobe's own example response
    (`"settings": "{...}"`), not a nested object, sitting alongside many
    other unrelated configuration keys — parsed defensively here since a
    malformed value shouldn't crash the whole property fetch, and every
    other key is simply ignored.

    Reported live, not something Adobe's own docs describe in one place: a
    single property can configure a genuinely *different* datastream per
    build environment — `datastreamId`/`edgeConfigId` for production
    (`edgeConfigId` confirmed-deprecated in favor of `datastreamId`), plus
    separate flat keys for staging/development. Both the older
    `stagingEdgeConfigId`/`developmentEdgeConfigId` naming (confirmed live)
    and the newer `datastreamId`-style rename applied consistently
    (`stagingDatastreamId`/`developmentDatastreamId`) are checked, since
    which one a given tenant's extension version actually uses isn't
    confirmed either way — this app has not seen a live example
    confirming the newer names exist for staging/development specifically,
    only that the pattern of the rename holds for the production key.

    Detected by the presence of these setting keys themselves, not by
    matching the Web SDK extension's own package name/delegate_descriptor_id
    — Adobe's own docs don't show a live example of that exact string for
    this specific extension, so keying off a setting name it's uniquely
    known to carry is the more robust signal here, not a guess this app
    can't verify. Only environments with a non-empty value are included —
    an environment with no override configured is absent from the result,
    not an empty-string entry."""
    settings_raw = attrs.get("settings")
    if isinstance(settings_raw, str):
        try:
            settings_obj = json.loads(settings_raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    elif isinstance(settings_raw, dict):
        settings_obj = settings_raw
    else:
        return {}
    if not isinstance(settings_obj, dict):
        return {}

    result: dict[str, str] = {}
    production_id = settings_obj.get("datastreamId") or settings_obj.get("edgeConfigId")
    if production_id:
        result["production"] = str(production_id)
    staging_id = settings_obj.get("stagingDatastreamId") or settings_obj.get("stagingEdgeConfigId")
    if staging_id:
        result["staging"] = str(staging_id)
    development_id = settings_obj.get("developmentDatastreamId") or settings_obj.get("developmentEdgeConfigId")
    if development_id:
        result["development"] = str(development_id)
    return result


def parse_extension(item: dict[str, Any]) -> dict[str, Any]:
    attrs = safe_dict(item.get("attributes"))
    review_status = str(attrs.get("review_status") or attrs.get("reviewStatus") or "").lower()
    return {
        "extension_id": str(item.get("id") or ""),
        "name": str(attrs.get("name") or attrs.get("display_name") or item.get("id") or "(unnamed)"),
        "published": bool(attrs.get("published")),
        "review_status": review_status,
        "has_issue": review_status in {"rejected", "failed"},
        "datastream_ids": _extract_datastream_ids(attrs),
        "raw": item,
    }


def parse_rule(item: dict[str, Any]) -> dict[str, Any]:
    attrs = safe_dict(item.get("attributes"))
    return {
        "rule_id": str(item.get("id") or ""),
        "name": str(attrs.get("name") or item.get("id") or "(unnamed)"),
        "enabled": bool(attrs.get("enabled", True)),
        "published": bool(attrs.get("published")),
        "raw": item,
    }


def parse_library(item: dict[str, Any]) -> dict[str, Any]:
    attrs = safe_dict(item.get("attributes"))
    state = str(attrs.get("state") or "").lower()
    return {
        "library_id": str(item.get("id") or ""),
        "name": str(attrs.get("name") or item.get("id") or "(unnamed)"),
        "state": state,
        "is_bad": state in _BAD_LIBRARY_STATES,
        "is_good": state in _GOOD_LIBRARY_STATES,
        "build_date": str(attrs.get("build_date") or attrs.get("buildDate") or ""),
        "raw": item,
    }


_BAD_ENVIRONMENT_STATUSES = {"failed"}
_GOOD_ENVIRONMENT_STATUSES = {"succeeded"}


def parse_environment(item: dict[str, Any]) -> dict[str, Any]:
    attrs = safe_dict(item.get("attributes"))
    stage = str(attrs.get("stage") or "").lower()
    status = str(attrs.get("status") or "").lower()
    return {
        "environment_id": str(item.get("id") or ""),
        "name": str(attrs.get("name") or item.get("id") or "(unnamed)"),
        # development / staging / production — confirmed exactly these
        # three via Adobe's docs; "production" specifically is what the
        # DC page and alerts.py's new condition key off of.
        "stage": stage,
        "status": status,
        "is_bad": status in _BAD_ENVIRONMENT_STATUSES,
        "is_good": status in _GOOD_ENVIRONMENT_STATUSES,
        "raw": item,
    }


def parse_data_element(item: dict[str, Any]) -> dict[str, Any]:
    attrs = safe_dict(item.get("attributes"))
    review_status = str(attrs.get("review_status") or "").lower()
    return {
        "data_element_id": str(item.get("id") or ""),
        "name": str(attrs.get("name") or item.get("id") or "(unnamed)"),
        "enabled": bool(attrs.get("enabled", True)),
        "published": bool(attrs.get("published")),
        "dirty": bool(attrs.get("dirty")),
        "review_status": review_status,
        # Same "issue" shape as parse_extension(): unpublished local
        # changes or a not-yet-submitted-for-review state, surfaced the
        # same way a rejected extension already is.
        "has_issue": bool(attrs.get("dirty")) or review_status == "rejected",
        "raw": item,
    }


def parse_audit_event(item: dict[str, Any]) -> dict[str, Any]:
    attrs = safe_dict(item.get("attributes"))
    return {
        "event_id": str(item.get("id") or ""),
        "action": str(attrs.get("type_of") or ""),
        "actor": str(attrs.get("attributed_to_email") or attrs.get("attributed_to_display_name") or ""),
        "timestamp": str(attrs.get("created_at") or ""),
        "target": str(attrs.get("display_name") or ""),
        "raw": item,
    }
