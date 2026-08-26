from __future__ import annotations

"""BaseAdobeClient._headers()'s extra_headers merge — including the
None-removes-a-header behavior added to fix a code-review finding where
x-sandbox-id stayed pinned to the globally configured value even when
x-sandbox-name was overridden per sandbox (Compare page's Sandboxes tab), risking a
mismatched name/id pair sent to Adobe.

auth.get_token is monkeypatched to a stub so these run with no network
access and no real credentials. Plain sync test functions wrapping
asyncio.run() — no pytest-asyncio dependency, matching adobe-access-manager's
test suite, which bridges the same way via its own run_async() equivalent.
"""

import asyncio

import pytest

from aep_monitor.clients import base as base_module
from aep_monitor.clients.base import BaseAdobeClient


@pytest.fixture(autouse=True)
def _stub_token(monkeypatch):
    async def _fake_get_token(http, client_id, client_secret, scopes):
        return "fake-token"
    # base.py does `from ..auth import get_token`, binding its own name —
    # patching aep_monitor.auth.get_token would miss that binding entirely.
    monkeypatch.setattr(base_module, "get_token", _fake_get_token)


class _FixedHeaderClient(BaseAdobeClient):
    """A minimal concrete client whose _extra_headers() always sends a
    sandbox pair, mirroring ObservabilityClient's shape without importing
    the real config-derived base_url."""
    base_url = "https://example.invalid"

    def _extra_headers(self) -> dict[str, str]:
        return {"x-sandbox-name": "prod", "x-sandbox-id": "global-sandbox-id"}


def test_extra_headers_overrides_a_value():
    client = _FixedHeaderClient("cid", "secret", "scope", "org")
    headers = asyncio.run(client._headers(http=None, extra_headers={"x-sandbox-name": "dev"}))
    assert headers["x-sandbox-name"] == "dev"
    assert headers["x-sandbox-id"] == "global-sandbox-id"  # untouched by this override


def test_extra_headers_none_value_removes_the_header_entirely():
    client = _FixedHeaderClient("cid", "secret", "scope", "org")
    headers = asyncio.run(client._headers(http=None, extra_headers={"x-sandbox-name": "dev", "x-sandbox-id": None}))
    assert headers["x-sandbox-name"] == "dev"
    assert "x-sandbox-id" not in headers


def test_no_extra_headers_leaves_the_configured_defaults_untouched():
    client = _FixedHeaderClient("cid", "secret", "scope", "org")
    headers = asyncio.run(client._headers(http=None))
    assert headers["x-sandbox-name"] == "prod"
    assert headers["x-sandbox-id"] == "global-sandbox-id"


def test_base_auth_headers_are_always_present():
    client = _FixedHeaderClient("my-client-id", "secret", "scope", "my-org")
    headers = asyncio.run(client._headers(http=None))
    assert headers["Authorization"] == "Bearer fake-token"
    assert headers["x-api-key"] == "my-client-id"
    assert headers["x-gw-ims-org-id"] == "my-org"


def test_audit_client_sends_sandbox_name_header(monkeypatch):
    """Regression: shipped without this header entirely, and Adobe
    returned a live HTTP 400 'Missing Sandbox Information' as a result —
    Adobe's own docs consulted while building this client didn't call it
    out as required for this specific endpoint."""
    from aep_monitor.clients.audit import AuditClient
    from aep_monitor.config import settings
    monkeypatch.setattr(settings, "adobe_sandbox", "prod")
    client = AuditClient("cid", "secret", "scope", "org")
    headers = asyncio.run(client._headers(http=None))
    assert headers["x-sandbox-name"] == "prod"


def test_quota_client_sends_sandbox_name_header(monkeypatch):
    """Sent defensively — the docs consulted for this client didn't list
    it as required either, but the identical gap just broke Audit live
    (see above), and what this client reports (dataset expiration,
    consumer-delete identities) is plausibly sandbox-scoped too."""
    from aep_monitor.clients.quota import QuotaClient
    from aep_monitor.config import settings
    monkeypatch.setattr(settings, "adobe_sandbox", "prod")
    client = QuotaClient("cid", "secret", "scope", "org")
    headers = asyncio.run(client._headers(http=None))
    assert headers["x-sandbox-name"] == "prod"


def test_segmentation_client_sends_sandbox_name_header(monkeypatch):
    """Sent defensively, same reasoning as quota.py/audit.py above — not
    confirmed as required from docs, but the identical gap has broken a
    real endpoint in this app before, and Profile/Segmentation is plausibly
    sandbox-scoped the same way datasets and schemas are."""
    from aep_monitor.clients.segmentation import SegmentationClient
    from aep_monitor.config import settings
    monkeypatch.setattr(settings, "adobe_sandbox", "prod")
    client = SegmentationClient("cid", "secret", "scope", "org")
    headers = asyncio.run(client._headers(http=None))
    assert headers["x-sandbox-name"] == "prod"


