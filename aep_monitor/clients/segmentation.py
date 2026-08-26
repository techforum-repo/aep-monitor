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

Segment Definitions (`list_segments()`/`parse_segment()`) and Segment Jobs
(`list_segment_jobs()`/`parse_segment_job()`) are now confirmed against
Adobe's own published example responses (not guessed) — see
parse_segment_job()'s docstring for what changed as a result, including a
real live bug: the original `sort` parameter's syntax was backwards
(`"desc:createdAt"` instead of the documented `"[attribute]:[asc|desc]"`,
e.g. `"creationTime:desc"`), which Adobe rejected outright with HTTP 400
"The expression used is invalid" — a hard failure, not a shape mismatch
that degrades gracefully like most of the guesses elsewhere in this app.
"""

from datetime import datetime, timezone
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
        # Confirmed live via Adobe's own docs example: `sort` is
        # "[attribute]:[asc|desc]" (e.g. "creationTime:desc") — the
        # original "desc:createdAt" had both the order and the attribute
        # name backwards, and Adobe validates this strictly enough to
        # reject it with a hard HTTP 400 "The expression used is invalid"
        # rather than silently ignoring a malformed sort. The envelope key
        # is "children" (HAL-style, with "_page"/"_links"), not
        # "records"/"items"/"data" as originally guessed — kept as
        # fallbacks below in case a different tenant/version varies.
        data = await self.get(
            http, "/segment/jobs", params={"limit": limit, "sort": "creationTime:desc"}, extra_headers=self._sandbox_override(sandbox)
        )
        items = (data.get("children") or data.get("records") or data.get("items") or data.get("data") or []) if isinstance(data, dict) else []
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


def _millis_to_iso(value: Any) -> str:
    """Segment job timestamps are epoch milliseconds (confirmed live), not
    ISO strings like every other timestamp in this app — converted here so
    the rest of this app (format_timestamp(), history tables) doesn't need
    a special case for this one client."""
    if not isinstance(value, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""


def parse_segment_job(item: dict[str, Any]) -> dict[str, Any]:
    """Confirmed live via Adobe's own published example response — and it
    corrected several guesses in the original version of this parser:

    1. A job's segment reference is `segments` — a **list** of
       `{segmentId: ...}` objects, not a single top-level `segmentId`/
       `definitionId` string. A job can apparently target more than one
       segment; this app shows/matches against the first one (the common
       case) rather than modeling a job as belonging to several segments
       throughout the rest of the app for a case that's likely rare.
    2. Timestamps are `creationTime`/`updateTime` in **epoch
       milliseconds**, not `startTime`/`endTime` ISO strings — converted
       via `_millis_to_iso()` above.
    3. The profile-count field is `metrics.segmentedProfileCounter`, not
       `metrics.segmentedProfileCount` (no missing "er" in the real one).

    Status vocabulary is also now confirmed: `NEW`, `PROCESSING`,
    `SUCCEEDED`, `FAILED` — only `FAILED`/`ERROR` count as bad; `NEW`/
    `PROCESSING` are in-progress, not failures.
    """
    status = str(item.get("status") or "unknown").lower()
    metrics = item.get("metrics")
    segments = item.get("segments")
    first_segment = segments[0] if isinstance(segments, list) and segments and isinstance(segments[0], dict) else {}
    return {
        "job_id": str(item.get("id") or ""),
        "segment_id": str(first_segment.get("segmentId") or item.get("segmentId") or item.get("definitionId") or ""),
        "status": status,
        "is_bad": status in _BAD_JOB_STATUSES,
        "segmented_profile_count": metrics.get("segmentedProfileCounter") if isinstance(metrics, dict) else None,
        "started_at": _millis_to_iso(item.get("creationTime")) or str(item.get("startTime") or ""),
        "ended_at": _millis_to_iso(item.get("updateTime")) or str(item.get("endTime") or ""),
        "raw": item,
    }
