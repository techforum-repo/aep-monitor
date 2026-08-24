from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import database
from ..poller import refresh_dc
from ..utils import safe_csv
from .shared import format_timestamp, refresh_button, render_friendly_error, status_pill


def _ensure_loaded() -> None:
    if st.session_state.dc_rows is None:
        _do_refresh()


def _do_refresh() -> None:
    try:
        st.session_state.dc_rows = refresh_dc()
        st.session_state["_dc_error"] = None
    except Exception as exc:
        st.session_state["_dc_error"] = exc


def render() -> None:
    st.markdown("### Data Collection — Properties, extensions & publish status")
    st.caption("Reactor API: extension review status, environment build status (especially production), and data element publish state per property.")

    if refresh_button("Refresh from Adobe", key="dc_refresh"):
        _do_refresh()
    _ensure_loaded()

    error = st.session_state.get("_dc_error")
    if error is not None:
        if render_friendly_error(error, key="dc_retry", context="Fetching properties, extensions, rules, libraries, environments, and data elements"):
            _do_refresh()
            st.rerun()
        return

    rows = st.session_state.dc_rows or []
    st.caption(f"Last refreshed {format_timestamp(database.latest_checked_at('Data Collection'))}")

    if not rows:
        st.info("No properties found for this company/credential.")
        return

    table = pd.DataFrame([
        {
            "Property": r["property_name"],
            "Extensions": r["extension_count"],
            "Extension issues": r["extension_issue_count"],
            "Rules": r["rule_count"],
            "Libraries": r["library_count"],
            "Library issues": r["library_issue_count"],
            "Environments": r["environment_count"],
            "Production issues": r["production_environment_issue_count"],
            "Data elements": r["data_element_count"],
            "Data element issues": r["data_element_issue_count"],
            "property_id": r["property_id"],
        }
        for r in rows
    ])
    st.dataframe(table.drop(columns=["property_id"]), use_container_width=True, hide_index=True)
    st.download_button("Download as CSV", safe_csv(table.drop(columns=["property_id"])), "dc_properties.csv", "text/csv")

    st.divider()
    st.markdown("#### Property detail")
    names_by_id = {r["property_id"]: r["property_name"] for r in rows}
    selected_id = st.selectbox("Choose a property", list(names_by_id.keys()), format_func=lambda pid: names_by_id[pid])
    selected_row = next(r for r in rows if r["property_id"] == selected_id)

    tab_ext, tab_rules, tab_libs, tab_envs, tab_data_elements = st.tabs(
        ["Extensions", "Rules", "Libraries", "Environments", "Data Elements"]
    )
    with tab_ext:
        for ext in selected_row.get("extensions", []):
            st.markdown(f"- **{ext['name']}** — {status_pill(ext['review_status'] or ('published' if ext['published'] else 'unpublished'))}")
        if not selected_row.get("extensions"):
            st.caption("No extensions.")
    with tab_rules:
        for rule in selected_row.get("rules", []):
            state = "enabled" if rule["enabled"] else "disabled"
            st.markdown(f"- **{rule['name']}** — {status_pill(state)} · {'published' if rule['published'] else 'unpublished'}")
        if not selected_row.get("rules"):
            st.caption("No rules.")
    with tab_libs:
        for lib in selected_row.get("libraries", []):
            st.markdown(f"- **{lib['name']}** — {status_pill(lib['state'])}")
        if not selected_row.get("libraries"):
            st.caption("No libraries.")
    with tab_envs:
        for env in selected_row.get("environments", []):
            marker = " 🏭" if env["stage"] == "production" else ""
            st.markdown(f"- **{env['name']}**{marker} ({env['stage']}) — {status_pill(env['status'])}")
        if not selected_row.get("environments"):
            st.caption("No environments.")
    with tab_data_elements:
        for de in selected_row.get("data_elements", []):
            # status_pill() only recognizes single canonical words (see
            # shared.py's _GOOD/_WARNING/_BAD_STATES) — pick the single
            # most severe one rather than concatenating dirty+review_status
            # into a composite string that would never match any of them
            # and silently always render neutral regardless of real severity.
            if de["review_status"] == "rejected":
                pill_state = "rejected"
            elif de["dirty"]:
                pill_state = "pending"  # unpublished local changes
            elif de["published"]:
                pill_state = "published"
            else:
                pill_state = "unpublished"
            detail = f" ({de['review_status']})" if de["review_status"] and de["review_status"] != pill_state else ""
            st.markdown(f"- **{de['name']}** — {status_pill(pill_state)}{detail}")
        if not selected_row.get("data_elements"):
            st.caption("No data elements.")
