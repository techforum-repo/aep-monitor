from __future__ import annotations

"""AEP Flow Service client — dataflow (ingestion) monitoring.

Docs: https://experienceleague.adobe.com/en/docs/experience-platform/dataflows/api/monitor

Adobe's documented monitoring call filters runs by a specific flowId
(`GET /runs?property=flowId=={id}`) — there is no documented "all runs
org-wide" endpoint, so `recent_runs_for_flows()` fans out one call per flow
(capped) rather than guessing at an undocumented one. Response field names
(`recordSummary`, `statusSummary`, ...) come from Adobe's docs but have been
observed to vary slightly by source type — every parse here is defensive
(`.get()` with a default) and the raw JSON is always kept alongside the
parsed row so a shape mismatch is visible in the UI instead of crashing it.
"""

from typing import Any

import httpx

from ..config import settings
from ..utils import safe_dict
from .base import BaseAdobeClient


class AEPClient(BaseAdobeClient):
    base_url = settings.aep_flowservice_base_url

    def _extra_headers(self) -> dict[str, str]:
        return {"x-sandbox-name": settings.adobe_sandbox}

    @staticmethod
    def _sandbox_override(sandbox: str | None) -> dict[str, str] | None:
        """A per-call x-sandbox-name, used by ui/compare_page.py to poll
        multiple sandboxes through one client instance without touching the
        configured default (settings.adobe_sandbox stays what every other
        page uses)."""
        return {"x-sandbox-name": sandbox} if sandbox else None

    async def list_flows(self, http: httpx.AsyncClient, limit: int = 100, sandbox: str | None = None) -> list[dict[str, Any]]:
        data = await self.get(http, "/flows", params={"limit": limit}, extra_headers=self._sandbox_override(sandbox))
        items = data.get("items", data.get("data", [])) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_runs(self, http: httpx.AsyncClient, flow_id: str, limit: int = 5, sandbox: str | None = None) -> list[dict[str, Any]]:
        data = await self.get(
            http, "/runs", params={"property": f"flowId=={flow_id}", "orderby": "-created", "limit": limit},
            extra_headers=self._sandbox_override(sandbox),
        )
        items = data.get("items", data.get("data", [])) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def recent_runs_for_flows(
        self, http: httpx.AsyncClient, flows: list[dict[str, Any]], runs_per_flow: int = 3, sandbox: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Runs per flow, keyed by flow id. Each flow is a separate documented
        call — a flow whose lookup fails doesn't abort the others."""
        result: dict[str, list[dict[str, Any]]] = {}
        for flow in flows:
            flow_id = str(flow.get("id") or "")
            if not flow_id:
                continue
            try:
                result[flow_id] = await self.list_runs(http, flow_id, limit=runs_per_flow, sandbox=sandbox)
            except Exception:
                result[flow_id] = []
        return result

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.list_flows(http, limit=1)
        return True


def parse_flow(flow: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow_id": str(flow.get("id") or ""),
        "flow_name": str(flow.get("name") or flow.get("id") or "(unnamed)"),
        "state": str(flow.get("state") or safe_dict(flow.get("flowSpec")).get("name") or ""),
        "created_at": str(flow.get("createdAt") or ""),
        "raw": flow,
    }


def parse_run(run: dict[str, Any]) -> dict[str, Any]:
    metrics = safe_dict(run.get("metrics"))
    record_summary = safe_dict(metrics.get("recordSummary")) or safe_dict(safe_dict(metrics.get("statistics")).get("recordSummary"))
    status_summary = safe_dict(metrics.get("statusSummary"))
    duration = safe_dict(metrics.get("durationSummary"))
    status = str(
        status_summary.get("status")
        or run.get("status")
        or safe_dict(run.get("state")).get("value", "")
        or "unknown"
    ).lower()
    return {
        "run_id": str(run.get("id") or ""),
        "flow_id": str(run.get("flowId") or ""),
        "status": status,
        "records_in": record_summary.get("inputCount") or safe_dict(record_summary.get("input")).get("recordCount"),
        "records_out": record_summary.get("outputCount") or safe_dict(record_summary.get("output")).get("recordCount"),
        "records_failed": record_summary.get("failedCount") or record_summary.get("errorCount") or 0,
        "started_at": duration.get("startedAtUTC") or run.get("createdAt") or "",
        "completed_at": duration.get("completedAtUTC") or run.get("updatedAt") or "",
        "raw": run,
    }
