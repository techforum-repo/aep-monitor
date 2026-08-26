from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aep_monitor import alerts, database


def test_evaluate_aep_flags_a_failed_run(temp_db):
    rows = [{"flow_id": "f1", "flow_name": "Flow 1", "latest_run": {"status": "failed", "records_failed": 0}}]
    alerts.evaluate_aep(rows)
    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert open_alerts.iloc[0]["source"] == "AEP"


def test_evaluate_aep_flags_a_success_status_run_with_failed_records_above_threshold(temp_db):
    """Regression: the code-review-caught case where the Compare page's own
    failing-flow count didn't match this — a run can report status=success
    while still having failed records (a partial failure), and that must
    still alert."""
    rows = [{"flow_id": "f1", "flow_name": "Flow 1", "latest_run": {"status": "success", "records_failed": 120}}]
    alerts.evaluate_aep(rows)
    assert len(database.list_alerts(resolved=False)) == 1


def test_evaluate_aep_does_not_flag_a_healthy_run(temp_db):
    rows = [{"flow_id": "f1", "flow_name": "Flow 1", "latest_run": {"status": "success", "records_failed": 0}}]
    alerts.evaluate_aep(rows)
    assert database.list_alerts(resolved=False).empty


def test_evaluate_aep_skips_flows_with_no_runs_yet(temp_db):
    rows = [{"flow_id": "f1", "flow_name": "Flow 1", "latest_run": {}}]
    alerts.evaluate_aep(rows)
    assert database.list_alerts(resolved=False).empty


def test_evaluate_aep_auto_resolves_once_the_flow_recovers(temp_db):
    failing = [{"flow_id": "f1", "flow_name": "Flow 1", "latest_run": {"status": "failed", "records_failed": 0}}]
    alerts.evaluate_aep(failing)
    assert len(database.list_alerts(resolved=False)) == 1

    healthy = [{"flow_id": "f1", "flow_name": "Flow 1", "latest_run": {"status": "success", "records_failed": 0}}]
    alerts.evaluate_aep(healthy)
    assert database.list_alerts(resolved=False).empty
    assert len(database.list_alerts(resolved=True)) == 1


def test_evaluate_dc_flags_every_bad_library_not_just_the_first(temp_db):
    """Regression: the earlier "last library = libraries[0]" bug (fixed
    before this test suite existed) silently missed a failed build sitting
    anywhere but the first slot. This pins the fix: every bad-state library
    in the list must produce its own alert, regardless of position."""
    rows = [{
        "property_id": "p1", "property_name": "Web",
        "extensions": [],
        "libraries": [
            {"library_id": "l1", "name": "Production", "state": "published", "is_bad": False},
            {"library_id": "l2", "name": "Staging", "state": "failed", "is_bad": True},
        ],
    }]
    alerts.evaluate_dc(rows)
    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert "Staging" in open_alerts.iloc[0]["title"]


def test_evaluate_dc_flags_a_rejected_extension_as_a_warning(temp_db):
    rows = [{
        "property_id": "p1", "property_name": "Web",
        "extensions": [{"extension_id": "e1", "name": "Custom", "review_status": "rejected", "has_issue": True}],
        "libraries": [],
    }]
    alerts.evaluate_dc(rows)
    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert open_alerts.iloc[0]["severity"] == "warning"


def test_evaluate_dc_flags_a_failed_production_environment_as_critical(temp_db):
    rows = [{
        "property_id": "p1", "property_name": "Web",
        "extensions": [], "libraries": [],
        "environments": [
            {"environment_id": "en1", "name": "Production", "stage": "production", "status": "failed", "is_bad": True},
        ],
    }]
    alerts.evaluate_dc(rows)
    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert open_alerts.iloc[0]["severity"] == "critical"
    assert "PRODUCTION" in open_alerts.iloc[0]["title"]


def test_evaluate_dc_does_not_flag_a_failed_non_production_environment(temp_db):
    """A failed development/staging build shouldn't page anyone the same
    way a failed production build does — the alert is specifically scoped
    to stage == "production"."""
    rows = [{
        "property_id": "p1", "property_name": "Web",
        "extensions": [], "libraries": [],
        "environments": [
            {"environment_id": "en1", "name": "Development", "stage": "development", "status": "failed", "is_bad": True},
        ],
    }]
    alerts.evaluate_dc(rows)
    assert database.list_alerts(resolved=False).empty


