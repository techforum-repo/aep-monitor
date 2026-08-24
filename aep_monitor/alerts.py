from __future__ import annotations

"""Turns each product's latest fetched rows into open/resolved alerts, and
optionally pushes new (not re-notified) alerts to Slack.

Each evaluate_*() call is idempotent: it upserts (dedupes by fingerprint) the
alerts that should be open right now, then resolves any previously-open
alert for that source whose condition cleared. Call it after every
data.fetch_*() so the Alerts page and the Overview banner always reflect the
most recent poll.
"""

from typing import Any

import httpx

from . import database
from .config import settings
from .logging_setup import get_logger


def _notify_slack(title: str, message: str) -> None:
    if not settings.slack_webhook_url:
        return
    try:
        httpx.post(settings.slack_webhook_url, json={"text": f"*{title}*\n{message}"}, timeout=10)
    except httpx.HTTPError as exc:
        get_logger().warning("Slack notification failed: %s", exc)


def evaluate_aep(rows: list[dict[str, Any]]) -> None:
    active: set[str] = set()
    for row in rows:
        latest = row.get("latest_run") or {}
        if not latest:
            continue
        failed_records = int(latest.get("records_failed") or 0)
        is_failed_status = latest.get("status") in {"failed", "error"}
        if is_failed_status or failed_records > settings.alert_failed_records_threshold:
            fingerprint = f"aep:{row['flow_id']}:latest_run"
            active.add(fingerprint)
            title = f"AEP — {row['flow_name']}: latest run {'failed' if is_failed_status else 'has failed records'}"
            message = f"Status: {latest.get('status')}. Records in={latest.get('records_in')}, failed={failed_records}."
            if database.upsert_alert("AEP", "critical", title, message, fingerprint):
                _notify_slack(title, message)
    database.auto_resolve_missing("AEP", active)


def evaluate_dc(rows: list[dict[str, Any]]) -> None:
    active: set[str] = set()
    for row in rows:
        for ext in row.get("extensions", []):
            if ext["has_issue"]:
                fingerprint = f"dc:{row['property_id']}:extension:{ext['extension_id']}"
                active.add(fingerprint)
                title = f"Data Collection — {row['property_name']}: extension \"{ext['name']}\" {ext['review_status']}"
                if database.upsert_alert("Data Collection", "warning", title, "", fingerprint):
                    _notify_slack(title, f"Property: {row['property_name']}")
        for lib in row.get("libraries", []):
            if lib["is_bad"]:
                fingerprint = f"dc:{row['property_id']}:library:{lib['library_id']}"
                active.add(fingerprint)
                title = f"Data Collection — {row['property_name']}: library \"{lib['name']}\" build {lib['state']}"
                if database.upsert_alert("Data Collection", "critical", title, "", fingerprint):
                    _notify_slack(title, f"Property: {row['property_name']}")
        for env in row.get("environments", []):
            if env["stage"] == "production" and env["is_bad"]:
                fingerprint = f"dc:{row['property_id']}:environment:{env['environment_id']}"
                active.add(fingerprint)
                title = f"Data Collection — {row['property_name']}: PRODUCTION environment build {env['status']}"
                if database.upsert_alert("Data Collection", "critical", title, "", fingerprint):
                    _notify_slack(title, f"Property: {row['property_name']}")
    database.auto_resolve_missing("Data Collection", active)


def evaluate_cja(rows: list[dict[str, Any]]) -> None:
    active: set[str] = set()
    for row in rows:
        if row["has_issue"]:
            fingerprint = f"cja:{row['connection_id']}"
            active.add(fingerprint)
            title = f"CJA — connection \"{row['name']}\" status: {row['status']}"
            if database.upsert_alert("CJA", "critical", title, "", fingerprint):
                _notify_slack(title, f"Connection: {row['name']}")
    database.auto_resolve_missing("CJA", active)


def evaluate_quota(rows: list[dict[str, Any]]) -> None:
    active: set[str] = set()
    for row in rows:
        if row["is_high"]:
            fingerprint = f"quota:{row['name']}"
            active.add(fingerprint)
            title = f"Quota — {row['name']} at {row['pct_used']:.0f}% ({row['consumed']:.0f}/{row['quota']:.0f})"
            if database.upsert_alert("Quota", "warning", title, row["description"], fingerprint):
                _notify_slack(title, row["description"])
    database.auto_resolve_missing("Quota", active)
