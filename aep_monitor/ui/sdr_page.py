from __future__ import annotations

"""SDR ("Solution Design Reference") — a live, auto-generated reference of
what's actually configured, pulled from the CJA data-view components API
and the AEP Schema Registry, rather than a hand-maintained document that
drifts out of sync with reality. Not a diff against an existing SDR
document — see the page caption and the conversation this was scoped from.
"""

import pandas as pd
import streamlit as st

from .. import data
from ..utils import safe_csv
from .shared import get_active_sandbox, mark_cache_sandbox, refresh_button, render_friendly_error, sandbox_changed_since_cache


def _do_refresh_dataviews() -> None:
    try:
        st.session_state["sdr_dataviews"] = data.fetch_cja_dataviews()
        st.session_state["_sdr_dataviews_error"] = None
    except Exception as exc:
        st.session_state["_sdr_dataviews_error"] = exc


def _do_refresh_schemas() -> None:
    active_sandbox = get_active_sandbox()
    try:
        st.session_state["sdr_schemas"] = data.fetch_schemas(sandbox=active_sandbox)
        mark_cache_sandbox("sdr_schemas", active_sandbox)
        st.session_state["_sdr_schemas_error"] = None
    except Exception as exc:
        st.session_state["_sdr_schemas_error"] = exc


def _render_cja_section() -> None:
    st.markdown("#### CJA — Data view components")
    if refresh_button("Refresh data views", key="sdr_dataviews_refresh"):
        _do_refresh_dataviews()
        st.session_state["sdr_components_cache"] = {}
        st.session_state["sdr_component_usage_cache"] = {}
    if st.session_state.get("sdr_dataviews") is None:
        _do_refresh_dataviews()

    error = st.session_state.get("_sdr_dataviews_error")
    if error is not None:
        if render_friendly_error(error, key="sdr_dataviews_retry", context="Fetching data views"):
            _do_refresh_dataviews()
            st.rerun()
        return

    dataviews = st.session_state.get("sdr_dataviews") or []
    if not dataviews:
        st.info(
            "No data views found — check that this credential's Product Profile has the required data views "
            "assigned under its own Permissions tab (this doesn't need product administration; that's only "
            "required for Connections — see the CJA page's note, or README Known Limitations)."
        )
        return

    names_by_id = {dv["dataview_id"]: dv["name"] for dv in dataviews}
    selected_id = st.selectbox(
        "Data view", list(names_by_id.keys()), format_func=lambda dvid: names_by_id[dvid], key="sdr_dataview_select"
    )

    cache = st.session_state.setdefault("sdr_components_cache", {})
    if selected_id not in cache:
        with st.spinner("Loading dimensions, metrics, and calculated metrics..."):
            try:
                cache[selected_id] = {
                    "dimensions": data.fetch_cja_dimensions(selected_id),
                    "metrics": data.fetch_cja_metrics(selected_id),
                    "calculated_metrics": data.fetch_cja_calculated_metrics(selected_id),
                    "error": None,
                }
            except Exception as exc:
                cache[selected_id] = {"dimensions": [], "metrics": [], "calculated_metrics": [], "error": exc}

    entry = cache[selected_id]
    if entry["error"] is not None:
        render_friendly_error(entry["error"], key="sdr_components_retry", context=f"Fetching components for {names_by_id[selected_id]}")
        return

    tab_dims, tab_metrics, tab_calc_metrics, tab_usage = st.tabs([
        f"Dimensions ({len(entry['dimensions'])})", f"Metrics ({len(entry['metrics'])})",
        f"Calculated Metrics ({len(entry['calculated_metrics'])})", "Component Usage",
    ])
    with tab_dims:
        if entry["dimensions"]:
            table = pd.DataFrame([
                {"Name": d["name"], "Description": d["description"], "Type": d["type"], "Source field": d["source_field"], "Approved": d["approved"]}
                for d in entry["dimensions"]
            ])
            st.dataframe(table, use_container_width=True, hide_index=True, key="sdr_dimensions_table")
            st.download_button("Download as CSV", safe_csv(table), f"cja_{selected_id}_dimensions.csv", "text/csv", key="sdr_dims_csv")
        else:
            st.caption("No dimensions.")
    with tab_metrics:
        if entry["metrics"]:
            table = pd.DataFrame([
                {"Name": m["name"], "Description": m["description"], "Type": m["type"], "Source field": m["source_field"], "Approved": m["approved"]}
                for m in entry["metrics"]
            ])
            st.dataframe(table, use_container_width=True, hide_index=True, key="sdr_metrics_table")
            st.download_button("Download as CSV", safe_csv(table), f"cja_{selected_id}_metrics.csv", "text/csv", key="sdr_metrics_csv")
        else:
            st.caption("No metrics.")
    with tab_calc_metrics:
        if entry["calculated_metrics"]:
            table = pd.DataFrame([
                {"Name": m["name"], "Description": m["description"], "Type": m["type"], "Polarity": m["polarity"]}
                for m in entry["calculated_metrics"]
            ])
            st.dataframe(table, use_container_width=True, hide_index=True, key="sdr_calc_metrics_table")
            st.download_button("Download as CSV", safe_csv(table), f"cja_{selected_id}_calculated_metrics.csv", "text/csv", key="sdr_calc_metrics_csv")
        else:
            st.caption("No calculated metrics.")
    with tab_usage:
        _render_component_usage(selected_id, entry)


