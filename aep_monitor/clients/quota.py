from __future__ import annotations

"""Data Lifecycle (Hygiene) Quota API client.

Docs: https://experienceleague.adobe.com/en/docs/experience-platform/data-lifecycle/api/quota

This is governance/lifecycle quota (dataset expiration, consumer-delete
identity quotas for privacy requests) — not a live "requests remaining
before a 429" quota. Adobe doesn't publish an API for the latter; its
documented rate limits (req/s per service) are static numbers, shown as
reference text on the Settings page, not something queryable here.

Sends x-sandbox-name defensively even though the docs consulted while
building this client didn't list it as required: the Audit Query client
had the identical gap (undocumented-but-actually-required sandbox header)
and it broke live with "Missing Sandbox Information" — and what this
client reports (dataset expiration, consumer-delete identities) is
plausibly sandbox-scoped the same way datasets themselves are. Sending an
unneeded header costs nothing; omitting a needed one is a hard 400.
"""

from typing import Any

import httpx

from ..config import settings
from .base import BaseAdobeClient


class QuotaClient(BaseAdobeClient):
    base_url = settings.aep_quota_base_url

    def _extra_headers(self) -> dict[str, str]:
        return {"x-sandbox-name": settings.adobe_sandbox}

    async def list_quotas(self, http: httpx.AsyncClient) -> list[dict[str, Any]]:
        data = await self.get(http, "/quota")
        items = data.get("quotas", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.list_quotas(http)
        return True


def parse_quota(item: dict[str, Any]) -> dict[str, Any]:
    consumed = float(item.get("consumed") or 0)
    quota = float(item.get("quota") or 0)
    pct_used = (consumed / quota * 100) if quota else 0.0
    return {
        "name": str(item.get("name") or ""),
        "description": str(item.get("description") or ""),
        "consumed": consumed,
        "quota": quota,
        "pct_used": round(pct_used, 1),
        "is_high": pct_used >= settings.alert_quota_threshold_pct,
        "raw": item,
    }
