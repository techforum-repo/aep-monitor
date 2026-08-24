from __future__ import annotations

"""Adobe IMS OAuth Server-to-Server token issuance, cached per client_id.

Cached by client_id (not per-client-instance) because AEP, Data Collection,
and CJA often share the same credential — reusing the cached token avoids a
redundant IMS round-trip on every poll cycle across all three.
"""

import threading
import time

import httpx

from .config import settings

_token_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


async def get_token(http: httpx.AsyncClient, client_id: str, client_secret: str, scopes: str) -> str:
    with _lock:
        cached = _token_cache.get(client_id)
    if cached and time.time() < cached[1] - 60:
        return cached[0]

    try:
        response = await http.post(
            settings.adobe_ims_token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
                "scope": scopes,
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Adobe IMS connection failed: {exc}") from exc

    data = response.json()
    token = data["access_token"]
    expires_at = time.time() + int(data.get("expires_in", 86399))
    with _lock:
        _token_cache[client_id] = (token, expires_at)
    return token


def clear_cache() -> None:
    """Used by Settings when a credential is changed at runtime, so a stale
    token for the old client_id can't linger for up to 24h."""
    with _lock:
        _token_cache.clear()
