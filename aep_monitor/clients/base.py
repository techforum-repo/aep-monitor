from __future__ import annotations

"""Shared HTTP plumbing for every Adobe API client: token attachment, request
pacing, and uniform error normalization. Each product client (aep.py,
reactor.py, cja.py, audit.py) subclasses BaseAdobeClient and only adds its
own base URL, extra headers, and endpoint methods.
"""

import threading
import time
from typing import Any

import httpx

from ..auth import get_token
from ..config import settings
from ..errors import AdobeRateLimitError


def _parse_retry_after(value: str | None) -> float | None:
    """Adobe sends Retry-After as seconds, not an HTTP-date."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class RequestPacer:
    """Enforces a minimum spacing between outgoing requests for one client
    instance. Adobe throttles per technical account, so pacing is scoped per
    credential (one pacer per client instance) rather than globally — an AEP
    poll and a CJA poll on different credentials shouldn't wait on each
    other."""

    def __init__(self, requests_per_second: float | None = None) -> None:
        """`requests_per_second=None` (every client except User Management —
        see clients/user_management.py) paces against the shared
        `settings.requests_per_second`, re-read on every call so a
        Settings-page-driven change applies immediately without a restart.
        A fixed value overrides that shared default for this client only —
        for a client whose own documented rate limit is nothing like the
        rest of this app's, a single global setting can't express both."""
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0
        self._fixed_rps = requests_per_second

    def wait(self) -> None:
        rps = self._fixed_rps if self._fixed_rps is not None else settings.requests_per_second
        if rps <= 0:
            return
        min_interval = 1.0 / rps
        with self._lock:
            now = time.monotonic()
            delay = self._next_allowed_at - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._next_allowed_at = now + min_interval


class BaseAdobeClient:
    """Not instantiated directly — see aep.py/reactor.py/cja.py/audit.py."""

    base_url: str = ""
    # Override in a subclass to pace that client independently of the
    # shared settings.requests_per_second default — see
    # clients/user_management.py, whose documented rate limit (25 req/min)
    # is far stricter than every other API this app talks to.
    requests_per_second_override: float | None = None

    def __init__(self, client_id: str, client_secret: str, scopes: str, org_id: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes
        self._org_id = org_id
        self._pacer = RequestPacer(requests_per_second=self.requests_per_second_override)

    def _new_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=settings.http_timeout, trust_env=True)

    def _extra_headers(self) -> dict[str, str]:
        """Overridden by subclasses that need product-specific headers
        (Reactor's JSON:API Accept/Content-Type, AEP's x-sandbox-name)."""
        return {}

    def _check_config(self) -> None:
        if not (self._client_id and self._client_secret and self._scopes and self._org_id):
            raise RuntimeError(f"{self.base_url} client is not configured — missing org id, client id, secret, or scopes.")

    async def _headers(self, http: httpx.AsyncClient, extra_headers: dict[str, str | None] | None = None) -> dict[str, str]:
        self._check_config()
        token = await get_token(http, self._client_id, self._client_secret, self._scopes)
        headers = {
            "Authorization": f"Bearer {token}",
            "x-api-key": self._client_id,
            "x-gw-ims-org-id": self._org_id,
        }
        headers.update(self._extra_headers())
        if extra_headers:
            # Per-call override — e.g. a different x-sandbox-name than the
            # configured default, so one client instance can be used to poll
            # multiple sandboxes (see ui/compare_page.py). A None value
            # removes that header entirely rather than overriding it — used
            # when a global default (e.g. x-sandbox-id) doesn't apply to the
            # overridden sandbox and would misattribute the request if left in.
            for key, value in extra_headers.items():
                if value is None:
                    headers.pop(key, None)
                else:
                    headers[key] = value
        return headers

    async def _request(self, http: httpx.AsyncClient, method: str, url: str, extra_headers: dict[str, str | None] | None = None, **kwargs: Any) -> Any:
        self._pacer.wait()
        try:
            response = await http.request(method, url, headers=await self._headers(http, extra_headers), **kwargs)
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            return response.json() if response.content else {}
        except httpx.ConnectError as exc:
            raise RuntimeError(f"Cannot connect to Adobe. Check VPN, proxy, and firewall. Endpoint: {url}") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Adobe request timed out. Endpoint: {url}") from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            if exc.response.status_code == 429:
                retry_after = _parse_retry_after(exc.response.headers.get("Retry-After"))
                raise AdobeRateLimitError(f"Adobe returned HTTP 429: {detail}", retry_after=retry_after) from exc
            raise RuntimeError(f"Adobe returned HTTP {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Adobe request failed: {exc}. Endpoint: {url}") from exc

    async def get(self, http: httpx.AsyncClient, path: str, extra_headers: dict[str, str | None] | None = None, **kwargs: Any) -> Any:
        return await self._request(http, "GET", f"{self.base_url}{path}", extra_headers=extra_headers, **kwargs)

    async def test_connection(self) -> bool:
        """Overridden per client with a cheap, harmless read call."""
        raise NotImplementedError
