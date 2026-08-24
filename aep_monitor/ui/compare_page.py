from __future__ import annotations

"""Compare — every side-by-side comparison Adobe doesn't provide a built-in
tool for, across four unrelated axes: AEP sandboxes, one schema's fields
across two sandboxes, two Data Collection properties, and two CJA data
views. Only the Sandboxes and Schemas tabs are actually about sandboxes —
Data Collection and CJA are org-wide in Adobe's architecture (see
data.py's fetch_sandbox_comparison docstring), so their tabs compare two
picked entities instead.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import data
from ..config import settings
from .shared import format_timestamp, refresh_button, render_friendly_error

_RED = "#d03b3b"
_DRIFT_MODE_OPTIONS = ["Another sandbox/entity", "Last snapshot (drift)"]


def _drift_mode_toggle(key: str) -> bool:
    """The "Compare against" radio every drift-capable tab (Schemas,
    Datasets, DC Properties, CJA Data Views) starts with. Returns True when
    "Last snapshot (drift)" is selected. A plain st.radio rather than a
    second-level st.tabs — this is a mode switch for the *same* comparison,
    not a separate view, and a radio keeps that framing clear."""
    mode = st.radio("Compare against", _DRIFT_MODE_OPTIONS, key=key, horizontal=True)
    return mode == _DRIFT_MODE_OPTIONS[1]


def _render_baseline_banner(has_baseline: bool, baseline_checked_at: str | None, entity_label: str) -> None:
    if not has_baseline:
        st.info(f"No prior snapshot for **{entity_label}** yet — this check just became the baseline for next time.")
    else:
        st.caption(f"Comparing against the snapshot taken {format_timestamp(baseline_checked_at)}.")


def _render_diff(diff: dict, label_a: str, label_b: str, detail_fields: list[tuple[str, str]]) -> None:
    """Generic renderer for one diffing.diff_by_key() result: a 4-metric
    summary row, then a table each for only-A, only-B, and changed common
    items (old vs. new value per changed field). `detail_fields` is
    `[(field_key, display_label), ...]` for the fields worth showing when
    a common item changed (e.g. a schema field's type/title/description)."""
    only_a, only_b, common = diff["only_a"], diff["only_b"], diff["common"]
    changed = [c for c in common if c["changed_fields"]]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Only in {label_a}", len(only_a))
    c2.metric(f"Only in {label_b}", len(only_b))
    c3.metric("Changed", len(changed))
    c4.metric("Unchanged", len(common) - len(changed))

    if not only_a and not only_b and not changed:
        st.success(f"🟢 No differences between {label_a} and {label_b}.")
        return

    if only_a:
        st.markdown(f"**Only in {label_a}**")
        st.dataframe(pd.DataFrame([{"Name": item.get("name") or item.get("path") or ""} for item in only_a]), use_container_width=True, hide_index=True)
    if only_b:
        st.markdown(f"**Only in {label_b}**")
        st.dataframe(pd.DataFrame([{"Name": item.get("name") or item.get("path") or ""} for item in only_b]), use_container_width=True, hide_index=True)
    if changed:
        st.markdown("**Changed**")
        rows = []
        for entry in changed:
            row: dict = {"Name": entry["key"]}
            for field_key, field_label in detail_fields:
                if field_key in entry["changed_fields"]:
                    row[f"{field_label} ({label_a})"] = entry["a"].get(field_key)
                    row[f"{field_label} ({label_b})"] = entry["b"].get(field_key)
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# --- Sandboxes (AEP) ---------------------------------------------------------------

def _do_refresh_sandboxes() -> None:
    try:
        st.session_state["compare_rows"] = data.fetch_sandbox_comparison()
        st.session_state["_compare_error"] = None
    except Exception as exc:
        st.session_state["_compare_error"] = exc


def _render_sandboxes_tab() -> None:
    st.caption(
        "AEP dataflow health and Observability Insights across every sandbox in `ADOBE_SANDBOXES` — the only "
        "one of the three products that's actually sandbox-scoped in Adobe's architecture."
    )

    if not settings.sandbox_list or len(settings.sandbox_list) < 2:
        st.info(
            "Only one sandbox is configured. Set `ADOBE_SANDBOXES` in `.env` to a comma-separated list "
            "(e.g. `prod,dev,stage`) to compare more than one."
        )
        if not settings.sandbox_list:
            return

    if refresh_button("Refresh all sandboxes", key="compare_refresh"):
        _do_refresh_sandboxes()
    if st.session_state.get("compare_rows") is None:
        _do_refresh_sandboxes()

    error = st.session_state.get("_compare_error")
    if error is not None:
        if render_friendly_error(error, key="compare_retry", context="Comparing sandboxes"):
            _do_refresh_sandboxes()
            st.rerun()
        return

    rows = st.session_state.get("compare_rows") or []
    if not rows:
        st.caption("No sandboxes configured.")
        return

    for row in rows:
        if row.get("error"):
            st.warning(f"**{row['sandbox']}**: {row['error']}")

    table = pd.DataFrame([
        {
            "Sandbox": r["sandbox"],
            "Flows": r["flow_count"],
            "Failing flows": r["failing_count"],
            "Records failed (latest run)": r["records_failed"],
            "Record success (24h)": r["recordsuccess"],
            "Batches failed (24h)": r["batchfailed"],
        }
        for r in rows if not r.get("error")
    ])
    if table.empty:
        st.caption("No successful sandbox fetches to show.")
        return
    st.dataframe(table, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        fig = go.Figure(go.Bar(x=table["Sandbox"], y=table["Failing flows"], marker_color=_RED))
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), title="Failing flows by sandbox", yaxis_title="Count")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig = go.Figure(go.Bar(x=table["Sandbox"], y=table["Batches failed (24h)"], marker_color=_RED))
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), title="Batches failed, last 24h", yaxis_title="Count")
        st.plotly_chart(fig, use_container_width=True)