def _render_component_usage(selected_id: str, entry: dict) -> None:
    st.caption(
        "Which of this data view's dimensions, metrics, and calculated metrics are actually referenced by a "
        "CJA Workspace project — not just defined. There's no bulk endpoint for this (one API call per "
        "project bound to this data view, on top of the list call), so it's opt-in rather than loaded "
        "automatically with the tabs above."
    )
    usage_cache = st.session_state.setdefault("sdr_component_usage_cache", {})
    if selected_id not in usage_cache:
        if st.button("Load project usage", key="sdr_load_component_usage"):
            with st.spinner("Fetching every project bound to this data view..."):
                try:
                    references = data.fetch_cja_project_entity_references(selected_id)
                    usage_cache[selected_id] = {"references": references, "usage": data.aggregate_component_usage(references), "error": None}
                except Exception as exc:
                    usage_cache[selected_id] = {"references": [], "usage": {}, "error": exc}
            st.rerun()
        return

    usage_entry = usage_cache[selected_id]
    if usage_entry["error"] is not None:
        if render_friendly_error(usage_entry["error"], key="sdr_component_usage_retry", context="Fetching project component usage"):
            del usage_cache[selected_id]
            st.rerun()
        return

    references = usage_entry["references"]
    project_count = len({r["project_id"] for r in references}) if references else len({p["project_id"] for p in data.fetch_cja_projects() if p["dataview_id"] == selected_id})
    st.caption(f"{project_count} project(s) bound to this data view · {len(references)} raw component reference(s) found across them.")

    usage = usage_entry["usage"]
    known = [
        *[{"id": d["component_id"], "name": d["name"]} for d in entry["dimensions"]],
        *[{"id": m["component_id"], "name": m["name"]} for m in entry["metrics"]],
        *[{"id": m["component_id"], "name": m["name"]} for m in entry["calculated_metrics"]],
    ]
    if not known:
        st.caption("No dimensions, metrics, or calculated metrics defined on this data view.")
        return

    rows = []
    for component in known:
        matched = usage.get(component["id"])
        rows.append({
            "Name": component["name"],
            "Used in projects": len(matched["projects"]) if matched else 0,
            "Projects": ", ".join(matched["projects"]) if matched else "—",
        })
    table = pd.DataFrame(rows).sort_values("Used in projects")
    st.dataframe(table, use_container_width=True, hide_index=True, key="sdr_component_usage_table")
    st.download_button("Download as CSV", safe_csv(table), f"cja_{selected_id}_component_usage.csv", "text/csv", key="sdr_component_usage_csv")

    unused_count = int((table["Used in projects"] == 0).sum())
    if unused_count:
        st.caption(f"{unused_count} component(s) defined on this data view but not referenced by any of its bound projects.")

    # A project can reference a component that's since been removed from
    # (or was never added to) the data view's own component lists above —
    # a stale/orphaned reference worth surfacing separately, not silently
    # dropped just because it doesn't match anything in `known`.
    known_ids = {c["id"] for c in known}
    stale = [info for component_id, info in usage.items() if component_id not in known_ids]
    if stale:
        with st.expander(f"Referenced by a project but not in this data view's current component list ({len(stale)})"):
            stale_table = pd.DataFrame([
                {"Name": s["name"], "Type": s["type"], "Projects": ", ".join(s["projects"])}
                for s in stale
            ])
            st.dataframe(stale_table, use_container_width=True, hide_index=True, key="sdr_stale_usage_table")

    with st.expander(f"Raw entity references ({len(references)} found, unfiltered)"):
        st.caption(
            "Every `__entity__`-tagged reference this app found in the raw project definitions, before any "
            "matching or filtering — including ReportSuite/DateRange framing entities and anything whose id "
            "didn't match a known component. If every component above shows 0 usage despite projects that "
            "clearly reference some, compare an id here against a component's own id on the Dimensions/"
            "Metrics/Calculated Metrics tabs — a mismatch there (not an empty list here) is what a wrong "
            "assumption about Adobe's real entity shape would look like; an empty list here instead would "
            "mean the extraction itself found nothing to work with."
        )
        if references:
            st.dataframe(
                pd.DataFrame([{"Id": r["id"], "Type": r["type"], "Name": r["name"], "Project": r["project_name"]} for r in references]),
                use_container_width=True, hide_index=True, key="sdr_raw_entity_refs_table",
            )
        else:
            st.caption("No entity references extracted at all.")


