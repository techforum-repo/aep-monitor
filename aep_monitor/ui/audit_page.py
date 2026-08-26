from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import data
from ..utils import safe_csv
from .shared import get_active_sandbox, mark_cache_sandbox, refresh_button, render_friendly_error, sandbox_changed_since_cache


def _render_events_table(events: list[dict], *, csv_filename: str, key_prefix: str, description_col: bool = False) -> None:
    columns = [
        {"When": e["timestamp"], "Actor": e["actor"], "Action": e["action"], "Target": e["target"], **({"Description": e.get("description", "")} if description_col else {})}
        for e in events
    ]
    table = pd.DataFrame(columns)
    st.dataframe(table, use_container_width=True, hide_index=True, key=f"{key_prefix}_table")
    st.download_button("Download as CSV", safe_csv(table), csv_filename, "text/csv", key=f"{key_prefix}_csv")
    with st.expander("Raw response (first event)"):
        st.json(events[0]["raw"], expanded=False)


# --- AEP -------------------------------------------------------------------------

def _do_refresh_aep() -> None:
    active_sandbox = get_active_sandbox()
    try:
        st.session_state.audit_events = data.fetch_audit_events(limit=100, sandbox=active_sandbox)
        mark_cache_sandbox("audit_events", active_sandbox)
        st.session_state["_audit_error"] = None
    except Exception as exc:
        st.session_state["_audit_error"] = exc


def _render_aep_section() -> None:
    st.markdown(f"#### AEP — who changed what · Sandbox: **{get_active_sandbox()}**")
    st.caption("Audit Query API. This endpoint's contract is the least exercised part of this app — see the README.")

    if refresh_button("Refresh", key="audit_refresh"):
        _do_refresh_aep()
    if st.session_state.audit_events is None or sandbox_changed_since_cache("audit_events", get_active_sandbox()):
        _do_refresh_aep()

    error = st.session_state.get("_audit_error")
    if error is not None:
        if render_friendly_error(error, key="audit_retry", context="Fetching AEP audit events"):
            _do_refresh_aep()
            st.rerun()
        return

    events = st.session_state.audit_events or []
    if not events:
        st.info("No audit events returned. Confirm the credential's product profile has \"View User Activity Log\" granted.")
        return
    _render_events_table(events, csv_filename="aep_audit_events.csv", key_prefix="aep_audit")


# --- Data Collection ---------------------------------------------------------------

def _do_refresh_dc() -> None:
    try:
        st.session_state["dc_audit_events"] = data.fetch_dc_audit_events(limit=50)
        st.session_state["_dc_audit_error"] = None
    except Exception as exc:
        st.session_state["_dc_audit_error"] = exc


def _render_dc_section() -> None:
    st.markdown("#### Data Collection — who changed what")
    st.caption(
        "Reactor's Audit Events API. Org-wide, not sandbox-scoped. Adobe's own docs call this endpoint's "
        "implementation \"in flux\" — the least stable integration in this app."
    )

    if refresh_button("Refresh", key="dc_audit_refresh"):
        _do_refresh_dc()
    if st.session_state.get("dc_audit_events") is None:
        _do_refresh_dc()

    error = st.session_state.get("_dc_audit_error")
    if error is not None:
        if render_friendly_error(error, key="dc_audit_retry", context="Fetching Data Collection audit events"):
            _do_refresh_dc()
            st.rerun()
        return

    events = st.session_state.get("dc_audit_events") or []
    if not events:
        st.info("No audit events returned.")
        return
    _render_events_table(events, csv_filename="dc_audit_events.csv", key_prefix="dc_audit")


# --- CJA -----------------------------------------------------------------------

def _do_refresh_cja() -> None:
    try:
        st.session_state["cja_audit_logs"] = data.fetch_cja_audit_logs(limit=50)
        st.session_state["_cja_audit_error"] = None
    except Exception as exc:
        st.session_state["_cja_audit_error"] = exc


def _render_cja_section() -> None:
    st.markdown("#### CJA — who changed what")
    st.caption(
        "CJA's own Audit Logs API — a separate namespace from every other CJA endpoint in this app. "
        "Org-wide, not sandbox-scoped."
    )

    if refresh_button("Refresh", key="cja_audit_refresh"):
        _do_refresh_cja()
    if st.session_state.get("cja_audit_logs") is None:
        _do_refresh_cja()

    error = st.session_state.get("_cja_audit_error")
    if error is not None:
        if render_friendly_error(error, key="cja_audit_retry", context="Fetching CJA audit logs"):
            _do_refresh_cja()
            st.rerun()
        return

    events = st.session_state.get("cja_audit_logs") or []
    if not events:
        st.info(
            "No audit logs returned. If your org has recent CJA activity, this credential's technical account "
            "may need the same **product administration** privileges as the CJA page's Connections note."
        )
        return
    _render_events_table(events, csv_filename="cja_audit_logs.csv", key_prefix="cja_audit", description_col=True)


def render() -> None:
    st.markdown("### Audit Log — Who changed what across AEP, Data Collection, and CJA")
    _render_aep_section()
    st.divider()
    _render_dc_section()
    st.divider()
    _render_cja_section()