# --- Schemas (AEP, across sandboxes) ------------------------------------------------

def _schema_list_for_sandbox(sandbox: str) -> dict:
    """Cached per-sandbox schema list — shared across both sides of the
    picker, since sandbox A and sandbox B are frequently the same sandbox
    (or a repeat from a previous comparison), and re-fetching the same
    sandbox's schema list twice per run would be wasted work."""
    cache = st.session_state.setdefault("compare_schema_list_cache", {})
    if sandbox not in cache:
        try:
            cache[sandbox] = {"schemas": data.fetch_schemas(sandbox=sandbox), "error": None}
        except Exception as exc:
            cache[sandbox] = {"schemas": [], "error": exc}
    return cache[sandbox]


def _render_schemas_tab() -> None:
    st.caption(
        "Any schema in sandbox A vs. any schema in sandbox B — usually the same schema across two sandboxes "
        "(catches drift like a field added in dev but not yet promoted to prod), but the two sides are picked "
        "independently, so comparing two genuinely different schemas works too."
    )

    sandboxes = settings.sandbox_list
    if not sandboxes:
        st.info("Set `ADOBE_SANDBOXES` in `.env` to compare schemas.")
        return

    drift_mode = _drift_mode_toggle("compare_schema_mode")

    if drift_mode:
        sandbox = st.selectbox("Sandbox", sandboxes, index=0, key="compare_schema_drift_sandbox")
        entry = _schema_list_for_sandbox(sandbox)
        if entry["error"] is not None:
            if render_friendly_error(entry["error"], key="compare_schema_drift_list_retry", context=f"Listing schemas in {sandbox}"):
                del st.session_state["compare_schema_list_cache"][sandbox]
                st.rerun()
            return
        titles = {s["title"]: s["schema_id"] for s in entry["schemas"]}
        if not titles:
            st.info(f"No schemas found in **{sandbox}**.")
            return
        schema_title = st.selectbox("Schema", list(titles.keys()), key="compare_schema_drift_title")
        schema_id = titles[schema_title]

        cache = st.session_state.setdefault("compare_schema_drift_cache", {})
        drift_key = f"{sandbox}::{schema_id}"
        if drift_key not in cache:
            with st.spinner("Checking for drift..."):
                try:
                    cache[drift_key] = {"result": data.fetch_schema_drift(schema_id, sandbox, schema_title), "error": None}
                except Exception as exc:
                    cache[drift_key] = {"result": None, "error": exc}
        drift_entry = cache[drift_key]
        if drift_entry["error"] is not None:
            if render_friendly_error(drift_entry["error"], key="compare_schema_drift_retry", context=f"Checking '{schema_title}' for drift"):
                del cache[drift_key]
                st.rerun()
            return

        result = drift_entry["result"]
        _render_baseline_banner(result["has_baseline"], result.get("baseline_checked_at"), schema_title)
        if result["has_baseline"]:
            _render_diff(result["diff"], "Previous snapshot", "Current", [("type", "Type"), ("title", "Title"), ("description", "Description")])
        return

    if len(sandboxes) < 2:
        st.info("Set `ADOBE_SANDBOXES` to at least two sandboxes in `.env` to compare schemas across them.")
        return

    col_a, col_b = st.columns(2)
    with col_a:
        sandbox_a = st.selectbox("Sandbox A", sandboxes, index=0, key="compare_schema_sandbox_a")
        entry_a = _schema_list_for_sandbox(sandbox_a)
        if entry_a["error"] is not None:
            if render_friendly_error(entry_a["error"], key="compare_schema_a_retry", context=f"Listing schemas in {sandbox_a}"):
                del st.session_state["compare_schema_list_cache"][sandbox_a]
                st.rerun()
            return
        titles_a = {s["title"]: s["schema_id"] for s in entry_a["schemas"]}
        if not titles_a:
            st.info(f"No schemas found in **{sandbox_a}**.")
            return
        schema_title_a = st.selectbox("Schema A", list(titles_a.keys()), key="compare_schema_title_a")

    with col_b:
        sandbox_b = st.selectbox("Sandbox B", sandboxes, index=min(1, len(sandboxes) - 1), key="compare_schema_sandbox_b")
        entry_b = _schema_list_for_sandbox(sandbox_b)
        if entry_b["error"] is not None:
            if render_friendly_error(entry_b["error"], key="compare_schema_b_retry", context=f"Listing schemas in {sandbox_b}"):
                del st.session_state["compare_schema_list_cache"][sandbox_b]
                st.rerun()
            return
        titles_b = {s["title"]: s["schema_id"] for s in entry_b["schemas"]}
        if not titles_b:
            st.info(f"No schemas found in **{sandbox_b}**.")
            return
        # Defaults to the same title as side A when it exists in this
        # sandbox too — the common case — without forcing it; any title
        # in this sandbox's own list remains selectable.
        default_index = list(titles_b.keys()).index(schema_title_a) if schema_title_a in titles_b else 0
        schema_title_b = st.selectbox("Schema B", list(titles_b.keys()), index=default_index, key="compare_schema_title_b")

    schema_id_a, schema_id_b = titles_a[schema_title_a], titles_b[schema_title_b]

    diff_cache = st.session_state.setdefault("compare_schema_diff_cache", {})
    diff_key = f"{sandbox_a}::{schema_id_a}::{sandbox_b}::{schema_id_b}"
    if diff_key not in diff_cache:
        with st.spinner("Comparing schema fields..."):
            try:
                diff_cache[diff_key] = {"result": data.fetch_schema_diff(schema_id_a, sandbox_a, schema_id_b, sandbox_b), "error": None}
            except Exception as exc:
                diff_cache[diff_key] = {"result": None, "error": exc}

    diff_entry = diff_cache[diff_key]
    if diff_entry["error"] is not None:
        if render_friendly_error(diff_entry["error"], key="compare_schema_diff_retry", context=f"Comparing '{schema_title_a}' vs. '{schema_title_b}'"):
            del diff_cache[diff_key]
            st.rerun()
        return

    if schema_title_a != schema_title_b:
        st.info(f"Comparing two different schemas: **{schema_title_a}** ({sandbox_a}) vs. **{schema_title_b}** ({sandbox_b}).")
    label_a, label_b = f"{schema_title_a} ({sandbox_a})", f"{schema_title_b} ({sandbox_b})"
    _render_diff(diff_entry["result"]["diff"], label_a, label_b, [("type", "Type"), ("title", "Title"), ("description", "Description")])