def test_evaluate_cja_flags_an_unhealthy_connection(temp_db):
    rows = [{"connection_id": "c1", "name": "CRM", "status": "error", "has_issue": True}]
    alerts.evaluate_cja(rows)
    assert len(database.list_alerts(resolved=False)) == 1


def test_evaluate_quota_flags_a_quota_at_or_above_the_threshold(temp_db):
    rows = [{"name": "dailyConsumerDeleteIdentitiesQuota", "description": "x", "consumed": 92, "quota": 100, "pct_used": 92.0, "is_high": True}]
    alerts.evaluate_quota(rows)
    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert open_alerts.iloc[0]["source"] == "Quota"


def test_evaluate_quota_does_not_flag_a_quota_under_the_threshold(temp_db):
    rows = [{"name": "x", "description": "x", "consumed": 10, "quota": 100, "pct_used": 10.0, "is_high": False}]
    alerts.evaluate_quota(rows)
    assert database.list_alerts(resolved=False).empty


def test_repeated_evaluation_of_the_same_condition_does_not_duplicate_alerts(temp_db):
    rows = [{"flow_id": "f1", "flow_name": "Flow 1", "latest_run": {"status": "failed", "records_failed": 0}}]
    alerts.evaluate_aep(rows)
    alerts.evaluate_aep(rows)
    alerts.evaluate_aep(rows)
    assert len(database.list_alerts(resolved=False)) == 1


