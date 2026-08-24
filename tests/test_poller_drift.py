from __future__ import annotations

"""refresh_entity_drift() — the cron-only sweep (see poller.py's docstring
for why this is NOT part of refresh_all()) that keeps "vs. last snapshot"
drift baselines fresh for whatever entities a Compare visit has already
opted into tracking. Run against mock data (settings.mock_mode defaults
True)."""

from aep_monitor import database
from aep_monitor.poller import refresh_entity_drift


def test_sweeps_only_entities_that_already_have_a_baseline(temp_db):
    """An entity nobody has ever drift-checked via Compare has no snapshot
    row yet, so it's invisible to list_known_entity_keys() and the sweep
    must not touch it — there's no baseline for a scheduled run to
    originate."""
    counts = refresh_entity_drift()
    assert counts == {"schema": 0, "dataset": 0, "dc_property": 0, "cja_dataview": 0}


def test_sweep_records_a_fresh_snapshot_for_every_known_entity_type(temp_db):
    # Seed one "known" entity per type, as if each had already been opened
    # once in Compare's "Last snapshot (drift)" mode.
    database.record_entity_snapshot("schema", "prod::https://ns.adobe.com/acmecorp/schemas/loyalty-events", "Loyalty Events", [])
    database.record_entity_snapshot("dataset", "prod::5f1a2b3c4d5e6f7a8b9c0d1e", "Loyalty Events", {})
    database.record_entity_snapshot("dc_property", "PR1", "acme.com — Web", {})
    database.record_entity_snapshot("cja_dataview", "dv-exec", "Executive Dashboard", {})

    seeded_checked_at = {
        entity_type: database.latest_entity_snapshot(entity_type, key)["checked_at"]
        for entity_type, key in [("schema", "prod::https://ns.adobe.com/acmecorp/schemas/loyalty-events"),
                                  ("dataset", "prod::5f1a2b3c4d5e6f7a8b9c0d1e"),
                                  ("dc_property", "PR1"),
                                  ("cja_dataview", "dv-exec")]
    }

    counts = refresh_entity_drift()

    assert counts == {"schema": 1, "dataset": 1, "dc_property": 1, "cja_dataview": 1}
    # Each sweep call re-fetched live (mock) data and recorded it as a new
    # latest snapshot — the empty seeded payloads above are superseded by
    # real content, and each snapshot's timestamp moved forward.
    schema_latest = database.latest_entity_snapshot("schema", "prod::https://ns.adobe.com/acmecorp/schemas/loyalty-events")
    assert schema_latest["payload"] != []
    assert schema_latest["checked_at"] >= seeded_checked_at["schema"]

    dataset_latest = database.latest_entity_snapshot("dataset", "prod::5f1a2b3c4d5e6f7a8b9c0d1e")
    assert dataset_latest["payload"] != {}

    dc_latest = database.latest_entity_snapshot("dc_property", "PR1")
    assert dc_latest["payload"] != {}

    cja_latest = database.latest_entity_snapshot("cja_dataview", "dv-exec")
    assert cja_latest["payload"] != {}


def test_sweep_skips_a_failing_entity_without_aborting_the_rest(temp_db, monkeypatch):
    """One entity failing to re-fetch (e.g. deleted since its last snapshot)
    must not stop the sweep from covering every other known entity."""
    from aep_monitor import data

    database.record_entity_snapshot("schema", "prod::not-a-real-schema", "Ghost Schema", {})
    database.record_entity_snapshot("dc_property", "PR1", "acme.com — Web", {})

    original_fetch_schema_drift = data.fetch_schema_drift

    def _boom(schema_id, sandbox, schema_title):
        if schema_id == "not-a-real-schema":
            raise RuntimeError("schema was deleted")
        return original_fetch_schema_drift(schema_id, sandbox, schema_title)

    monkeypatch.setattr(data, "fetch_schema_drift", _boom)

    counts = refresh_entity_drift()

    assert counts["schema"] == 1  # attempted, even though it failed
    assert counts["dc_property"] == 1  # unaffected by the schema failure
    dc_latest = database.latest_entity_snapshot("dc_property", "PR1")
    assert dc_latest["payload"] != {}  # the DC sweep actually ran and recorded fresh data
