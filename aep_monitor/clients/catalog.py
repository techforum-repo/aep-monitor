from __future__ import annotations

"""AEP Catalog Service client — dataset metadata monitoring.

Docs: https://experienceleague.adobe.com/en/docs/experience-platform/catalog/api/getting-started
Confirmed base URL: https://platform.adobe.io/data/foundation/catalog

Two shape details confirmed via docs — both are genuinely different from
every other Adobe API this app talks to, called out explicitly so nobody
"fixes" this file to match the array-based convention everywhere else
without realizing why it's different:

1. `GET /dataSets` returns an object **keyed by dataset ID**, not an array
   — `{"<datasetId>": {name, description, ...}, ...}`. The ID only exists
   as the dict key; a dataset's own value object doesn't self-report its
   id. `parse_dataset()` below takes the id and the value as two separate
   arguments for exactly this reason.
2. By default Adobe only returns a small subset of fields (`name`,
   `description`, `files`) — everything else (`schemaRef`, `tags`,
   timestamps) must be explicitly requested via the `properties` query
   parameter (a comma-separated field list), or it's silently absent from
   the response rather than erroring.
"""

from typing import Any

import httpx

from ..config import settings
from ..utils import safe_dict
from .base import BaseAdobeClient

# Explicitly requested — see module docstring point 2. schemaRef.id is what
# links a dataset back to a schema (and to Compare's Schemas tab / SDR);
# tags carry the unifiedProfile/unifiedIdentity enabled flags.
_REQUESTED_PROPERTIES = "name,description,schemaRef,tags,created,updated"


class CatalogClient(BaseAdobeClient):
    base_url = settings.aep_catalog_base_url

    def _extra_headers(self) -> dict[str, str]:
        return {"x-sandbox-name": settings.adobe_sandbox}

    async def list_datasets(self, http: httpx.AsyncClient, limit: int = 100, sandbox: str | None = None) -> dict[str, Any]:
        """Returns the raw ID-keyed object as-is (not converted to a list
        here) — parse_dataset() needs both the id (the dict key) and the
        value, and dict.items() at the call site is the natural way to
        supply both without an intermediate reshaping step."""
        extra = {"x-sandbox-name": sandbox} if sandbox else None
        data = await self.get(http, "/dataSets", params={"limit": limit, "properties": _REQUESTED_PROPERTIES}, extra_headers=extra)
        return data if isinstance(data, dict) else {}

    async def test_connection(self) -> bool:
        async with self._new_http_client() as http:
            await self.list_datasets(http, limit=1)
        return True


def parse_dataset(dataset_id: str, item: dict[str, Any]) -> dict[str, Any]:
    tags = safe_dict(item.get("tags"))
    schema_ref = safe_dict(item.get("schemaRef"))
    return {
        "dataset_id": str(dataset_id or ""),
        "name": str(item.get("name") or dataset_id or "(unnamed)"),
        "description": str(item.get("description") or ""),
        "schema_id": str(schema_ref.get("id") or ""),
        # Adobe represents these as e.g. {"unifiedProfile": ["enabled:true"]}
        # — a list of strings, not a boolean — so presence of any entry
        # containing "enabled:true" is what "enabled" means here, not just
        # whether the tag key exists at all.
        "profile_enabled": any("enabled:true" in str(v) for v in tags.get("unifiedProfile", [])),
        "identity_enabled": any("enabled:true" in str(v) for v in tags.get("unifiedIdentity", [])),
        "created_at": str(item.get("created") or ""),
        "updated_at": str(item.get("updated") or ""),
        "raw": item,
    }
