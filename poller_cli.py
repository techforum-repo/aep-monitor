#!/usr/bin/env python3
"""Run one poll cycle across AEP, Data Collection, and CJA and exit.

Intended for cron (or any scheduler) so history/trend charts and alerts keep
accumulating even when nobody has the Streamlit app open — the app and this
script both write to the same aep_monitor.db.

Example crontab entry (every 15 minutes):
    */15 * * * * cd /path/to/aep-monitor && ./.venv/bin/python poller_cli.py >> logs/poller_cron.log 2>&1
"""

from __future__ import annotations

import sys

from aep_monitor.config import harden_env_file
from aep_monitor.database import initialize
from aep_monitor.poller import refresh_all, refresh_entity_drift


def main() -> int:
    initialize()
    harden_env_file()
    try:
        results = refresh_all()
    except Exception as exc:  # noqa: BLE001 — top-level safety net; refresh_all() itself isolates each leg's own errors below, so this should only trip on a genuine bug in the orchestration itself
        print(f"Poll cycle failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"AEP flows: {len(results['aep'])}, DC properties: {len(results['dc'])}, CJA connections: {len(results['cja'])}, "
        f"segment jobs: {len(results['segments'])}, queries: {len(results['query_service'])}"
    )
    # Each leg isolates its own failure (see refresh_all()'s docstring) so
    # one broken product's fetch never costs every other product its
    # already-fetched data — but a failure still needs to surface here,
    # both for whoever reads cron's log and for the exit code cron
    # alerting typically watches.
    leg_errors = results.get("errors") or {}
    for name, exc in leg_errors.items():
        print(f"{name} leg failed: {exc}", file=sys.stderr)

    # Keeps "vs. last snapshot" drift baselines fresh for whatever entities
    # a Compare visit has already opted into tracking (see
    # refresh_entity_drift()'s docstring) — a separate try/except so a
    # drift-sweep failure never marks the whole cron run as failed when the
    # core AEP/DC/CJA/Quota poll above already succeeded.
    try:
        drift_counts = refresh_entity_drift()
        print(
            f"Drift sweep — schemas: {drift_counts['schema']}, datasets: {drift_counts['dataset']}, "
            f"DC properties: {drift_counts['dc_property']}, CJA data views: {drift_counts['cja_dataview']}"
        )
    except Exception as exc:  # noqa: BLE001 — same top-level CLI reasoning as above
        print(f"Drift sweep failed: {exc}", file=sys.stderr)

    # Non-zero whenever any leg failed, so cron-failure alerting (watching
    # this script's exit code) still catches a partial failure — even
    # though the poll cycle itself no longer aborts on one, per-leg errors
    # printed above still need to reach whoever/whatever is monitoring this.
    return 1 if leg_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
