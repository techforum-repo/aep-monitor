from __future__ import annotations

import streamlit as st

from .. import database
from ..clients import (
    aep_client,
    audit_client,
    catalog_client,
    cja_client,
    observability_client,
    query_service_client,
    quota_client,
    reactor_client,
    schema_registry_client,
    segmentation_client,
)
from ..config import settings
from ..logging_setup import LOG_PATH
from ..utils import run_async

_CLIENTS = {
    "AEP (Flow Service)": ("AEP", aep_client),
    "Data Collection (Reactor)": ("Data Collection", reactor_client),
    "CJA": ("CJA", cja_client),
    "Segmentation Service": ("Segmentation", segmentation_client),
    "Query Service": ("Query Service", query_service_client),
    "Audit Query": ("Audit", audit_client),
    "Observability Insights": ("Observability", observability_client),
    "Data Lifecycle Quota": ("Quota", quota_client),
    "Schema Registry": ("Schema Registry", schema_registry_client),
    "Catalog (Datasets)": ("Catalog", catalog_client),
}


def render() -> None:
    st.markdown("### Diagnostics")

    st.markdown("#### Connection tests")
    st.caption("Each test makes one small, harmless read call through that product's client.")
    for label, (source, client) in _CLIENTS.items():
        col1, col2 = st.columns([2, 5])
        with col1:
            run = st.button(f"Test {label}", key=f"diag_{source}")
        if run:
            mode = "mock" if settings.mock_mode else "live"
            try:
                if settings.mock_mode:
                    ok, detail = True, "Mock mode — no live call made."
                else:
                    run_async(client.test_connection())
                    ok, detail = True, "Connected."
            except Exception as exc:
                ok, detail = False, str(exc)
            database.record_connection_check(source, ok, mode, detail)
        check = database.last_connection_checks().get(source)
        with col2:
            if not check:
                st.caption("Not tested yet.")
            elif check["success"]:
                st.success(f"✅ {check['mode']} · {check['detail']} · {check['checked_at']}")
            else:
                st.error(f"❌ {check['mode']} · {check['detail']} · {check['checked_at']}")

    st.divider()
    st.markdown("#### Local storage")
    health = database.sqlite_health()
    counts = database.table_counts()
    c1, c2 = st.columns(2)
    c1.metric("SQLite integrity", "OK" if health["ok"] else "ISSUE")
    c2.metric("Size", f"{health['size_bytes'] / 1024:.0f} KB")
    st.json(counts, expanded=False)
    st.caption(f"Database: `{health['path']}`")

    st.divider()
    st.markdown("#### Logs")
    if LOG_PATH.exists():
        st.download_button("Download log file", LOG_PATH.read_bytes(), LOG_PATH.name, "text/plain")
    else:
        st.caption("No log file yet.")