def test_evaluate_quota_trend_flags_a_quota_projected_to_cross_soon(temp_db, monkeypatch):
    # 50% -> 70% over 2 days = 10 pts/day -> 3 days to 100%, well inside the default 14-day trend window.
    monkeypatch.setattr(database, "_now", lambda: (datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    database.record_quota_snapshots([{"name": "q1", "consumed": 50, "quota": 100, "pct_used": 50.0}])
    monkeypatch.setattr(database, "_now", lambda: datetime.now(timezone.utc).isoformat())
    database.record_quota_snapshots([{"name": "q1", "consumed": 70, "quota": 100, "pct_used": 70.0}])

    rows = [{"name": "q1", "description": "x", "consumed": 70, "quota": 100, "pct_used": 70.0, "is_high": False}]
    alerts.evaluate_quota(rows)

    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert "projected" in open_alerts.iloc[0]["title"]


def test_evaluate_quota_trend_does_not_flag_a_flat_quota(temp_db, monkeypatch):
    monkeypatch.setattr(database, "_now", lambda: (datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    database.record_quota_snapshots([{"name": "q1", "consumed": 50, "quota": 100, "pct_used": 50.0}])
    monkeypatch.setattr(database, "_now", lambda: datetime.now(timezone.utc).isoformat())
    database.record_quota_snapshots([{"name": "q1", "consumed": 50, "quota": 100, "pct_used": 50.0}])

    rows = [{"name": "q1", "description": "x", "consumed": 50, "quota": 100, "pct_used": 50.0, "is_high": False}]
    alerts.evaluate_quota(rows)
    assert database.list_alerts(resolved=False).empty


def test_evaluate_quota_trend_is_suppressed_when_already_over_threshold(temp_db, monkeypatch):
    """A quota that's already crossed the plain threshold gets exactly one
    alert, not both — the trend alert would be pure noise on top of it."""
    monkeypatch.setattr(database, "_now", lambda: (datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    database.record_quota_snapshots([{"name": "q1", "consumed": 85, "quota": 100, "pct_used": 85.0}])
    monkeypatch.setattr(database, "_now", lambda: datetime.now(timezone.utc).isoformat())
    database.record_quota_snapshots([{"name": "q1", "consumed": 92, "quota": 100, "pct_used": 92.0}])

    rows = [{"name": "q1", "description": "x", "consumed": 92, "quota": 100, "pct_used": 92.0, "is_high": True}]
    alerts.evaluate_quota(rows)

    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert "projected" not in open_alerts.iloc[0]["title"]


def test_evaluate_quota_trend_needs_at_least_two_snapshots(temp_db):
    database.record_quota_snapshots([{"name": "q1", "consumed": 90, "quota": 100, "pct_used": 90.0}])
    rows = [{"name": "q1", "description": "x", "consumed": 90, "quota": 100, "pct_used": 90.0, "is_high": False}]
    alerts.evaluate_quota(rows)
    assert database.list_alerts(resolved=False).empty


def test_evaluate_freshness_skips_a_source_with_no_snapshot_yet(temp_db):
    """Fresh install, nothing ever polled — not "stale", just not started."""
    alerts.evaluate_freshness()
    assert database.list_alerts(resolved=False).empty


def test_evaluate_freshness_does_not_flag_a_fresh_source(temp_db):
    database.record_aep_snapshots([{"flow_id": "f1", "flow_name": "x", "status": "success", "records_in": 1, "records_out": 1, "records_failed": 0}])
    alerts.evaluate_freshness()
    assert database.list_alerts(resolved=False).empty


def test_evaluate_freshness_flags_a_source_that_has_gone_quiet(temp_db, monkeypatch):
    monkeypatch.setattr(database, "_now", lambda: (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat())
    database.record_aep_snapshots([{"flow_id": "f1", "flow_name": "x", "status": "success", "records_in": 1, "records_out": 1, "records_failed": 0}])

    alerts.evaluate_freshness()

    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert open_alerts.iloc[0]["source"] == "Monitor"


def test_evaluate_freshness_auto_resolves_once_a_source_is_fresh_again(temp_db, monkeypatch):
    # Not monkeypatch.undo() — that would also revert the temp_db fixture's
    # own DB_PATH patch (same monkeypatch instance, undo() reverts every
    # patch made through it, not just this test body's).
    monkeypatch.setattr(database, "_now", lambda: (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat())
    database.record_aep_snapshots([{"flow_id": "f1", "flow_name": "x", "status": "success", "records_in": 1, "records_out": 1, "records_failed": 0}])
    alerts.evaluate_freshness()
    assert len(database.list_alerts(resolved=False)) == 1

    monkeypatch.setattr(database, "_now", lambda: datetime.now(timezone.utc).isoformat())
    database.record_aep_snapshots([{"flow_id": "f1", "flow_name": "x", "status": "success", "records_in": 1, "records_out": 1, "records_failed": 0}])
    alerts.evaluate_freshness()
    assert database.list_alerts(resolved=False).empty


def test_evaluate_segments_flags_a_failed_job(temp_db):
    rows = [{"job_id": "j1", "segment_id": "s1", "segment_name": "High Value", "status": "failed", "is_bad": True}]
    alerts.evaluate_segments(rows)
    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert open_alerts.iloc[0]["source"] == "Segments"


def test_evaluate_segments_does_not_flag_a_succeeded_job(temp_db):
    rows = [{"job_id": "j1", "segment_id": "s1", "segment_name": "High Value", "status": "succeeded", "is_bad": False}]
    alerts.evaluate_segments(rows)
    assert database.list_alerts(resolved=False).empty


def test_evaluate_query_service_flags_a_failed_query(temp_db):
    rows = [{"query_id": "q1", "name": "Daily rollup", "state": "failed", "is_bad": True, "error_message": "timeout"}]
    alerts.evaluate_query_service(rows)
    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert open_alerts.iloc[0]["source"] == "Query Service"


def test_evaluate_query_service_does_not_flag_a_successful_query(temp_db):
    rows = [{"query_id": "q1", "name": "Daily rollup", "state": "success", "is_bad": False, "error_message": ""}]
    alerts.evaluate_query_service(rows)
    assert database.list_alerts(resolved=False).empty


def test_evaluate_freshness_covers_segments_and_query_service(temp_db, monkeypatch):
    monkeypatch.setattr(database, "_now", lambda: (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat())
    database.record_segment_job_snapshots([{"job_id": "j1", "segment_id": "s1", "segment_name": "x", "status": "succeeded"}])
    database.record_query_snapshots([{"query_id": "q1", "name": "x", "state": "success"}])

    alerts.evaluate_freshness()

    open_alerts = database.list_alerts(resolved=False)
    assert {row["title"].split(" — ")[0] for _, row in open_alerts.iterrows()} == {"Segments", "Query Service"}