# --- Datasets (AEP, across sandboxes) -----------------------------------------------

def _dataset_list_for_sandbox(sandbox: str) -> dict:
    cache = st.session_state.setdefault("compare_dataset_list_cache", {})
    if sandbox not in cache:
        try:
            cache[sandbox] = {"datasets": data.fetch_datasets(sandbox=sandbox), "error": None}
        except Exception as exc:
            cache[sandbox] = {"datasets": [], "error": exc}
    return cache[sandbox]


def _format_dataset_value(field: str, value: object, schema_titles: dict[str, str]) -> str:
    # dataset_diff's/dataset_drift's rows mix string fields (name, schema id)
    # and boolean fields (profile/identity enabled) in the same "value_a"/
    # "value_b" slot — building the DataFrame column straight from that mix
    # crashes Streamlit's Arrow serialization (a column can't hold both str
    # and bool). Every value is coerced to display text before the table is
    # built, once, here, rather than leaving mixed types for pandas/Arrow to
    # choke on downstream. Shared by both the "another sandbox" and "last
    # snapshot" render paths.
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if field == "schema_id" and value:
        # Same "resolve id to a name for display" treatment as the
        # Datasets page — fall back to the id's last URL segment if the
        # title can't be resolved, rather than a full raw $id URL.
        return schema_titles.get(str(value), str(value).rsplit("/", 1)[-1])
    return str(value) if value else "—"


