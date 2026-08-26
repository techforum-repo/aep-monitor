from __future__ import annotations

"""Adobe User Management API (UMAPI) — resolves an opaque Adobe user id to
a display name/email. Used only by Query Service's "Run by" column (see
data.py's fetch_user_display_names()): Query Service's own API has no
CJA-style `expansion` parameter to resolve this itself — confirmed via
Adobe's own docs, which document a complete parameter list for `GET
/queries` (`orderby`, `limit`, `start`, `property`, `excludeSoftDeleted`,
`excludeHidden`, `isPrevLink`) with no expansion/properties/fields option
anywhere, and `userId` as the only user-identifying field on a query
object at all.

Docs: https://adobe-apiplatform.github.io/umapi-documentation/en/api/getUsersWithPage.html
Confirmed base URL: https://usermanagement.adobe.io/v2/usermanagement
Confirmed endpoint: GET /users/{orgId}/{page} (zero-indexed page),
response `{"lastPage": bool, "result": "success", "users": [...]}`.

This is a genuinely separate Adobe API product from AEP/Data Collection/
CJA/Query Service — it must be added to the same Developer Console project
(see README "Going live") or every call here fails; that failure degrades
to "every userId stays unresolved" (see data.py) rather than breaking the
Query Service page itself.

**Not confirmed**: whether a user's `id` field here is actually the same
identifier Query Service's own `userId` returns — Adobe's Queries API docs
don't document that field's format at all (see README Known Limitations),
and these are two separate Adobe systems with no documented guarantee
their id spaces line up. Also expected, not a bug: UMAPI's `id` is
"optional if unpopulated" per Adobe's own docs, and a technical/service
account (like the one this app's own credential authenticates as) very
plausibly has no directory entry at all — an unresolved id on a
scheduled/API-run query is the expected outcome for that case, not a
resolution failure.

**Rate limit — confirmed via Adobe's own docs, the strictest of any API
this app talks to by a wide margin**: 25 requests/minute per client, plus
a separate 100/minute cap shared across every client in the org. This
client's pacer is fixed well under the per-client limit (see
requests_per_second_override below) instead of sharing this app's usual
global `settings.requests_per_second` — there is no way for this app to
also protect the org-wide cap if other tools/clients share it. Adobe's own
guidance recommends syncing on an hourly-or-slower cadence; this app goes
further and caches the whole resolved directory in aep_monitor.db,
refetching only once `settings.user_directory_cache_hours` has passed
(see data.py's fetch_user_display_names()) — independent of how often the
Query Service page itself is refreshed.
"""

from typing import Any

import httpx

from ..config import settings
from .base import BaseAdobeClient

# Hard cap on pages fetched in one refresh, independent of `lastPage` — a
# very large org could otherwise page indefinitely and burn through the
# entire per-client rate budget (see module docstring) in a single
# refresh. Generous for almost any real org while still bounding the
# worst case.
_MAX_PAGES = 20


class UserManagementClient(BaseAdobeClient):
    base_url = settings.user_management_base_url
    requests_per_second_override = settings.user_management_requests_per_second

    async def list_users(self, http: httpx.AsyncClient) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = []
        for page in range(_MAX_PAGES):
            data = await self.get(http, f"/users/{self._org_id}/{page}")
            if not isinstance(data, dict):
                break
            page_users = data.get("users")
            if isinstance(page_users, list):
                users.extend(page_users)
            if data.get("lastPage", True):
                break
        return users

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.list_users(http)
        return True


def parse_user(item: dict[str, Any]) -> dict[str, str]:
    display = " ".join(part for part in (item.get("firstname"), item.get("lastname")) if part)
    return {
        "user_id": str(item.get("id") or ""),
        "email": str(item.get("email") or ""),
        "display_name": display or str(item.get("email") or item.get("username") or ""),
    }
