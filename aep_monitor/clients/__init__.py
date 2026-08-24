from __future__ import annotations

"""One shared credential (settings.adobe_*) for every client — see
config.py's docstring: Adobe Developer Console supports adding every API
this app talks to (AEP, Reactor, CJA, Audit, Observability, Quota) to a
single project, so one client_id/secret/scope combination covers all of
them; there's no per-product credential split to configure."""

from ..config import settings
from .aep import AEPClient
from .audit import AuditClient
from .catalog import CatalogClient
from .cja import CJAClient
from .observability import ObservabilityClient
from .quota import QuotaClient
from .reactor import ReactorClient
from .schema_registry import SchemaRegistryClient

_credentials = (settings.adobe_client_id, settings.adobe_client_secret, settings.adobe_scopes, settings.adobe_org_id)

aep_client = AEPClient(*_credentials)
audit_client = AuditClient(*_credentials)
observability_client = ObservabilityClient(*_credentials)
quota_client = QuotaClient(*_credentials)
reactor_client = ReactorClient(*_credentials)
cja_client = CJAClient(*_credentials)
schema_registry_client = SchemaRegistryClient(*_credentials)
catalog_client = CatalogClient(*_credentials)
