from __future__ import annotations

from aep_monitor import database


def test_upsert_alert_is_idempotent_for_the_same_open_fingerprint(temp_db):
    created_first = database.upsert_alert("AEP", "critical", "Flow X failed", "", "aep:flow-x:latest_run")
    created_second = database.upsert_alert("AEP", "critical", "Flow X failed", "", "aep:flow-x:latest_run")
    assert created_first is True
    assert created_second is False  # dedup — no duplicate row, no re-notify
    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1


def test_auto_resolve_missing_clears_alerts_whose_fingerprint_is_no_longer_active(temp_db):
    database.upsert_alert("AEP", "critical", "Flow X failed", "", "aep:flow-x:latest_run")
    database.upsert_alert("AEP", "critical", "Flow Y failed", "", "aep:flow-y:latest_run")

    # Next poll: only flow-x is still failing.
    resolved_count = database.auto_resolve_missing("AEP", {"aep:flow-x:latest_run"})

    assert resolved_count == 1
    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert open_alerts.iloc[0]["title"] == "Flow X failed"


def test_auto_resolve_missing_only_touches_its_own_source(temp_db):
    database.upsert_alert("AEP", "critical", "AEP issue", "", "aep:x")
    database.upsert_alert("CJA", "critical", "CJA issue", "", "cja:x")

    database.auto_resolve_missing("AEP", set())  # nothing active -> resolves AEP's alert only

    open_alerts = database.list_alerts(resolved=False)
    assert len(open_alerts) == 1
    assert open_alerts.iloc[0]["source"] == "CJA"


def test_a_condition_that_clears_then_recurs_reopens_as_a_new_alert(temp_db):
    """The unique index is scoped to resolved=0, so a fingerprint can be
    reused once its prior alert is resolved — this is what lets the same
    flow alert again on a second, later failure instead of staying silently
    resolved forever."""
    database.upsert_alert("AEP", "critical", "Flow X failed", "", "aep:flow-x:latest_run")
    database.auto_resolve_missing("AEP", set())  # condition clears
    created_again = database.upsert_alert("AEP", "critical", "Flow X failed again", "", "aep:flow-x:latest_run")

    assert created_again is True
    assert len(database.list_alerts(resolved=False)) == 1
    assert len(database.list_alerts(resolved=True)) == 1


def test_resolve_alert_marks_it_resolved(temp_db):
    database.upsert_alert("AEP", "critical", "Flow X failed", "", "aep:flow-x:latest_run")
    alert_id = int(database.list_alerts(resolved=False).iloc[0]["id"])

    database.resolve_alert(alert_id)

    assert database.list_alerts(resolved=False).empty
    assert len(database.list_alerts(resolved=True)) == 1


def test_open_alert_counts_groups_by_severity(temp_db):
    database.upsert_alert("AEP", "critical", "a", "", "fp1")
    database.upsert_alert("Data Collection", "warning", "b", "", "fp2")
    database.upsert_alert("Data Collection", "warning", "c", "", "fp3")

    counts = database.open_alert_counts()

    assert counts == {"critical": 1, "warning": 2}


def test_aep_snapshot_round_trips_through_history(temp_db):
    database.record_aep_snapshots([
        {"flow_id": "f1", "flow_name": "Flow 1", "status": "success", "records_in": 100, "records_out": 100, "records_failed": 0},
    ])
    history = database.read_aep_history(flow_id="f1")
    assert len(history) == 1
    assert history.iloc[0]["records_in"] == 100


def test_quota_snapshot_round_trips_through_history(temp_db):
    database.record_quota_snapshots([{"name": "q1", "consumed": 10, "quota": 100, "pct_used": 10.0}])
    history = database.read_quota_history(quota_name="q1")
    assert len(history) == 1
    assert history.iloc[0]["pct_used"] == 10.0


def test_latest_checked_at_covers_quota(temp_db):
    assert database.latest_checked_at("Quota") is None
    database.record_quota_snapshots([{"name": "q1", "consumed": 10, "quota": 100, "pct_used": 10.0}])
    assert database.latest_checked_at("Quota") is not None


