from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import data, database
from ..poller import refresh_cja
from ..utils import safe_csv
from .shared import format_timestamp, refresh_button, render_friendly_error, status_pill


def _resolve_name(lookup: dict[str, str], entity_id: str) -> str:
    """Resolve an id to a display name via `lookup`, falling back to the
    raw id — but visibly flagged as unresolved rather than blending in as
    if it were an actual name. A real, expected case (not just a bug):
    Connections needs product administration to see the full org-wide
    list and Data Views needs the credential's own Product Profile
    permissions (see README Known Limitations) — a connection/data view a
    project or data view references but this credential can't itself see
    falls back here, distinguishably, instead of silently."""
    if not entity_id:
        return "—"
    name = lookup.get(entity_id)
    return name if name else f"{entity_id} (unresolved)"


def _ensure_loaded() -> None:
    # Checks all three, not just cja_connections: the Overview page's
    # "Refresh everything" populates cja_connections (via refresh_all() ->
    # refresh_cja()) but has no reason to know this page also needs
    # cja_dataviews/cja_projects, so it never sets them. Visiting Overview
    # first (the app's default landing page) then clicking into CJA left
    # cja_dataviews stuck at its initial None forever — "No data views
    # found" even when data views exist — until a manual "Refresh from
    # Adobe" click on this page specifically; cja_projects is added here
    # from the start rather than repeating that same live bug a second time.
    if st.session_state.cja_connections is None or st.session_state.cja_dataviews is None or st.session_state.cja_projects is None:
        _do_refresh()


def _do_refresh() -> None:
    try:
        st.session_state.cja_connections = refresh_cja()
        st.session_state.cja_dataviews = data.fetch_cja_dataviews()
        # Cheap list-only call (no per-project definition fetch — that's
        # SDR's Component Usage tab, deliberately opt-in for its N+1 cost)
        # so it's safe to auto-load here alongside Connections/Data views.
        st.session_state.cja_projects = data.fetch_cja_projects()
        st.session_state["_cja_error"] = None
    except Exception as exc:
        st.session_state["_cja_error"] = exc


def render() -> None:
    st.markdown("### CJA — Connections, data views & projects")
    st.caption("Customer Journey Analytics API: connection status, data views built on each connection, and the Workspace projects built on those data views.")

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
    projects = st.session_state.cja_projects or []
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
            {"Data view": d["name"], "Connection": _resolve_name(names_by_conn, d["connection_id"]), "Owner": d["owner"] or "—"}
            for d in dataviews
        ])
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.download_button("Download as CSV", safe_csv(table), "cja_dataviews.csv", "text/csv")

    st.divider()
    st.markdown("#### Projects")
    if not projects:
        st.info(
            "No CJA Workspace projects found. `includeType=all` is requested (Adobe's own docs describe it as "
            "the admin-scoped option), so — same as Connections above — this credential's technical account "
            "may need CJA product administration to see the org's full project list rather than just what it "
            "owns itself."
        )
    else:
        names_by_dv = {d["dataview_id"]: d["name"] for d in dataviews}
        # Recomputed here rather than reusing the Data views section's own
        # local — that block only runs (and only defines this) when
        # `dataviews` is non-empty, and Projects can still have rows to
        # show even then.
        conn_id_by_dv = {d["dataview_id"]: d["connection_id"] for d in dataviews}
        names_by_conn = {c["connection_id"]: c["name"] for c in connections}
        table = pd.DataFrame([
            {
                "Project": p["name"],
                "Data view": _resolve_name(names_by_dv, p["dataview_id"]),
                # Two-hop resolution (project -> data view -> connection) —
                # unresolved at either hop still falls back distinguishably
                # rather than silently showing a raw id.
                "Connection": _resolve_name(names_by_conn, conn_id_by_dv.get(p["dataview_id"], "")),
                "Owner": p["owner"] or "—",
                "Created": p["created_at"] or "—",
            }
            for p in projects
        ])
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.download_button("Download as CSV", safe_csv(table), "cja_projects.csv", "text/csv")
        st.caption(
            "For which dimensions/metrics/calculated metrics each project actually references (and which "
            "ones on a data view are unused by any project), see the SDR page's Component Usage tab."
        )