def _render_datasets_tab() -> None:
    st.caption(
        "Any dataset in sandbox A vs. any dataset in sandbox B — same independent-per-side pattern as Schemas: "
        "usually the same dataset across two sandboxes, but comparing two different ones works too. Compares "
        "name, description, schema binding, and Profile/Identity enablement — not creation/update timestamps, "
        "which differ on nearly every real comparison and aren't a meaningful configuration drift."
    )

    sandboxes = settings.sandbox_list
    if not sandboxes:
        st.info("Set `ADOBE_SANDBOXES` in `.env` to compare datasets.")
        return

    drift_mode = _drift_mode_toggle("compare_dataset_mode")

    if drift_mode:
        sandbox = st.selectbox("Sandbox", sandboxes, index=0, key="compare_dataset_drift_sandbox")
        entry = _dataset_list_for_sandbox(sandbox)
        if entry["error"] is not None:
            if render_friendly_error(entry["error"], key="compare_dataset_drift_list_retry", context=f"Listing datasets in {sandbox}"):
                del st.session_state["compare_dataset_list_cache"][sandbox]
                st.rerun()
            return
        names = {d["name"]: d["dataset_id"] for d in entry["datasets"]}
        if not names:
            st.info(f"No datasets found in **{sandbox}**.")
            return
        dataset_name = st.selectbox("Dataset", list(names.keys()), key="compare_dataset_drift_name")
        dataset_id = names[dataset_name]

        cache = st.session_state.setdefault("compare_dataset_drift_cache", {})
        drift_key = f"{sandbox}::{dataset_id}"
        if drift_key not in cache:
            cache[drift_key] = data.fetch_dataset_drift(dataset_id, sandbox, dataset_name)
        result = cache[drift_key]

        if not result["found"]:
            st.warning("Dataset couldn't be re-fetched — try refreshing.")
            return
        _render_baseline_banner(result["has_baseline"], result.get("baseline_checked_at"), dataset_name)
        if not result["has_baseline"]:
            return

        rows = result["rows"]
        changed_count = sum(1 for r in rows if r["changed"])
        if changed_count == 0:
            st.success("🟢 No differences.")

        schema_titles = {s["schema_id"]: s["title"] for s in _schema_list_for_sandbox(sandbox).get("schemas", [])}
        table = pd.DataFrame([
            {
                "Field": r["label"],
                "Previous snapshot": _format_dataset_value(r["field"], r["value_a"], schema_titles),
                "Current": _format_dataset_value(r["field"], r["value_b"], schema_titles),
                "Changed": "🔴 yes" if r["changed"] else "🟢 no",
            }
            for r in rows
        ])
        st.dataframe(table, use_container_width=True, hide_index=True)
        return

    if len(sandboxes) < 2:
        st.info("Set `ADOBE_SANDBOXES` to at least two sandboxes in `.env` to compare datasets across them.")
        return

    col_a, col_b = st.columns(2)
    with col_a:
        sandbox_a = st.selectbox("Sandbox A", sandboxes, index=0, key="compare_dataset_sandbox_a")
        entry_a = _dataset_list_for_sandbox(sandbox_a)
        if entry_a["error"] is not None:
            if render_friendly_error(entry_a["error"], key="compare_dataset_a_retry", context=f"Listing datasets in {sandbox_a}"):
                del st.session_state["compare_dataset_list_cache"][sandbox_a]
                st.rerun()
            return
        names_a = {d["name"]: d["dataset_id"] for d in entry_a["datasets"]}
        if not names_a:
            st.info(f"No datasets found in **{sandbox_a}**.")
            return
        dataset_name_a = st.selectbox("Dataset A", list(names_a.keys()), key="compare_dataset_name_a")

    with col_b:
        sandbox_b = st.selectbox("Sandbox B", sandboxes, index=min(1, len(sandboxes) - 1), key="compare_dataset_sandbox_b")
        entry_b = _dataset_list_for_sandbox(sandbox_b)
        if entry_b["error"] is not None:
            if render_friendly_error(entry_b["error"], key="compare_dataset_b_retry", context=f"Listing datasets in {sandbox_b}"):
                del st.session_state["compare_dataset_list_cache"][sandbox_b]
                st.rerun()
            return
        names_b = {d["name"]: d["dataset_id"] for d in entry_b["datasets"]}
        if not names_b:
            st.info(f"No datasets found in **{sandbox_b}**.")
            return
        default_index = list(names_b.keys()).index(dataset_name_a) if dataset_name_a in names_b else 0
        dataset_name_b = st.selectbox("Dataset B", list(names_b.keys()), index=default_index, key="compare_dataset_name_b")

    dataset_id_a, dataset_id_b = names_a[dataset_name_a], names_b[dataset_name_b]

    diff_cache = st.session_state.setdefault("compare_dataset_diff_cache", {})
    diff_key = f"{sandbox_a}::{dataset_id_a}::{sandbox_b}::{dataset_id_b}"
    if diff_key not in diff_cache:
        diff_cache[diff_key] = data.fetch_dataset_diff(dataset_id_a, sandbox_a, dataset_id_b, sandbox_b)
    result = diff_cache[diff_key]

    if not result["found_a"] or not result["found_b"]:
        st.warning("One or both datasets couldn't be re-fetched — try refreshing.")
        return
    if dataset_name_a != dataset_name_b:
        st.info(f"Comparing two different datasets: **{dataset_name_a}** ({sandbox_a}) vs. **{dataset_name_b}** ({sandbox_b}).")

    rows = result["rows"]
    changed_count = sum(1 for r in rows if r["changed"])
    if changed_count == 0:
        st.success("🟢 No differences.")

    # Reuses the Schemas tab's own per-sandbox schema-list cache (schema_id
    # -> title) rather than a separate fetch — the same list this tab's
    # "Schema" row needs is already fetched (or fetchable the same cached
    # way) whether or not the user has actually visited the Schemas tab.
    schema_titles_a = {s["schema_id"]: s["title"] for s in _schema_list_for_sandbox(sandbox_a).get("schemas", [])}
    schema_titles_b = {s["schema_id"]: s["title"] for s in _schema_list_for_sandbox(sandbox_b).get("schemas", [])}

    table = pd.DataFrame([
        {
            "Field": r["label"],
            f"Value ({sandbox_a})": _format_dataset_value(r["field"], r["value_a"], schema_titles_a),
            f"Value ({sandbox_b})": _format_dataset_value(r["field"], r["value_b"], schema_titles_b),
            "Changed": "🔴 yes" if r["changed"] else "🟢 no",
        }
        for r in rows
    ])
    st.dataframe(table, use_container_width=True, hide_index=True)

    # The row above only says the schema *binding* differs (by name/id) —
    # it doesn't say what's actually different about the two schemas'
    # fields. Reported live as "not showing field differences": a dataset
    # comparison that stops at "Schema: changed" without drilling into the
    # actual field-level diff leaves the real content of that change
    # invisible. Reuses fetch_schema_diff()/_render_diff() — the exact
    # same engine the Schemas tab uses — rather than inventing a second one.
    schema_row = next((r for r in rows if r["field"] == "schema_id"), None)
    schema_id_a, schema_id_b = (schema_row["value_a"], schema_row["value_b"]) if schema_row else (None, None)
    if schema_id_a and schema_id_b:
        st.markdown("**Schema field differences**")
        schema_diff_cache = st.session_state.setdefault("compare_dataset_schema_diff_cache", {})
        schema_diff_key = f"{sandbox_a}::{schema_id_a}::{sandbox_b}::{schema_id_b}"
        if schema_diff_key not in schema_diff_cache:
            with st.spinner("Comparing schema fields..."):
                try:
                    schema_diff_cache[schema_diff_key] = {"result": data.fetch_schema_diff(schema_id_a, sandbox_a, schema_id_b, sandbox_b), "error": None}
                except Exception as exc:
                    schema_diff_cache[schema_diff_key] = {"result": None, "error": exc}
        schema_diff_entry = schema_diff_cache[schema_diff_key]
        if schema_diff_entry["error"] is not None:
            render_friendly_error(schema_diff_entry["error"], key="compare_dataset_schema_diff_retry", context="Comparing the datasets' schema fields")
        else:
            label_a = schema_titles_a.get(schema_id_a, schema_id_a.rsplit("/", 1)[-1])
            label_b = schema_titles_b.get(schema_id_b, schema_id_b.rsplit("/", 1)[-1])
            _render_diff(schema_diff_entry["result"]["diff"], f"{label_a} ({sandbox_a})", f"{label_b} ({sandbox_b})", [("type", "Type"), ("title", "Title"), ("description", "Description")])
    elif schema_id_a or schema_id_b:
        st.caption("One of the two datasets has no schema binding — nothing to compare at the field level.")


