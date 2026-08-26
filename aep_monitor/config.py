from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .utils import harden_file_permissions

# Resolved relative to the project root as long as the app is started from
# there (true for start-unix.sh / start-windows.bat / `streamlit run app.py`
# from a checkout) — same convention as database.py's DB_PATH.
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    app_env: str = "development"

    # Mock mode serves realistic sample data for every API this app talks
    # to (AEP, Data Collection, CJA, Audit Query, Observability, Quota) so
    # the dashboard is fully explorable before any Adobe credential exists.
    # Flips to live automatically once adobe_configured is true, unless
    # forced with MOCK_MODE=true.
    mock_mode: bool = True

    # --- Adobe I/O OAuth Server-to-Server credential ------------------------
    # One credential for every product this app talks to (AEP, Data
    # Collection/Reactor, CJA, Audit Query, Observability, Quota). Adobe
    # Developer Console supports adding all of their APIs to one project —
    # the scope string just combines them — so one client_id/secret covers
    # everything; see .env.example for the exact setup steps.
    adobe_org_id: str = ""
    adobe_client_id: str = ""
    adobe_client_secret: str = ""
    adobe_scopes: str = ""
    adobe_ims_token_url: str = "https://ims-na1.adobelogin.com/ims/token/v3"
    adobe_sandbox: str = "prod"
    # Observability Insights' docs list x-sandbox-id as required alongside
    # x-sandbox-name, but Adobe's own published Postman collection for the
    # same API only sends x-sandbox-name — the two disagree. Left optional;
    # only sent when set. Find it on the Sandboxes page in the AEP UI if the
    # Observability page errors without it.
    adobe_sandbox_id: str = ""
    # Comma-separated sandbox names for the sidebar switcher and the
    # Compare page's Sandboxes/Schemas tabs (e.g. "prod,dev,stage"). Only
    # AEP is actually sandbox-scoped in Adobe's architecture — Data
    # Collection, CJA, and the Quota API are org-wide —
    # so this only affects that one page. Empty defaults to just [adobe_sandbox].
    adobe_sandboxes: str = ""

    # --- API base URLs (rarely need changing) -------------------------------
    aep_flowservice_base_url: str = "https://platform.adobe.io/data/foundation/flowservice"
    aep_audit_base_url: str = "https://platform.adobe.io/data/foundation/audit"
    aep_observability_base_url: str = "https://platform.adobe.io/data/infrastructure/observability/insights"
    aep_quota_base_url: str = "https://platform.adobe.io/data/core/hygiene"
    reactor_base_url: str = "https://reactor.adobe.io"
    # Every CJA data endpoint (connections, dataviews, dimensions, metrics)
    # lives under /data — confirmed against Adobe's endpoint docs after this
    # was originally shipped without it (a live-only bug: every CJA call
    # would have 404'd against the real API despite working fine in mock
    # mode, since mock mode never hits a URL at all).
    cja_base_url: str = "https://cja.adobe.io/data"
    # CJA's Audit Logs API is a genuinely separate namespace from every
    # other CJA endpoint above (not under /data) — confirmed via Adobe's
    # own endpoint docs, not assumed.
    cja_auditlogs_base_url: str = "https://cja.adobe.io/auditlogs/api/v1"
    # Calculated Metrics is a third genuinely separate CJA namespace (also
    # not under /data) — confirmed via Adobe's own endpoint docs.
    cja_calculatedmetrics_base_url: str = "https://cja.adobe.io/calculatedmetrics"
    # Projects is a fourth genuinely separate CJA namespace (also not under
    # /data) — confirmed via Adobe's own endpoint docs and a live response.
    cja_projects_base_url: str = "https://cja.adobe.io/projects"
    aep_schema_registry_base_url: str = "https://platform.adobe.io/data/foundation/schemaregistry"
    aep_catalog_base_url: str = "https://platform.adobe.io/data/foundation/catalog"

    http_timeout: float = 30.0
    # Adobe doesn't publish one shared per-product rate limit; this is a
    # conservative default (one request every 200ms per client) to keep
    # polling well under it. Tunable from the Settings page without a restart.
    requests_per_second: float = 5.0

    # Poll results are cached this long before a page's "Refresh now" is
    # needed again — keeps repeated page visits cheap without going stale.
    cache_ttl_seconds: int = 300

    # --- Alert thresholds ----------------------------------------------------
    # A flow run is alert-worthy once its failed record count exceeds this
    # (0 = any failure at all alerts).
    alert_failed_records_threshold: int = 0
    # A data-lifecycle quota (dataset expiration, consumer-delete identities)
    # alerts once consumed/quota reaches this percentage.
    alert_quota_threshold_pct: float = 80.0
    slack_webhook_url: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def adobe_configured(self) -> bool:
        return all((self.adobe_org_id, self.adobe_client_id, self.adobe_client_secret, self.adobe_scopes))

    @property
    def effective_mock_mode(self) -> bool:
        """mock_mode is the explicit switch; it defaults True so a fresh
        checkout with no .env still runs. Once real credentials are filled
        in, .env should also flip MOCK_MODE=false — this property doesn't
        auto-flip it, so a half-configured .env fails loudly (via
        adobe_configured checks in each client) instead of silently mixing
        mock and live data."""
        return self.mock_mode

    @property
    def sandbox_list(self) -> list[str]:
        names = [s.strip() for s in self.adobe_sandboxes.split(",") if s.strip()]
        return names or ([self.adobe_sandbox] if self.adobe_sandbox else [])


settings = Settings()


def harden_env_file() -> None:
    """Restrict .env (holds Adobe client secrets) to the owning user only —
    mirrors how database.py hardens the SQLite DB and logging_setup.py
    hardens the log file. Called explicitly from app.py's startup, not at
    import time, so importing this module never has filesystem side effects
    on its own."""
    if ENV_PATH.exists():
        harden_file_permissions(ENV_PATH)
