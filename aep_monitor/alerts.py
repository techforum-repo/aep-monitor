from __future__ import annotations

"""Turns each product's latest fetched rows into open/resolved alerts, and
optionally pushes new (not re-notified) alerts to Slack.

Each evaluate_*() call is idempotent: it upserts (dedupes by fingerprint) the
alerts that should be open right now, then resolves any previously-open
alert for that source whose condition cleared. Call it after every
data.fetch_*() so the Alerts page and the Overview banner always reflect the
most recent poll.
"""

from datetime import datetime, timezone
from typing import Any

import httpx

from . import database
from .config import settings
from .logging_setup import get_logger

# Sources evaluate_freshness() checks on every call — every product this app
# polls into its own history table (see database.latest_checked_at()). Kept
# as one shared list (not per-caller) so a partial call can never
# accidentally auto-resolve a "Monitor" alert for a source it forgot to
# check — see evaluate_freshness()'s own docstring for why that matters.
FRESHNESS_SOURCES = ["AEP", "Data Collection", "CJA", "Quota", "Segments", "Query Service"]


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
            connector = row.get("connector_name")
            message = f"Status: {latest.get('status')}. Records in={latest.get('records_in')}, failed={failed_records}."
            if connector:
                message += f" Connector: {connector} (this may be an outbound activation flow, not ingestion — see AEP Ingestion page)."
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


def _quota_trend_days_to_full(quota_name: str) -> float | None:
    """Days until `quota_name` is projected to hit 100% at its own recent
    linear rate of change, from quota_snapshots history — or None if there's
    not enough history yet (fewer than 2 snapshots, or they all landed at
    the same instant) to compute a rate, or the trend is flat/improving
    (never gets there, however slowly, so no projection is meaningful)."""
    history = database.read_quota_history(quota_name=quota_name, limit=30)
    if len(history) < 2:
        return None
    history = history.sort_values("checked_at")
    first, last = history.iloc[0], history.iloc[-1]
    elapsed_days = (datetime.fromisoformat(str(last["checked_at"])) - datetime.fromisoformat(str(first["checked_at"]))).total_seconds() / 86400
    if elapsed_days <= 0:
        return None
    rate_per_day = (float(last["pct_used"]) - float(first["pct_used"])) / elapsed_days
    if rate_per_day <= 0:
        return None
    return (100 - float(last["pct_used"])) / rate_per_day


def evaluate_quota(rows: list[dict[str, Any]]) -> None:
    """Two distinct conditions, both scoped to source="Quota" and unioned
    into one active set before a single auto_resolve_missing() call — a
    second, separate evaluate_*() function for the trend alert would call
    auto_resolve_missing("Quota", ...) with only its own fingerprints in
    scope, incorrectly clearing the other's alerts every time only one of
    the two runs (they're both driven by the same refresh_quota() call today,
    but coupling that as an unstated assumption is exactly the kind of thing
    that breaks quietly later)."""
    active: set[str] = set()
    for row in rows:
        if row["is_high"]:
            fingerprint = f"quota:{row['name']}"
            active.add(fingerprint)
            title = f"Quota — {row['name']} at {row['pct_used']:.0f}% ({row['consumed']:.0f}/{row['quota']:.0f})"
            if database.upsert_alert("Quota", "warning", title, row["description"], fingerprint):
                _notify_slack(title, row["description"])
            continue  # already alerting on the crossed threshold — a trend alert on top would be noise.

        if settings.alert_quota_trend_days <= 0:
            continue
        days_to_full = _quota_trend_days_to_full(row["name"])
        if days_to_full is not None and 0 <= days_to_full <= settings.alert_quota_trend_days:
            fingerprint = f"quota-trend:{row['name']}"
            active.add(fingerprint)
            title = f"Quota — {row['name']} projected to reach 100% in ~{days_to_full:.0f}d at its current rate"
            message = f"Currently {row['pct_used']:.0f}% used ({row['consumed']:.0f}/{row['quota']:.0f}). {row['description']}".strip()
            if database.upsert_alert("Quota", "warning", title, message, fingerprint):
                _notify_slack(title, message)
    database.auto_resolve_missing("Quota", active)


def evaluate_segments(rows: list[dict[str, Any]]) -> None:
    """A failed segment job is very often the real upstream cause of "the
    audience never reached the destination" — see data.fetch_segment_jobs()'s
    docstring and aep.py's parse_flow() docstring on why activation flows
    alone can't be trusted to surface this."""
    active: set[str] = set()
    for row in rows:
        if row["is_bad"]:
            fingerprint = f"segment-job:{row['job_id']}"
            active.add(fingerprint)
            title = f"Segments — job for \"{row['segment_name']}\" {row['status']}"
            if database.upsert_alert("Segments", "critical", title, "", fingerprint):
                _notify_slack(title, f"Segment: {row['segment_name']}")
    database.auto_resolve_missing("Segments", active)


def evaluate_query_service(rows: list[dict[str, Any]]) -> None:
    active: set[str] = set()
    for row in rows:
        if row["is_bad"]:
            fingerprint = f"query:{row['query_id']}"
            active.add(fingerprint)
            title = f"Query Service — \"{row['name']}\" {row['state']}"
            if database.upsert_alert("Query Service", "warning", title, row.get("error_message", ""), fingerprint):
                _notify_slack(title, row.get("error_message", ""))
    database.auto_resolve_missing("Query Service", active)


def evaluate_freshness(now: datetime | None = None) -> None:
    """Dead-man's-switch: alerts when a source's last recorded snapshot is
    older than settings.alert_stale_after_hours — independent of whether the
    poller that would normally refresh it is even still running.

    This deliberately can't live inside refresh_all()/poller_cli.py: if the
    scheduled poller itself has died, code that only runs *as part of*
    polling never executes either, so it could never notice its own
    silence. It has to be evaluated on a read path instead — see
    ui/overview.py, which calls this on every page render, so the dashboard
    self-diagnoses "have I gone quiet?" the next time a human actually looks
    at it, rather than keeping quietly stale forever.

    A source with no snapshot at all yet (fresh install, never polled) is
    skipped, not flagged — this alert is for "went quiet after working",
    not "hasn't started yet"."""
    now = now or datetime.now(timezone.utc)
    active: set[str] = set()
    for source in FRESHNESS_SOURCES:
        checked_at = database.latest_checked_at(source)
        if not checked_at:
            continue
        try:
            checked_dt = datetime.fromisoformat(checked_at)
        except ValueError:
            continue
        if checked_dt.tzinfo is None:
            checked_dt = checked_dt.replace(tzinfo=timezone.utc)
        age_hours = (now - checked_dt).total_seconds() / 3600
        if age_hours > settings.alert_stale_after_hours:
            fingerprint = f"stale:{source}"
            active.add(fingerprint)
            title = f"{source} — no new data in {age_hours:.1f}h (expected within {settings.alert_stale_after_hours:.0f}h)"
            message = f"Last successful check: {checked_at}. The scheduled poller (poller_cli.py via cron) may have stopped running, or its credential may be failing."
            if database.upsert_alert("Monitor", "warning", title, message, fingerprint):
                _notify_slack(title, message)
    database.auto_resolve_missing("Monitor", active)
