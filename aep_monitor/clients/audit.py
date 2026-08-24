from __future__ import annotations

"""AEP Audit Query API client — who-changed-what across AEP.

Docs: https://experienceleague.adobe.com/en/docs/experience-platform/landing/governance-privacy-security/audit-logs/audit-api/events
Requires the "View User Activity Log" access-control permission (Data
Governance category) on the credential's product profile.

Sends x-sandbox-name — confirmed required live: without it Adobe returns
HTTP 400 `AUDIT-0003-400 "Missing Sandbox Information"`, a gap this
client originally shipped with (Adobe's own docs consulted while building
it didn't call the header out as required for this specific endpoint).

Response envelope — confirmed live/via docs, and also a second real bug
this client shipped with: events are nested under `_embedded.events`
(a HAL-style envelope), not a top-level `events`/`data`/`items` key as
originally guessed. That guess wasn't just wrong in the parser — the mock
data in clients/mock.py was *also* built to the same wrong guessed shape
instead of the real raw API shape, so the test suite validated the parser
against its own mistake and could never have caught this; both are fixed
together, and MOCK_AUDIT_EVENTS now mirrors the real `_embedded.events`
envelope specifically so that can't recur. With the old top-level-key
guess, a real API response parsed to an empty list silently — no
exception, nothing to catch via friendly_error(), the page just showed
"No audit events returned" as if there genuinely were none.

Event field names below (`assetName`, `userEmail`, ...) are Adobe's
confirmed real ones; parsing still falls back to the originally-guessed
names too, defensively, in case a differently-configured tenant or API
version varies.

HTTP method is a known unresolved ambiguity: Adobe's own docs page
labels this endpoint GET in one section and shows a POST curl example in
another, and says so itself ("appears to be inconsistent"). Left as GET
here since that's what was already in place and reported working
(no method-not-allowed error) once the envelope fix above is applied —
switch to POST only if you see a 404/405 against your tenant.
"""

from typing import Any

import httpx

from ..config import settings
from ..utils import safe_dict
from .base import BaseAdobeClient


class AuditClient(BaseAdobeClient):
    base_url = settings.aep_audit_base_url

    def _extra_headers(self) -> dict[str, str]:
        return {"x-sandbox-name": settings.adobe_sandbox}

    async def list_events(self, http: httpx.AsyncClient, limit: int = 50, sandbox: str | None = None) -> list[dict[str, Any]]:
        extra = {"x-sandbox-name": sandbox} if sandbox else None
        data = await self.get(http, "/events", params={"limit": limit}, extra_headers=extra)
        items = _extract_events(data)
        return items if isinstance(items, list) else []

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.list_events(http, limit=1)
        return True


def _extract_events(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    embedded = data.get("_embedded")
    if isinstance(embedded, dict) and isinstance(embedded.get("events"), list):
        return embedded["events"]
    # Fallbacks for the originally-guessed (unconfirmed) shapes, kept in
    # case a different tenant/API version doesn't use the HAL envelope.
    for key in ("events", "data", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def parse_event(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(item.get("id") or item.get("requestId") or item.get("eventId") or ""),
        "action": str(item.get("action") or item.get("actionType") or ""),
        "actor": str(item.get("userEmail") or item.get("authId") or item.get("actor") or safe_dict(item.get("user")).get("email", "") or ""),
        "timestamp": str(item.get("timestamp") or item.get("createdAt") or ""),
        "target": str(item.get("assetName") or item.get("assetType") or item.get("permissionResource") or item.get("target") or item.get("resourceName") or ""),
        "raw": item,
    }
