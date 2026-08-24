from __future__ import annotations

"""Observability Insights API client — Adobe's own org/sandbox-wide health
and historical-metrics API for AEP, as distinct from this app's own
per-flow polling (aep.py) and locally-accumulated history (database.py).

Docs: https://experienceleague.adobe.com/en/docs/experience-platform/observability/api/metrics
Confirmed against Adobe's published Postman collection (adobe/experience-platform-postman-samples):
POST /metrics is the only documented endpoint — there is no separate
"health check" endpoint despite Adobe's marketing copy describing
"health-checks" as a capability. What the AEP UI shows as health-check
categories (Ingestion, Schemas and Identities, Datasets, ...) appears to be
curated metric IDs surfaced in the UI, not a distinct API — so this client
only wraps the one real endpoint.

Only two metric IDs are confirmed from Adobe's own example request; every
other metric ID Adobe's UI groups under "health checks" (Query Service,
Merge Policies, Segmentation, ...) was not independently verified here.
Add more to DEFAULT_HEALTH_METRICS once you've found their exact IDs (check
your tenant's Observability UI, or Adobe's evolving metric catalog) rather
than guessing at names.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import settings
from .base import BaseAdobeClient

DEFAULT_HEALTH_METRICS = [
    "timeseries.ingestion.dataset.recordsuccess.count",
    "timeseries.ingestion.dataset.batchfailed.count",
]


class ObservabilityClient(BaseAdobeClient):
    base_url = settings.aep_observability_base_url

    def _extra_headers(self) -> dict[str, str]:
        headers = {"x-sandbox-name": settings.adobe_sandbox}
        if settings.adobe_sandbox_id:
            headers["x-sandbox-id"] = settings.adobe_sandbox_id
        return headers

    async def get_metrics(
        self, http: httpx.AsyncClient, metric_names: list[str], days: int = 7, granularity: str = "day",
        sandbox: str | None = None,
    ) -> dict[str, Any]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        body = {
            "start": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "granularity": granularity,
            "metrics": [{"name": name, "aggregator": "sum"} for name in metric_names],
        }
        # x-sandbox-name is overridden per call (see aep.py's same pattern).
        # x-sandbox-id must be *removed*, not left as-is, when overriding:
        # there's no per-sandbox ID configured here, so ADOBE_SANDBOX_ID (if
        # set at all) is only valid for the configured default sandbox —
        # sending it alongside a different x-sandbox-name would pair a
        # mismatched name/id and could silently misattribute the request to
        # the wrong sandbox.
        extra: dict[str, str | None] | None = {"x-sandbox-name": sandbox, "x-sandbox-id": None} if sandbox else None
        return await self._request(http, "POST", f"{self.base_url}/metrics", json=body, extra_headers=extra)

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.get_metrics(http, DEFAULT_HEALTH_METRICS[:1], days=1)
        return True


def parse_metrics_response(data: Any) -> dict[str, list[dict[str, Any]]]:
    """Keyed by metric name -> list of {timestamp, value} points, sorted
    ascending by timestamp. Response envelope field names beyond
    `metricResponses`/`datapoints` were not independently verified —
    parsing is defensive at every level (not just the top level: every
    `isinstance` check below exists because a live response was found, in
    practice, to not match the assumed shape at that specific point — e.g.
    `entry["metric"]` turned out to be the metric name itself, a plain
    string, rather than a nested `{"name": ...}` object), and the raw
    response is always available in the UI's expander for a shape mismatch
    to be visible instead of silently wrong. The sort itself is defensive
    too: Adobe's example response wasn't confirmed to guarantee
    chronological order, and both the AEP page's trend chart and Compare
    Sandboxes' `points[-1]` "latest value" lookup depend on it being
    sorted — a missing/unparsable timestamp sorts first (empty string)
    rather than raising, so one bad point doesn't break the whole series."""
    result: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(data, dict):
        return result
    responses = data.get("metricResponses") or data.get("metrics") or []
    if not isinstance(responses, list):
        return result
    for entry in responses:
        if not isinstance(entry, dict):
            continue
        metric_field = entry.get("metric")
        if isinstance(metric_field, dict):
            nested_name = metric_field.get("name")
        elif isinstance(metric_field, str):
            nested_name = metric_field
        else:
            nested_name = None
        name = str(entry.get("name") or nested_name or "unknown")
        datapoints = entry.get("datapoints") or entry.get("dataPoints") or []
        if not isinstance(datapoints, list):
            datapoints = []
        points = [
            {"timestamp": dp.get("timestamp") or dp.get("time"), "value": dp.get("value")}
            for dp in datapoints if isinstance(dp, dict)
        ]
        points.sort(key=lambda p: p["timestamp"] or "")
        result[name] = points
    return result
