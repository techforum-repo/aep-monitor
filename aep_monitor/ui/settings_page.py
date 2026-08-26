from __future__ import annotations

import streamlit as st

from ..config import settings


def _mask(value: str) -> str:
    if not value:
        return "(not set)"
    return f"{value[:4]}…{value[-2:]}" if len(value) > 8 else "•••"


def render() -> None:
    st.markdown("### Settings")
    st.caption(
        "Secrets and connection settings live in `.env`, not here — edit that file and restart the app. "
        "This page shows the effective configuration so a misconfigured credential is easy to spot."
    )

    st.markdown("#### Mode")
    st.write(f"**{'Mock / demo data' if settings.mock_mode else 'Live'}** (`MOCK_MODE` in `.env`)")

    st.markdown("#### Credential (shared by every product)")
    st.caption(
        "One Adobe I/O credential for AEP, Data Collection, CJA, Audit Query, Observability, and Quota — "
        "add every API to the same Developer Console project (see `.env.example` for exact steps)."
    )
    st.table({
        "Field": ["Org ID", "Client ID", "Client secret", "Scopes", "Sandbox"],
        "Value": [
            settings.adobe_org_id or "(not set)",
            _mask(settings.adobe_client_id),
            _mask(settings.adobe_client_secret),
            settings.adobe_scopes or "(not set)",
            settings.adobe_sandbox,
        ],
    })
    st.write("Status: " + ("✅ configured" if settings.adobe_configured else "⚠️ incomplete — required fields missing"))

    st.markdown("#### Alerting")
    st.write(f"Failed-record threshold: **{settings.alert_failed_records_threshold}** (a run alerts once failed records exceed this)")
    st.write(f"Quota threshold: **{settings.alert_quota_threshold_pct:.0f}%** (a quota alerts once consumed/quota reaches this)")
    st.write("Slack webhook: " + ("✅ configured" if settings.slack_webhook_url else "not set — alerts only show in-app"))

    st.markdown("#### Networking")
    st.write(
        f"Requests/sec per client (shared default): **{settings.requests_per_second}** · "
        f"User Management API (its own, stricter pace — see below): **{settings.user_management_requests_per_second}**/s · "
        f"HTTP timeout: **{settings.http_timeout}s**"
    )
    st.caption(
        "Adobe's documented (static, not queryable) API rate limits — not something this app monitors live, "
        "shown here as reference: AEP data lake ingestion ~4000–5000 req/s · profile/streaming segmentation "
        "~1500 req/s · CJA/Analytics 20,000 calls/hour · Analytics 2.0 120 req/min · **User Management API "
        "25 req/min per client, 100/min shared org-wide across every client** — by far the strictest of any "
        "API this app talks to, which is why it gets its own pacer instead of sharing the default above, plus "
        f"its own {settings.user_directory_cache_hours:.0f}h cache (see the Query Service page's \"Run by\" "
        "column) rather than refetching on every refresh."
    )

    st.divider()
    st.caption("Base URLs:")
    st.code(
        f"AEP Flow Service      : {settings.aep_flowservice_base_url}\n"
        f"AEP Audit Query       : {settings.aep_audit_base_url}\n"
        f"AEP Observability     : {settings.aep_observability_base_url}\n"
        f"AEP Data Lifecycle    : {settings.aep_quota_base_url}\n"
        f"AEP Schema Registry   : {settings.aep_schema_registry_base_url}\n"
        f"Reactor               : {settings.reactor_base_url}\n"
        f"CJA                   : {settings.cja_base_url}",
        language="text",
    )
