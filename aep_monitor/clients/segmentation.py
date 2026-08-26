from __future__ import annotations

"""AEP Segmentation Service (Unified Profile) client — segment definitions
and segment evaluation jobs.

Docs: https://experienceleague.adobe.com/en/docs/experience-platform/segmentation/api/segment-definitions
      https://experienceleague.adobe.com/en/docs/experience-platform/segmentation/api/segment-jobs
Confirmed base URL (Adobe's Unified Profile API, shared by Segmentation and
Profile access): https://platform.adobe.io/data/core/ups

Added to close a real coverage gap, not a peripheral one: this app already
watched ingestion (AEP Flow Service) and consumption (CJA connections/data
views/projects), but nothing watched the layer in between that actually
*produces* what an activation flow exports to a destination (see aep.py's
parse_flow() docstring on why a flow's direction isn't otherwise visible) —
a failed or stalled segment job upstream is very often the real cause of
"the audience never showed up," not the destination flow itself.

This is, alongside clients/query_service.py, the newest and least-verified
integration in this app — same caveat class as Audit Query/Observability
Insights (see README Known Limitations): the list-response envelope key and
several field names below (`segments` vs `items` vs `data`; `metrics.
segmentedProfileCount`; job status vocabulary) are best-effort from Adobe's
published docs/examples, not confirmed against a live tenant. Every parse
here is defensive and the raw response is kept alongside the parsed row for
exactly this reason — check the Segments page's raw-response expander
against what parse_segment()/parse_segment_job() assume before trusting
this page's numbers on a new tenant.
"""

from typing import Any

import httpx

from ..config import settings
from .base import BaseAdobeClient

_BAD_JOB_STATUSES = {"failed", "error"}


class SegmentationClient(BaseAdobeClient):
    base_url = settings.aep_segmentation_base_url

    def _extra_headers(self) -> dict[str, str]:
        # Sent defensively, same reasoning as quota.py/audit.py: Profile/
        # Segmentation is plausibly sandbox-scoped the same way datasets and
        # schemas are, and an unneeded header costs nothing while a missing
        # required one has been a hard 400 elsewhere in this app's history.
        return {"x-sandbox-name": settings.adobe_sandbox}

    @staticmethod
    def _sandbox_override(sandbox: str | None) -> dict[str, str] | None:
        return {"x-sandbox-name": sandbox} if sandbox else None

    async def list_segments(self, http: httpx.AsyncClient, limit: int = 100, sandbox: str | None = None) -> list[dict[str, Any]]:
        data = await self.get(http, "/segment/definitions", params={"limit": limit}, extra_headers=self._sandbox_override(sandbox))
        items = (data.get("segments") or data.get("items") or data.get("data") or []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def list_segment_jobs(self, http: httpx.AsyncClient, limit: int = 50, sandbox: str | None = None) -> list[dict[str, Any]]:
        data = await self.get(
            http, "/segment/jobs", params={"limit": limit, "sort": "desc:createdAt"}, extra_headers=self._sandbox_override(sandbox)
        )
        items = (data.get("records") or data.get("items") or data.get("data") or []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.list_segments(http, limit=1)
        return True


def parse_segment(item: dict[str, Any]) -> dict[str, Any]:
    schema_ref = item.get("schema")
    return {
        "segment_id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or "(unnamed)"),
        "description": str(item.get("description") or ""),
        "schema_ref": str((schema_ref or {}).get("name") or "") if isinstance(schema_ref, dict) else "",
        "raw": item,
    }


def parse_segment_job(item: dict[str, Any]) -> dict[str, Any]:
    status = str(item.get("status") or "unknown").lower()
    metrics = item.get("metrics")
    return {
        "job_id": str(item.get("id") or ""),
        "segment_id": str(item.get("segmentId") or item.get("definitionId") or ""),
        "status": status,
        "is_bad": status in _BAD_JOB_STATUSES,
        "segmented_profile_count": metrics.get("segmentedProfileCount") if isinstance(metrics, dict) else None,
        "started_at": str(item.get("startTime") or item.get("createdAt") or ""),
        "ended_at": str(item.get("endTime") or item.get("updatedAt") or ""),
        "raw": item,
    }
