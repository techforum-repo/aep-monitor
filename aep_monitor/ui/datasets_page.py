from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import data
from ..utils import safe_csv
from .shared import get_active_sandbox, mark_cache_sandbox, refresh_button, render_friendly_error, sandbox_changed_since_cache, status_pill


def _do_refresh() -> None:
    active_sandbox = get_active_sandbox()
    try:
        st.session_state["dataset_rows"] = data.fetch_datasets(sandbox=active_sandbox)
        # Resolved alongside, same sandbox, same refresh — used purely for
        # display (schema title instead of a raw $id slug), so it's fetched
        # together with the datasets it labels rather than as a separate
        # cached/staleness-tracked thing of its own.
        st.session_state["dataset_schema_titles"] = data.fetch_schema_titles(sandbox=active_sandbox)
        mark_cache_sandbox("dataset_rows", active_sandbox)
        st.session_state["_datasets_error"] = None
    except Exception as exc:
        st.session_state["_datasets_error"] = exc


def render() -> None:
    st.markdown(f"### AEP Datasets · Sandbox: **{get_active_sandbox()}**")
    st.caption(
        "Catalog Service API: dataset metadata, the schema each dataset is bound to, and Profile/Identity "
        "enablement — follows the sidebar sandbox switcher, same as AEP Ingestion and Audit Log."
    )

    if refresh_button("Refresh from Adobe", key="datasets_refresh"):
        _do_refresh()
    if st.session_state.get("dataset_rows") is None or sandbox_changed_since_cache("dataset_rows", get_active_sandbox()):
        _do_refresh()

    error = st.session_state.get("_datasets_error")
    if error is not None:
        if render_friendly_error(error, key="datasets_retry", context="Fetching datasets"):
            _do_refresh()
            st.rerun()
        return

    rows = st.session_state.get("dataset_rows") or []
    if not rows:
        st.info("No datasets found for this sandbox/credential.")
        return

    schema_titles = st.session_state.get("dataset_schema_titles") or {}

    def _schema_display(schema_id: str) -> str:
        if not schema_id:
            return "—"
        # Falls back to the id's last URL segment (e.g. "loyalty-events")
        # when the title can't be resolved — a schema in a different
        # container (global vs. tenant), or one the schema list fetch
        # missed — rather than showing nothing or the full raw $id URL.
        return schema_titles.get(schema_id, schema_id.rsplit("/", 1)[-1])

    table = pd.DataFrame([
        {
            "Name": r["name"],
            "Description": r["description"],
            "Schema": _schema_display(r["schema_id"]),
            "Profile-enabled": status_pill("enabled" if r["profile_enabled"] else "disabled"),
            "Identity-enabled": status_pill("enabled" if r["identity_enabled"] else "disabled"),
            "Last updated": r["updated_at"] or "—",
        }
        for r in rows
    ])
    st.dataframe(table, use_container_width=True, hide_index=True, key="datasets_table")
    st.download_button("Download as CSV", safe_csv(table), "aep_datasets.csv", "text/csv")

    with st.expander("Raw response (first dataset)"):
        if rows:
            st.json(rows[0]["raw"], expanded=False)
