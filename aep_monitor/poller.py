from __future__ import annotations

"""Orchestrates one refresh cycle per product: fetch -> record a history
snapshot -> evaluate alerts -> return the parsed rows. Used by every UI
page's "Refresh now" button, and importable standalone for a cron-driven
background poller (see poller_cli.py / README "Continuous background
polling") so history/alerts keep accumulating even with the app closed.
"""

from typing import Any

from . import alerts, data, database
from .logging_setup import get_logger


def refresh_aep(sandbox: str | None = None) -> list[dict[str, Any]]:
    rows = data.fetch_aep(sandbox=sandbox)
    snapshot_rows = [
        {
            "flow_id": r["flow_id"],
            "flow_name": r["flow_name"],
            "status": (r.get("latest_run") or {}).get("status", ""),
            "records_in": (r.get("latest_run") or {}).get("records_in"),
            "records_out": (r.get("latest_run") or {}).get("records_out"),
            "records_failed": (r.get("latest_run") or {}).get("records_failed"),
        }
        for r in rows
    ]
    if snapshot_rows:
        database.record_aep_snapshots(snapshot_rows)
    alerts.evaluate_aep(rows)
    get_logger().info("AEP refresh: %d flows", len(rows))
    return rows


def refresh_dc() -> list[dict[str, Any]]:
    rows = data.fetch_dc()
    snapshot_rows = [
        {
            "property_id": r["property_id"],
            "property_name": r["property_name"],
            "extension_count": r["extension_count"],
            "extension_issue_count": r["extension_issue_count"],
            "rule_count": r["rule_count"],
            "library_count": r["library_count"],
            "library_issue_count": r["library_issue_count"],
        }
        for r in rows
    ]
    if snapshot_rows:
        database.record_dc_snapshots(snapshot_rows)
    alerts.evaluate_dc(rows)
    get_logger().info("Data Collection refresh: %d properties", len(rows))
    return rows


def refresh_cja() -> list[dict[str, Any]]:
    rows = data.fetch_cja_connections()
    if rows:
        database.record_cja_snapshots(rows)
    alerts.evaluate_cja(rows)
    get_logger().info("CJA refresh: %d connections", len(rows))
    return rows


def refresh_quota() -> list[dict[str, Any]]:
    rows = data.fetch_quotas()
    if rows:
        database.record_quota_snapshots(rows)
    alerts.evaluate_quota(rows)
    get_logger().info("Quota refresh: %d quotas", len(rows))
    return rows


def refresh_segments(sandbox: str | None = None) -> list[dict[str, Any]]:
    rows = data.fetch_segment_jobs(sandbox=sandbox)
    if rows:
        database.record_segment_job_snapshots(rows)
    alerts.evaluate_segments(rows)
    get_logger().info("Segments refresh: %d jobs", len(rows))
    return rows


def refresh_query_service(sandbox: str | None = None) -> list[dict[str, Any]]:
    rows = data.fetch_queries(sandbox=sandbox)
    if rows:
        database.record_query_snapshots(rows)
    alerts.evaluate_query_service(rows)
    get_logger().info("Query Service refresh: %d queries", len(rows))
    return rows


def refresh_all(sandbox: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Used by poller_cli.py (cron) and the Overview page's single "Refresh
    everything" button. `sandbox` affects every leg that's actually
    sandbox-scoped in Adobe's architecture (AEP, Segments, Query Service) —
    Data Collection, CJA, and Quota are org-wide (see
    fetch_sandbox_comparison's docstring in data.py)."""
    return {
        "aep": refresh_aep(sandbox=sandbox),
        "dc": refresh_dc(),
        "cja": refresh_cja(),
        "quota": refresh_quota(),
        "segments": refresh_segments(sandbox=sandbox),
        "query_service": refresh_query_service(sandbox=sandbox),
    }


def refresh_entity_drift() -> dict[str, int]:
    """Re-snapshots every entity that's ever had a "vs. last snapshot"
    drift baseline established via Compare (see database.list_known_entity_keys()
    and each fetch_*_drift()'s docstring in data.py). Deliberately NOT part
    of refresh_all() — the Overview page's "Refresh everything" button calls
    refresh_all() directly and must not silently start writing drift
    snapshots as a side effect of an unrelated click; only poller_cli.py
    (cron) calls this, so drift baselines only advance on a schedule you
    explicitly set up, on top of whichever entities a UI visit has already
    opted into tracking. An entity nobody has ever drift-checked isn't swept
    here — there's no prior baseline for a scheduled run to build history
    from; only a UI visit's first fetch_*_drift() call can originate one.
    One entity failing (e.g. deleted since its last snapshot) is logged and
    skipped rather than aborting the rest of the sweep."""
    counts: dict[str, int] = {}

    schema_keys = database.list_known_entity_keys("schema")
    for known in schema_keys:
        sandbox, _, schema_id = known["entity_key"].partition("::")
        try:
            data.fetch_schema_drift(schema_id, sandbox, known["entity_label"])
        except Exception:
            get_logger().warning("Schema drift sweep failed for %s", known["entity_key"], exc_info=True)
    counts["schema"] = len(schema_keys)

    dataset_keys = database.list_known_entity_keys("dataset")
    for known in dataset_keys:
        sandbox, _, dataset_id = known["entity_key"].partition("::")
        try:
            data.fetch_dataset_drift(dataset_id, sandbox, known["entity_label"])
        except Exception:
            get_logger().warning("Dataset drift sweep failed for %s", known["entity_key"], exc_info=True)
    counts["dataset"] = len(dataset_keys)

    dc_keys = database.list_known_entity_keys("dc_property")
    for known in dc_keys:
        try:
            data.fetch_dc_property_drift(known["entity_key"])
        except Exception:
            get_logger().warning("DC property drift sweep failed for %s", known["entity_key"], exc_info=True)
    counts["dc_property"] = len(dc_keys)

    cja_keys = database.list_known_entity_keys("cja_dataview")
    for known in cja_keys:
        try:
            data.fetch_cja_dataview_drift(known["entity_key"], known["entity_label"])
        except Exception:
            get_logger().warning("CJA data view drift sweep failed for %s", known["entity_key"], exc_info=True)
    counts["cja_dataview"] = len(cja_keys)

    get_logger().info(
        "Drift sweep: %d schemas, %d datasets, %d DC properties, %d CJA data views",
        counts["schema"], counts["dataset"], counts["dc_property"], counts["cja_dataview"],
    )
    return counts
