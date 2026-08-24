from __future__ import annotations

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
