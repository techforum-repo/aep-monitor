from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import data, database
from ..poller import refresh_cja
from ..utils import safe_csv
from .shared import format_timestamp, refresh_button, render_friendly_error, status_pill


def _ensure_loaded() -> None:
    # Checks both, not just cja_connections: the Overview page's "Refresh
    # everything" populates cja_connections (via refresh_all() -> refresh_cja())
    # but has no reason to know this page also needs cja_dataviews, so it
    # never sets it. Visiting Overview first (the app's default landing
    # page) then clicking into CJA left cja_dataviews stuck at its initial
    # None forever — "No data views found" even when data views exist —
    # until a manual "Refresh from Adobe" click on this page specifically.
    if st.session_state.cja_connections is None or st.session_state.cja_dataviews is None:
        _do_refresh()


def _do_refresh() -> None:
    try:
        st.session_state.cja_connections = refresh_cja()
        st.session_state.cja_dataviews = data.fetch_cja_dataviews()
        st.session_state["_cja_error"] = None
    except Exception as exc:
        st.session_state["_cja_error"] = exc


def render() -> None:
    st.markdown("### CJA — Connections & data views")
    st.caption("Customer Journey Analytics API: connection status and data views built on it.")

    if refresh_button("Refresh from Adobe", key="cja_refresh"):
        _do_refresh()
    _ensure_loaded()

    error = st.session_state.get("_cja_error")
    if error is not None:
        if render_friendly_error(error, key="cja_retry", context="Fetching connections and data views"):
            _do_refresh()
            st.rerun()
        return

    connections = st.session_state.cja_connections or []
    dataviews = st.session_state.cja_dataviews or []
    st.caption(f"Last refreshed {format_timestamp(database.latest_checked_at('CJA'))}")

    st.markdown("#### Connections")
    if not connections:
        st.info(
            "No connections found. If connections exist in the CJA UI, this credential's technical account "
            "likely needs **product administration** privileges for CJA (not just profile membership) — "
            "Adobe's API silently returns only connections it owns otherwise, which for a service account is "
            "none. See README Known Limitations for how to grant it."
        )
    else:
        table = pd.DataFrame([
            {"Connection": c["name"], "Status": status_pill(c["status"]), "Last updated": c["updated_at"] or "—"}
            for c in connections
        ])
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.download_button("Download as CSV", safe_csv(table), "cja_connections.csv", "text/csv")

    st.divider()
    st.markdown("#### Data views")
    if not dataviews:
        st.info(
            "No data views found — unlike Connections, this doesn't need product administration. Check that "
            "this credential's Product Profile has the required data views assigned under its own Permissions "
            "tab (confirmed live: that alone is sufficient, no admin grant needed)."
        )
    else:
        names_by_conn = {c["connection_id"]: c["name"] for c in connections}
        table = pd.DataFrame([
            {"Data view": d["name"], "Connection": names_by_conn.get(d["connection_id"], d["connection_id"] or "—"), "Owner": d["owner"] or "—"}
            for d in dataviews
        ])
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.download_button("Download as CSV", safe_csv(table), "cja_dataviews.csv", "text/csv")