def test_user_directory_round_trips_and_fully_replaces_not_accumulates(temp_db):
    """Unlike every other snapshot table, the user directory is a
    point-in-time cache — a second replace must supersede the first, not
    append to it (see replace_user_directory()'s docstring)."""
    assert database.user_directory_fetched_at() is None
    assert database.read_user_directory() == []

    database.replace_user_directory([{"user_id": "u1", "email": "a@x.com", "display_name": "A"}])
    assert database.user_directory_fetched_at() is not None
    assert database.read_user_directory() == [{"user_id": "u1", "email": "a@x.com", "display_name": "A"}]

    database.replace_user_directory([{"user_id": "u2", "email": "b@x.com", "display_name": "B"}])
    directory = database.read_user_directory()
    assert directory == [{"user_id": "u2", "email": "b@x.com", "display_name": "B"}]  # u1 is gone, not still present


def test_latest_checked_at_is_none_before_any_snapshot(temp_db):
    assert database.latest_checked_at("AEP") is None
    database.record_aep_snapshots([{"flow_id": "f1", "flow_name": "x", "status": "success", "records_in": 1, "records_out": 1, "records_failed": 0}])
    assert database.latest_checked_at("AEP") is not None


def test_setting_overrides_round_trip(temp_db):
    assert database.get_setting("some_key", "default") == "default"
    database.set_setting("some_key", "custom_value")
    assert database.get_setting("some_key", "default") == "custom_value"


def test_sqlite_health_reports_ok_on_a_fresh_db(temp_db):
    health = database.sqlite_health()
    assert health["ok"] is True


def test_table_counts_reflects_inserted_rows(temp_db):
    database.upsert_alert("AEP", "critical", "a", "", "fp1")
    counts = database.table_counts()
    assert counts["alerts"] == 1


def test_latest_entity_snapshot_is_none_before_any_snapshot(temp_db):
    assert database.latest_entity_snapshot("schema", "prod::abc") is None


def test_entity_snapshot_round_trips_and_returns_the_newest(temp_db):
    database.record_entity_snapshot("schema", "prod::abc", "My Schema", {"fields": ["a"]})
    first = database.latest_entity_snapshot("schema", "prod::abc")
    assert first["entity_label"] == "My Schema"
    assert first["payload"] == {"fields": ["a"]}
    assert first["checked_at"] is not None

    database.record_entity_snapshot("schema", "prod::abc", "My Schema", {"fields": ["a", "b"]})
    second = database.latest_entity_snapshot("schema", "prod::abc")
    assert second["payload"] == {"fields": ["a", "b"]}  # supersedes the first, not appended to it


def test_entity_snapshot_is_scoped_by_both_entity_type_and_entity_key(temp_db):
    """A dataset and a schema that happen to share an entity_key (or the
    same schema id in two different sandboxes) must never be conflated into
    one drift history."""
    database.record_entity_snapshot("schema", "same-key", "Schema Label", {"kind": "schema"})
    database.record_entity_snapshot("dataset", "same-key", "Dataset Label", {"kind": "dataset"})

    assert database.latest_entity_snapshot("schema", "same-key")["payload"] == {"kind": "schema"}
    assert database.latest_entity_snapshot("dataset", "same-key")["payload"] == {"kind": "dataset"}


def test_list_known_entity_keys_returns_distinct_keys_with_their_latest_label(temp_db):
    database.record_entity_snapshot("cja_dataview", "dv-exec", "Executive Dashboard", {})
    database.record_entity_snapshot("cja_dataview", "dv-exec", "Executive Dashboard (renamed)", {})  # 2nd snapshot, same key
    database.record_entity_snapshot("cja_dataview", "dv-mktg", "Marketing Attribution View", {})
    database.record_entity_snapshot("dc_property", "PR1", "acme.com — Web", {})  # different entity_type — must not appear

    known = database.list_known_entity_keys("cja_dataview")

    assert {k["entity_key"] for k in known} == {"dv-exec", "dv-mktg"}
    exec_row = next(k for k in known if k["entity_key"] == "dv-exec")
    assert exec_row["entity_label"] == "Executive Dashboard (renamed)"  # the newest label, not the first


def test_table_counts_includes_entity_snapshots(temp_db):
    database.record_entity_snapshot("schema", "prod::abc", "My Schema", {})
    assert database.table_counts()["entity_snapshots"] == 1