# --- Data Collection properties -----------------------------------------------------

def _render_dc_tab() -> None:
    st.caption("Two Data Collection properties' extensions, rules, and libraries — catches drift like a dev property missing an extension prod already has.")

    if st.session_state.get("compare_dc_rows") is None:
        try:
            st.session_state["compare_dc_rows"] = data.fetch_dc()
            st.session_state["_compare_dc_error"] = None
        except Exception as exc:
            st.session_state["_compare_dc_error"] = exc

    error = st.session_state.get("_compare_dc_error")
    if error is not None:
        if render_friendly_error(error, key="compare_dc_retry", context="Fetching properties to compare"):
            st.session_state["compare_dc_rows"] = None
            st.rerun()
        return

    rows = st.session_state.get("compare_dc_rows") or []
    names_by_id = {r["property_id"]: r["property_name"] for r in rows}
    if not names_by_id:
        st.info("No Data Collection properties found.")
        return

    drift_mode = _drift_mode_toggle("compare_dc_mode")

    if drift_mode:
        ids = list(names_by_id.keys())
        property_id = st.selectbox("Property", ids, index=0, format_func=lambda pid: names_by_id[pid], key="compare_dc_drift_property")

        cache = st.session_state.setdefault("compare_dc_drift_cache", {})
        if property_id not in cache:
            cache[property_id] = data.fetch_dc_property_drift(property_id)
        result = cache[property_id]

        if not result["found"]:
            st.warning("Property couldn't be re-fetched — try refreshing.")
            return
        _render_baseline_banner(result["has_baseline"], result.get("baseline_checked_at"), names_by_id[property_id])
        if not result["has_baseline"]:
            return

        tab_ext, tab_rules, tab_libs, tab_envs, tab_data_elements = st.tabs(
            ["Extensions", "Rules", "Libraries", "Environments", "Data Elements"]
        )
        with tab_ext:
            _render_diff(result["extensions"], "Previous snapshot", "Current", [("review_status", "Review status"), ("published", "Published")])
        with tab_rules:
            _render_diff(result["rules"], "Previous snapshot", "Current", [("enabled", "Enabled"), ("published", "Published")])
        with tab_libs:
            _render_diff(result["libraries"], "Previous snapshot", "Current", [("state", "State")])
        with tab_envs:
            _render_diff(result["environments"], "Previous snapshot", "Current", [("status", "Status")])
        with tab_data_elements:
            _render_diff(result["data_elements"], "Previous snapshot", "Current", [("published", "Published"), ("dirty", "Dirty"), ("review_status", "Review status")])
        return

    if len(rows) < 2:
        st.info("Need at least two Data Collection properties to compare.")
        return

    ids = list(names_by_id.keys())
    col_a, col_b = st.columns(2)
    property_a = col_a.selectbox("Property A", ids, index=0, format_func=lambda pid: names_by_id[pid], key="compare_dc_property_a")
    property_b = col_b.selectbox("Property B", ids, index=min(1, len(ids) - 1), format_func=lambda pid: names_by_id[pid], key="compare_dc_property_b")

    cache = st.session_state.setdefault("compare_dc_diff_cache", {})
    diff_key = f"{property_a}::{property_b}"
    if diff_key not in cache:
        cache[diff_key] = data.fetch_dc_property_diff(property_a, property_b)
    result = cache[diff_key]

    tab_ext, tab_rules, tab_libs, tab_envs, tab_data_elements = st.tabs(
        ["Extensions", "Rules", "Libraries", "Environments", "Data Elements"]
    )
    with tab_ext:
        _render_diff(result["extensions"], names_by_id[property_a], names_by_id[property_b], [("review_status", "Review status"), ("published", "Published")])
    with tab_rules:
        _render_diff(result["rules"], names_by_id[property_a], names_by_id[property_b], [("enabled", "Enabled"), ("published", "Published")])
    with tab_libs:
        _render_diff(result["libraries"], names_by_id[property_a], names_by_id[property_b], [("state", "State")])
    with tab_envs:
        _render_diff(result["environments"], names_by_id[property_a], names_by_id[property_b], [("status", "Status")])
    with tab_data_elements:
        _render_diff(result["data_elements"], names_by_id[property_a], names_by_id[property_b], [("published", "Published"), ("dirty", "Dirty"), ("review_status", "Review status")])


