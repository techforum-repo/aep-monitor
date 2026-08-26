from __future__ import annotations

"""AEP Query Service client — ad-hoc and scheduled SQL queries against the
data lake.

Docs: https://experienceleague.adobe.com/en/docs/experience-platform/query/api/queries
      https://experienceleague.adobe.com/en/docs/experience-platform/query/api/schedules
Confirmed base URL: https://platform.adobe.io/data/foundation/query

Added to close a real coverage gap: Query Service is a major, cost-bearing
AEP capability with its own failure modes (a failed scheduled query, a
runaway ad-hoc query) that had zero visibility anywhere in this app.

Same "newest, least-verified" caveat as clients/segmentation.py (see that
module's docstring and README's Known Limitations) — the list-response
envelope and several field names below are best-effort from Adobe's
published docs/examples, not confirmed against a live tenant. Defensive
parsing throughout, raw response kept alongside every parsed row.
"""

from typing import Any

import httpx

from ..config import settings
from .base import BaseAdobeClient

_BAD_QUERY_STATES = {"failed", "error", "cancelled", "canceled"}


class QueryServiceClient(BaseAdobeClient):
    base_url = settings.aep_query_service_base_url

    def _extra_headers(self) -> dict[str, str]:
        return {"x-sandbox-name": settings.adobe_sandbox}

    @staticmethod
    def _sandbox_override(sandbox: str | None) -> dict[str, str] | None:
        return {"x-sandbox-name": sandbox} if sandbox else None

    async def list_queries(self, http: httpx.AsyncClient, limit: int = 50, sandbox: str | None = None) -> list[dict[str, Any]]:
        data = await self.get(http, "/queries", params={"limit": limit, "orderby": "-created"}, extra_headers=self._sandbox_override(sandbox))
        items = (data.get("queries") or data.get("items") or data.get("data") or []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_schedules(self, http: httpx.AsyncClient, sandbox: str | None = None) -> list[dict[str, Any]]:
        data = await self.get(http, "/schedules", extra_headers=self._sandbox_override(sandbox))
        items = (data.get("schedules") or data.get("items") or data.get("data") or []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.list_queries(http, limit=1)
        return True


def parse_query(item: dict[str, Any]) -> dict[str, Any]:
    state = str(item.get("state") or item.get("status") or "unknown").lower()
    return {
        "query_id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or "(ad hoc)"),
        "state": state,
        "is_bad": state in _BAD_QUERY_STATES,
        "row_count": item.get("rowCount"),
        "elapsed_ms": item.get("elapsedTime"),
        "error_message": str(item.get("errorMsg") or ""),
        "created_at": str(item.get("created") or ""),
        "is_scheduled": bool(item.get("scheduleId") or item.get("isScheduled")),
        "raw": item,
    }


def parse_schedule(item: dict[str, Any]) -> dict[str, Any]:
    query_ref = item.get("query")
    return {
        "schedule_id": str(item.get("id") or ""),
        "name": str((query_ref or {}).get("name") or item.get("id") or "(unnamed)") if isinstance(query_ref, dict) else str(item.get("id") or "(unnamed)"),
        "enabled": str(item.get("state") or "").lower() == "enabled",
        "raw": item,
    }