def test_query_service_client_sends_sandbox_name_header(monkeypatch):
    from aep_monitor.clients.query_service import QueryServiceClient
    from aep_monitor.config import settings
    monkeypatch.setattr(settings, "adobe_sandbox", "prod")
    client = QueryServiceClient("cid", "secret", "scope", "org")
    headers = asyncio.run(client._headers(http=None))
    assert headers["x-sandbox-name"] == "prod"


def test_segmentation_client_sends_the_confirmed_sort_syntax_for_segment_jobs(monkeypatch):
    """Regression for a real live bug: the original `sort` value was
    "desc:createdAt" (order and attribute name both backwards) — Adobe
    rejected it outright with HTTP 400 "The expression used is invalid".
    Confirmed live via Adobe's own docs example: the syntax is
    "[attribute]:[asc|desc]", e.g. "creationTime:desc"."""
    from aep_monitor.clients.segmentation import SegmentationClient

    captured: dict = {}

    async def _fake_get(self, http, path, extra_headers=None, **kwargs):
        captured["path"] = path
        captured["kwargs"] = kwargs
        return {}

    monkeypatch.setattr(SegmentationClient, "get", _fake_get)
    client = SegmentationClient("cid", "secret", "scope", "org")
    asyncio.run(client.list_segment_jobs(http=None))

    assert captured["path"] == "/segment/jobs"
    assert captured["kwargs"]["params"]["sort"] == "creationTime:desc"


def test_schema_registry_client_requests_label_descriptors_with_the_confirmed_filter(monkeypatch):
    """Confirmed *live*, not from docs (Adobe's own reference doc for this
    endpoint doesn't document a schema/type filter at all, and doesn't
    even list xdm:descriptorLabel as a supported @type): `property=
    <field>==<value>` is a real, repeatable, ANDed server-side filter —
    Adobe's own UI issues it under the hood. list_label_descriptors() uses
    `property=@type==xdm:descriptorLabel` to fetch only label descriptors
    instead of every descriptor type org-wide. Regression coverage for the
    exact request shape that was wrong before this was confirmed live."""
    from aep_monitor.clients.schema_registry import SchemaRegistryClient

    captured: dict = {}

    async def _fake_get(self, http, path, extra_headers=None, **kwargs):
        captured["path"] = path
        captured["extra_headers"] = extra_headers
        captured["kwargs"] = kwargs
        return {}

    monkeypatch.setattr(SchemaRegistryClient, "get", _fake_get)
    client = SchemaRegistryClient("cid", "secret", "scope", "org")
    asyncio.run(client.list_label_descriptors(http=None, sandbox="prod"))

    assert captured["path"] == "/tenant/descriptors"
    assert captured["kwargs"]["params"]["property"] == "@type==xdm:descriptorLabel"
    # Regression: this app originally sent limit=500 (the general schema
    # registry docs' page-size max elsewhere), and Adobe returned a live
    # HTTP 400 "Query limit out of range... valid query limit is 0 - 300"
    # — this endpoint's actual max, confirmed live, is 300.
    assert captured["kwargs"]["params"]["limit"] == 300
    assert captured["extra_headers"]["Accept"] == "application/vnd.adobe.xdm+json"
    assert captured["extra_headers"]["x-sandbox-name"] == "prod"


def test_cja_client_requests_projects_with_include_type_all(monkeypatch):
    """Confirmed via Adobe's own docs: /projects' default scope is
    narrower than "every project the org has" (`all` is documented as the
    admin-scoped option) — the same owner-only-by-default pattern CJA
    Connections has. Also confirmed via docs: `ownerFullName` is a valid
    expansion value on the *list* endpoint specifically, resolving every
    project's owner to a display name in the one bulk call rather than a
    per-project or per-user lookup. Regression coverage for the exact
    request shape: list_projects() and get_project() must both send
    includeType=all, not rely on whatever the unscoped default returns."""
    from aep_monitor.clients.cja import CJAClient

    captured: dict = {}

    async def _fake_request(self, http, method, url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return []

    monkeypatch.setattr(CJAClient, "_request", _fake_request)
    client = CJAClient("cid", "secret", "scope", "org")
    asyncio.run(client.list_projects(http=None))

    assert captured["kwargs"]["params"]["includeType"] == "all"
    assert captured["kwargs"]["params"]["expansion"] == "ownerFullName"

    async def _fake_request_single(self, http, method, url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return {}

    monkeypatch.setattr(CJAClient, "_request", _fake_request_single)
    asyncio.run(client.get_project(http=None, project_id="proj1"))

    assert captured["kwargs"]["params"]["includeType"] == "all"
    assert captured["kwargs"]["params"]["expansion"] == "definition,ownerFullName"
