from __future__ import annotations

"""data.py's diff orchestration functions (fetch_schema_diff,
fetch_dc_property_diff, fetch_cja_dataview_diff) — the plumbing behind the
Compare page's Schemas/DC Properties/CJA Data Views tabs. Run against mock
data (settings.mock_mode defaults True), which is deliberately seeded with
real overlaps/differences for exactly this purpose — see clients/mock.py.
"""

from aep_monitor import data

_LOYALTY_SCHEMA_ID = "https://ns.adobe.com/acmecorp/schemas/loyalty-events"


def test_fetch_schema_diff_shows_a_field_added_in_the_non_prod_sandbox():
    # mock_schema_fields_for_sandbox() adds "_acmecorp.loyaltyTier2" for any
    # non-prod sandbox and doesn't touch prod at all.
    result = data.fetch_schema_diff(_LOYALTY_SCHEMA_ID, "prod", _LOYALTY_SCHEMA_ID, "dev")
    diff = result["diff"]
    assert diff["only_a"] == []
    assert [f["path"] for f in diff["only_b"]] == ["_acmecorp.loyaltyTier2"]


def test_fetch_schema_diff_shows_a_changed_field_description():
    result = data.fetch_schema_diff(_LOYALTY_SCHEMA_ID, "prod", _LOYALTY_SCHEMA_ID, "dev")
    changed = {c["key"]: c["changed_fields"] for c in result["diff"]["common"]}
    assert changed["_acmecorp.tier"] == ["description"]


def test_fetch_schema_diff_between_identical_sandboxes_has_no_differences():
    result = data.fetch_schema_diff(_LOYALTY_SCHEMA_ID, "prod", _LOYALTY_SCHEMA_ID, "prod")
    diff = result["diff"]
    assert diff["only_a"] == []
    assert diff["only_b"] == []
    assert all(not c["changed_fields"] for c in diff["common"])


def test_fetch_schema_diff_handles_a_schema_id_that_does_not_exist():
    # fetch_schema_fields() falls back to {} for an unknown schema id
    # (see clients/mock.py / schema_registry.get_schema) — flatten_fields()
    # on that returns [], so the diff should show "everything on the other
    # side is only-there" rather than raising.
    result = data.fetch_schema_diff("not-a-real-schema-id", "prod", _LOYALTY_SCHEMA_ID, "prod")
    assert result["diff"]["only_a"] == []
    assert len(result["diff"]["only_b"]) > 0


def test_fetch_dc_property_diff_shows_extensions_only_on_each_side():
    result = data.fetch_dc_property_diff("PR1", "PR2")
    assert result["found_a"] is True
    assert result["found_b"] is True
    ext = result["extensions"]
    names_a = {e["name"] for e in ext["only_a"]}
    names_b = {e["name"] for e in ext["only_b"]}
    assert "Custom Consent Extension" in names_a  # PR1-only, per mock data
    assert "Adobe Experience Platform Mobile SDK" in names_b  # PR2-only


def test_fetch_dc_property_diff_reports_missing_property():
    result = data.fetch_dc_property_diff("PR1", "does-not-exist")
    assert result["found_a"] is True
    assert result["found_b"] is False
    assert "extensions" not in result  # no diff computed when either side is missing


def test_fetch_dc_property_diff_shows_production_environment_status_changed():
    # Both properties have a "Production" environment (same name), but
    # PR1's is seeded "failed" and PR2's "succeeded" — same-name match,
    # different status, should land in "common" with status flagged changed.
    result = data.fetch_dc_property_diff("PR1", "PR2")
    envs = result["environments"]
    only_a_names = {e["name"] for e in envs["only_a"]}
    assert only_a_names == {"Staging"}  # PR2 has no staging environment
    changed = {c["key"]: c["changed_fields"] for c in envs["common"]}
    assert changed.get("Production") == ["status"]


def test_fetch_dc_property_diff_shows_data_elements_only_on_each_side():
    result = data.fetch_dc_property_diff("PR1", "PR2")
    des = result["data_elements"]
    assert {d["name"] for d in des["only_a"]} == {"Cart Total", "Consent Status"}
    assert {d["name"] for d in des["only_b"]} == {"App Version"}


def test_fetch_cja_dataview_diff_shows_dimensions_only_on_each_side_and_a_type_change():
    result = data.fetch_cja_dataview_diff("dv-exec", "dv-mktg")
    dims = result["dimensions"]
    assert {d["name"] for d in dims["only_a"]} == {"Page"}
    assert {d["name"] for d in dims["only_b"]} == {"Campaign"}
    changed = {c["key"]: c["changed_fields"] for c in dims["common"]}
    assert changed["Marketing Channel"] == ["type"]


_LOYALTY_DATASET_ID = "5f1a2b3c4d5e6f7a8b9c0d1e"


def test_fetch_dataset_diff_flags_identity_enabled_changed_in_non_prod_sandbox():
    # mock_datasets_for_sandbox() disables Identity Service on the Loyalty
    # Events dataset for any non-prod sandbox, prod left untouched.
    result = data.fetch_dataset_diff(_LOYALTY_DATASET_ID, "prod", _LOYALTY_DATASET_ID, "dev")
    assert result["found_a"] is True
    assert result["found_b"] is True
    changed_fields = {r["field"] for r in result["rows"] if r["changed"]}
    assert changed_fields == {"identity_enabled"}


def test_fetch_dataset_diff_between_identical_sandboxes_has_no_changes():
    result = data.fetch_dataset_diff(_LOYALTY_DATASET_ID, "prod", _LOYALTY_DATASET_ID, "prod")
    assert all(not r["changed"] for r in result["rows"])


_WEB_EVENTS_DATASET_ID = "6a2b3c4d5e6f7a8b9c0d1e2f"


def test_fetch_dataset_diff_flags_description_changed():
    """Regression: reported live as "not showing the actual differences" —
    description was a real, user-editable field shown on the Datasets page
    but silently excluded from Compare's diff (only name/schema_id/
    profile_enabled/identity_enabled were compared), so two datasets that
    genuinely differed only in description showed as "no differences".
    mock_datasets_for_sandbox() perturbs Web SDK Events' description for
    any non-prod sandbox specifically to pin this."""
    result = data.fetch_dataset_diff(_WEB_EVENTS_DATASET_ID, "prod", _WEB_EVENTS_DATASET_ID, "dev")
    changed_fields = {r["field"] for r in result["rows"] if r["changed"]}
    assert changed_fields == {"description"}


def test_fetch_dataset_diff_reports_missing_dataset():
    result = data.fetch_dataset_diff(_LOYALTY_DATASET_ID, "prod", "not-a-real-dataset-id", "prod")
    assert result["found_a"] is True
    assert result["found_b"] is False
    assert "rows" not in result