# --- CJA data views ---------------------------------------------------------------

def _render_cja_tab() -> None:
    st.caption("Two CJA data views' dimensions and metrics — catches drift like a metric type that quietly diverged between two views meant to be similar.")

    if st.session_state.get("compare_cja_dataviews") is None:
        try:
            st.session_state["compare_cja_dataviews"] = data.fetch_cja_dataviews()
            st.session_state["_compare_cja_error"] = None
        except Exception as exc:
            st.session_state["_compare_cja_error"] = exc

    error = st.session_state.get("_compare_cja_error")
    if error is not None:
        if render_friendly_error(error, key="compare_cja_retry", context="Fetching data views to compare"):
            st.session_state["compare_cja_dataviews"] = None
            st.rerun()
        return

    dataviews = st.session_state.get("compare_cja_dataviews") or []
    names_by_id = {d["dataview_id"]: d["name"] for d in dataviews}
    if not names_by_id:
        st.info("No CJA data views found.")
        return

    drift_mode = _drift_mode_toggle("compare_cja_mode")

    if drift_mode:
        ids = list(names_by_id.keys())
        dataview_id = st.selectbox("Data view", ids, index=0, format_func=lambda did: names_by_id[did], key="compare_cja_drift_dataview")

        cache = st.session_state.setdefault("compare_cja_drift_cache", {})
        if dataview_id not in cache:
            cache[dataview_id] = data.fetch_cja_dataview_drift(dataview_id, names_by_id[dataview_id])
        result = cache[dataview_id]

        _render_baseline_banner(result["has_baseline"], result.get("baseline_checked_at"), names_by_id[dataview_id])
        if not result["has_baseline"]:
            return

        tab_dims, tab_metrics, tab_calc_metrics = st.tabs(["Dimensions", "Metrics", "Calculated Metrics"])
        with tab_dims:
            _render_diff(result["dimensions"], "Previous snapshot", "Current", [("type", "Type"), ("approved", "Approved")])
        with tab_metrics:
            _render_diff(result["metrics"], "Previous snapshot", "Current", [("type", "Type"), ("approved", "Approved")])
        with tab_calc_metrics:
            _render_diff(result["calculated_metrics"], "Previous snapshot", "Current", [("type", "Type"), ("polarity", "Polarity")])
        return

    if len(dataviews) < 2:
        st.info("Need at least two CJA data views to compare.")
        return

    ids = list(names_by_id.keys())
    col_a, col_b = st.columns(2)
    dataview_a = col_a.selectbox("Data view A", ids, index=0, format_func=lambda did: names_by_id[did], key="compare_cja_dataview_a")
    dataview_b = col_b.selectbox("Data view B", ids, index=min(1, len(ids) - 1), format_func=lambda did: names_by_id[did], key="compare_cja_dataview_b")

    cache = st.session_state.setdefault("compare_cja_diff_cache", {})
    diff_key = f"{dataview_a}::{dataview_b}"
    if diff_key not in cache:
        cache[diff_key] = data.fetch_cja_dataview_diff(dataview_a, dataview_b)
    result = cache[diff_key]

    tab_dims, tab_metrics, tab_calc_metrics = st.tabs(["Dimensions", "Metrics", "Calculated Metrics"])
    with tab_dims:
        _render_diff(result["dimensions"], names_by_id[dataview_a], names_by_id[dataview_b], [("type", "Type"), ("approved", "Approved")])
    with tab_metrics:
        _render_diff(result["metrics"], names_by_id[dataview_a], names_by_id[dataview_b], [("type", "Type"), ("approved", "Approved")])
    with tab_calc_metrics:
        _render_diff(result["calculated_metrics"], names_by_id[dataview_a], names_by_id[dataview_b], [("type", "Type"), ("polarity", "Polarity")])


def render() -> None:
    st.markdown("### Compare")
    st.caption(
        "Side-by-side comparisons Adobe doesn't provide a built-in tool for. Sandboxes, Schemas, and Datasets "
        "are actual sandbox comparisons; Data Collection and CJA are org-wide in Adobe's architecture, so those "
        "two compare two picked entities instead."
    )
    tab_sandboxes, tab_schemas, tab_datasets, tab_dc, tab_cja = st.tabs(
        ["Sandboxes", "Schemas", "Datasets", "DC Properties", "CJA Data Views"]
    )
    with tab_sandboxes:
        _render_sandboxes_tab()
    with tab_schemas:
        _render_schemas_tab()
    with tab_datasets:
        _render_datasets_tab()
    with tab_dc:
        _render_dc_tab()
    with tab_cja:
        _render_cja_tab()
