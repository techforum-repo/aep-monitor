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
    except Exception as exc:  # noqa: BLE001 — this is the top-level CLI entry point
        print(f"Poll cycle failed: {exc}", file=sys.stderr)
        return 1
    print(f"AEP flows: {len(results['aep'])}, DC properties: {len(results['dc'])}, CJA connections: {len(results['cja'])}")

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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
