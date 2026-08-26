from __future__ import annotations

"""AEP Query Service client — ad-hoc and scheduled SQL queries against the
data lake.

Docs: https://experienceleague.adobe.com/en/docs/experience-platform/query/api/queries
      https://experienceleague.adobe.com/en/docs/experience-platform/query/api/schedules
Confirmed base URL: https://platform.adobe.io/data/foundation/query

Added to close a real coverage gap: Query Service is a major, cost-bearing
AEP capability with its own failure modes (a failed scheduled query, a
runaway ad-hoc query) that had zero visibility anywhere in this app.

The Queries API's shape is now confirmed against Adobe's own published
example response (not just guessed) — see parse_query()'s docstring for
what changed as a result. The Schedules API (list_schedules()/
parse_schedule() below) is NOT independently confirmed the same way —
same "newest, least-verified" caveat as clients/segmentation.py, still
flagged in README's Known Limitations.
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
        # Confirmed live via Adobe's own docs example: the list envelope is
        # HAL-style — `{"queries": [...], "_page": {...}, "_links": {...}}`
        # — with `_page.orderby` confirming `orderby` is a real, honored
        # param; pagination itself is a `start` cursor (a timestamp, from
        # `_page.next`), not an offset, but that's not implemented here —
        # this app only asks for the most recent `limit` queries, same
        # single-page-only scope as most other list calls in this app.
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


def _stringify_query_error(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("message") or entry.get("code") or entry)
    return str(entry)


def parse_query(item: dict[str, Any]) -> dict[str, Any]:
    """Confirmed live via Adobe's own published example response (not a
    guess) — and it corrected three real mistakes in the original,
    docs-unverified version of this parser:

    1. `sql` is NOT top-level — it's nested under `request.sql` (alongside
       `request.dbName`, the database context the query ran against). The
       original `item.get("sql")` always returned "" against a real
       tenant — this is almost certainly why the Query Service page's
       detail view showed "No SQL text returned for this query" live.
    2. The client/origin field is `client` (e.g. "Adobe Query Service UI",
       "API"), not `clientType` as originally guessed — kept as a fallback
       below in case a different tenant/version uses it.
    3. Error info is an `errors` *array*, not a single `errorMsg` string.
       Adobe's own example only shows an empty array (`"errors": []`), so
       the shape of a populated entry isn't confirmed — handled
       defensively for either a plain string or a `{message: ...}` object.

    Also confirmed: there is genuinely **no `name` field** on the raw query
    object — unlike segments/flows elsewhere in this app, a query is
    identified by `id` (and its `sql`) only, not a user-given name. The
    `name` fallback below is therefore the *normal* path here, not an edge
    case.

    Not confirmed by this same example (no scheduled-query response was
    shown to check against): the `is_scheduled` linkage below.
    """
    state = str(item.get("state") or item.get("status") or "unknown").lower()
    request = item.get("request")
    request = request if isinstance(request, dict) else {}
    errors = item.get("errors")
    error_message = "; ".join(_stringify_query_error(e) for e in errors) if isinstance(errors, list) and errors else str(item.get("errorMsg") or "")
    links = item.get("_links")
    referenced = (links or {}).get("referenced_datasets") if isinstance(links, dict) else None
    referenced_dataset_ids = [str(d["id"]) for d in referenced if isinstance(d, dict) and d.get("id")] if isinstance(referenced, list) else []
    return {
        "query_id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or "(ad hoc)"),
        "state": state,
        "is_bad": state in _BAD_QUERY_STATES,
        "sql": str(request.get("sql") or item.get("sql") or ""),
        "db_name": str(request.get("dbName") or ""),
        "client_type": str(item.get("client") or item.get("clientType") or ""),
        "row_count": item.get("rowCount"),
        "elapsed_ms": item.get("elapsedTime"),
        "error_message": error_message,
        "created_at": str(item.get("created") or ""),
        "updated_at": str(item.get("updated") or ""),
        "user_id": str(item.get("userId") or ""),
        "is_scheduled": bool(item.get("scheduleId") or item.get("isScheduled")),
        "referenced_dataset_ids": referenced_dataset_ids,
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