def _render_aep_section() -> None:
    st.markdown("#### AEP — Schema fields")
    st.caption(f"Sandbox: **{get_active_sandbox()}**.")
    if refresh_button("Refresh schemas", key="sdr_schemas_refresh"):
        _do_refresh_schemas()
        st.session_state["sdr_schema_fields_cache"] = {}
        st.session_state["sdr_schema_labels_cache"] = {}
    if st.session_state.get("sdr_schemas") is None or sandbox_changed_since_cache("sdr_schemas", get_active_sandbox()):
        _do_refresh_schemas()
        # A schema_id cached under the previous sandbox isn't meaningful
        # here — the schema list itself just changed.
        st.session_state["sdr_schema_fields_cache"] = {}
        st.session_state["sdr_schema_labels_cache"] = {}

    error = st.session_state.get("_sdr_schemas_error")
    if error is not None:
        if render_friendly_error(error, key="sdr_schemas_retry", context="Fetching schemas"):
            _do_refresh_schemas()
            st.rerun()
        return

    schemas = st.session_state.get("sdr_schemas") or []
    if not schemas:
        st.info("No tenant schemas found for this credential/sandbox.")
        return

    titles_by_id = {s["schema_id"]: s["title"] for s in schemas}
    selected_id = st.selectbox(
        "Schema", list(titles_by_id.keys()), format_func=lambda sid: titles_by_id[sid], key="sdr_schema_select"
    )

    cache = st.session_state.setdefault("sdr_schema_fields_cache", {})
    if selected_id not in cache:
        with st.spinner("Loading schema fields..."):
            try:
                fields, raw = data.fetch_schema_fields(selected_id, sandbox=get_active_sandbox())
                cache[selected_id] = {"fields": fields, "raw": raw, "error": None}
            except Exception as exc:
                cache[selected_id] = {"fields": [], "raw": {}, "error": exc}

    entry = cache[selected_id]
    if entry["error"] is not None:
        render_friendly_error(entry["error"], key="sdr_schema_fields_retry", context=f"Fetching fields for {titles_by_id[selected_id]}")
        return

    fields = entry["fields"]
    if not fields:
        st.caption("No fields found (or the schema has an unexpected shape — check the raw response below against README's Known Limitations).")
        labels_entry = None
    else:
        labels_cache = st.session_state.setdefault("sdr_schema_labels_cache", {})
        active_sandbox = get_active_sandbox()
        if selected_id not in labels_cache:
            try:
                descriptors = data.fetch_label_descriptors(sandbox=active_sandbox)
                known_paths = {f["path"] for f in fields}
                labels_by_path: dict[str, list[str]] = {}
                for parsed in descriptors:
                    if parsed["path"] not in known_paths or not parsed["labels"]:
                        continue
                    labels_by_path.setdefault(parsed["path"], []).extend(parsed["labels"])
                labels_cache[selected_id] = {"descriptors": descriptors, "labels_by_path": labels_by_path, "error": None}
            except Exception as exc:
                # Labels are a best-effort layer on top of the fields table
                # — a fetch failure here is shown (below), but doesn't
                # block the fields table itself, the more load-bearing,
                # better-confirmed part of this page.
                labels_cache[selected_id] = {"descriptors": [], "labels_by_path": {}, "error": exc}
        labels_entry = labels_cache[selected_id]
        labels_by_path = labels_entry["labels_by_path"]

        def _labels_for(path: str) -> str:
            codes = labels_by_path.get(path)
            return ", ".join(codes) if codes else "—"

        table = pd.DataFrame([
            {"Field path": f["path"], "Type": f["type"], "Title": f["title"], "Description": f["description"], "Labels": _labels_for(f["path"])}
            for f in fields
        ])
        # A field can carry several labels (one descriptor's own xdm:labels
        # array can hold multiple codes, e.g. "custom/Restricted,
        # custom/Confidential") — st.dataframe's default auto-fit width
        # truncates that without an obvious way to tell more is there.
        # Widened explicitly rather than left to auto-fit.
        st.dataframe(
            table, use_container_width=True, hide_index=True, key="sdr_schema_fields_table",
            column_config={"Labels": st.column_config.TextColumn(width="large")},
        )
        st.download_button("Download as CSV", safe_csv(table), "aep_schema_fields.csv", "text/csv", key="sdr_fields_csv")
        if labels_entry["error"] is not None:
            st.warning(f"Couldn't fetch field labels: {labels_entry['error']}")
        elif any(labels_by_path.values()):
            st.caption(
                "Labels are data-governance/DULE labels (e.g. `core/I2` Identifiable, `core/S2` Sensitive, `core/C1` "
                "Contract data) applied via the Schema Registry's Descriptors API, matched to a field by its path — "
                "a field nested inside an array isn't confirmed to match correctly (see README Known Limitations)."
            )

    with st.expander("Raw schema response"):
        st.json(entry["raw"], expanded=False)

    if labels_entry is not None:
        with st.expander(f"Raw label descriptors ({len(labels_entry['descriptors'])} fetched for this sandbox)"):
            st.caption(
                "Every xdm:descriptorLabel descriptor Adobe returned for the active sandbox (not just this schema's) "
                "— compare `Path` here against `Field path` in the table above if a label you expect isn't showing "
                "up. Labels are sandbox-scoped: a descriptor recorded in a different sandbox than the one selected "
                "in the sidebar simply won't appear in this list at all — that looks identical to \"no labels "
                "configured\" from the app's side, so an empty list here with labels configured in Adobe's UI is "
                "the first thing to check against the sidebar's active sandbox."
            )
            if labels_entry["descriptors"]:
                debug_table = pd.DataFrame([
                    {"Path": d["path"], "Labels": ", ".join(d["labels"]) or "—", "Source schema (field group id)": d["source_schema"]}
                    for d in labels_entry["descriptors"]
                ])
                st.dataframe(debug_table, use_container_width=True, hide_index=True, key="sdr_raw_label_descriptors_table")
            else:
                st.caption("No label descriptors returned for this sandbox at all.")


def render() -> None:
    st.markdown("### SDR — Solution Design Reference (live)")
    st.caption(
        "An auto-generated reference of what's actually configured — CJA data view "
        "components and AEP schema fields, pulled live from Adobe rather than a "
        "hand-maintained document that drifts out of date. This does not diff "
        "against an existing SDR document; it's a starting point / living replacement for one."
    )
    _render_cja_section()
    st.divider()
    _render_aep_section()
