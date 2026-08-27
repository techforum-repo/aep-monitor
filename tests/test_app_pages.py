from __future__ import annotations

"""Streamlit AppTest smoke suite — every page, in mock mode, asserting no
uncaught exception. This is the same mechanism that caught two real bugs
while building this app (a settings field-name typo, and the Compare
Sandboxes "org-wide" mislabeling) and is exactly the class of bug a plain
unit test of business logic won't catch: widget-state and page-composition
issues that only show up when Streamlit actually runs the page script.

Slower than the rest of the suite (each AppTest.run() boots a page's full
script) — kept in one file so `pytest -k "not test_app_pages"` can skip it
for a fast inner loop, while `pytest` alone still covers it.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

# Derived from the actual source of truth (ui/shared.py), not hand-duplicated
# here — a hand-duplicated list previously went stale silently when the
# Datasets page was added: this file's own copy wasn't updated, so the
# "every page renders" smoke test below never actually exercised the new
# page even though it looked like full coverage. Importing it directly means
# the next new page is covered automatically, with no separate edit to
# remember here.
from aep_monitor.ui.shared import PAGE_NAMES

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def _temp_db_for_app(tmp_path, monkeypatch):
    """The app module-level `initialize()` call and every page's fetch/alert
    calls read/write aep_monitor.db — redirect that to a throwaway file so
    running this suite never touches (or depends on) a real one."""
    from aep_monitor import database
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "app_test.db")


@pytest.mark.parametrize("page", PAGE_NAMES)
def test_page_renders_without_exception(page):
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert at.exception == []
    at.radio(key="navigation").set_value(page).run()
    assert at.exception == []


def test_overview_page_shows_the_end_to_end_lineage_and_unlinked_dc_properties():
    """Overview's new "End-to-end data flow" section — a Sankey of AEP
    Dataset -> CJA Connection -> Data View -> Project, plus DC properties
    listed separately underneath as explicitly not connected into it (no
    public Datastream API to discover that link programmatically)."""
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert at.exception == []

    markdown_text = " ".join(m.value for m in at.markdown)
    assert "End-to-end data flow" in markdown_text
    assert "Data Collection properties (not linked above)" in markdown_text

    dc_table = next(df.value for df in at.get("dataframe") if "Property" in df.value.columns and "Extensions" in df.value.columns)
    assert len(dc_table) == 2  # both mock DC properties, listed unconnected

    # "All connections" was removed — a real org's full, unfiltered pipeline
    # is reliably too dense to read, so the picker always scopes to one.
    focus = at.selectbox(key="overview_lineage_focus")
    assert "All connections" not in focus.options
    assert focus.value in focus.options  # defaults to a real connection, not an unset/invalid value


def test_overview_lineage_names_the_cja_permission_gap_when_connections_are_empty(monkeypatch):
    """Regression: a generic "nothing to chart" message was indistinguishable
    from the much more common, well-documented cause (this credential can't
    see any CJA connections at all — the lineage walk starts there, so zero
    connections means zero rows no matter what else exists) — reported live
    as confusing for exactly that reason. Must name the real cause instead,
    same as the CJA page's own empty-connections note."""
    from aep_monitor.clients import mock as mock_module
    monkeypatch.setattr(mock_module, "MOCK_CONNECTIONS", [])

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()

    assert at.exception == []
    info_text = " ".join(i.value for i in at.info)
    assert "product-administration" in info_text or "product administration" in info_text


def test_overview_lineage_filters_connections_by_sandbox_relevance_with_an_opt_out(monkeypatch):
    """A connection whose dataset ids don't resolve in the active sandbox
    is hidden by default from "Focus on connection" — very likely means
    its real data lives in a different sandbox (connections are org-wide
    and have no sandbox of their own to check directly, so this is an
    inference, not a fact Adobe's API states). Never silently unreachable
    though: the "Show connections..." checkbox reveals it."""
    from aep_monitor.clients import mock as mock_module
    crm = dict(mock_module.MOCK_CONNECTIONS[1])  # CRM Connection — normally resolves fine
    crm["dataSets"] = [{"dataSetId": "not-a-real-dataset-id", "domain": "catalog", "type": "event", "name": "Ghost Dataset"}]
    monkeypatch.setattr(mock_module, "MOCK_CONNECTIONS", [mock_module.MOCK_CONNECTIONS[0], crm])

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert at.exception == []

    focus = at.selectbox(key="overview_lineage_focus")
    assert "CRM Connection" not in focus.options
    assert "Web + Mobile Unified" in focus.options

    at.checkbox(key="overview_lineage_show_all_connections").set_value(True).run()
    assert at.exception == []
    focus = at.selectbox(key="overview_lineage_focus")
    assert "CRM Connection" in focus.options


def test_sdr_page_loads_dataview_components_and_schema_fields_on_selection():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("SDR").run()
    assert at.exception == []

    # Both selectboxes default to their first option and eagerly load —
    # no extra click needed, matching the rest of the app's pattern.
    tables = at.get("dataframe")
    assert len(tables) >= 1  # at least the dimensions/metrics or fields table rendered
    assert at.exception == []
    tab_labels = [t.label for t in at.tabs] if hasattr(at, "tabs") else []
    assert "Calculated Metrics (2)" in tab_labels  # dv-exec's 2 calc metrics, per mock data


def test_sdr_page_component_usage_tab_is_opt_in_then_shows_real_usage():
    """The Component Usage tab is gated behind a "Load project usage"
    button (one API call per bound project — deliberately not auto-fetched
    like the other three tabs), then shows real per-component project
    counts once loaded."""
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("SDR").run()
    assert at.exception == []

    tab_labels = [t.label for t in at.tabs]
    assert "Component Usage" in tab_labels
    # Not loaded yet — no usage table, just the load button.
    assert not any("Used in projects" in df.value.columns for df in at.get("dataframe"))

    at.button(key="sdr_load_component_usage").click().run()
    assert at.exception == []

    usage_table = next(df.value for df in at.get("dataframe") if "Used in projects" in df.value.columns)
    by_name = usage_table.set_index("Name")
    assert by_name.loc["Conversion Rate", "Used in projects"] == 2
    assert by_name.loc["Marketing Channel", "Used in projects"] == 0  # unused, per mock data
    caption_text = " ".join(c.value for c in at.caption)
    assert "not referenced by any of its bound projects" in caption_text


def test_sdr_page_component_usage_debug_expander_shows_raw_unfiltered_references():
    """Added after "used in projects shows zero for everything" turned out
    to need a live round-trip to diagnose (same lesson as the schema field
    labels saga) — this expander exists so the next such mismatch is
    diagnosable from inside the app: every raw extracted reference,
    unfiltered (including the ReportSuite/DateRange ones the aggregated
    view excludes), so a real id can be compared directly against a known
    component's own id without needing another round-trip."""
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("SDR").run()
    at.button(key="sdr_load_component_usage").click().run()
    assert at.exception == []

    expander_labels = [e.label for e in at.expander]
    assert any("Raw entity references" in label and "7 found" in label for label in expander_labels)
    raw_table = next(df.value for df in at.get("dataframe") if "Id" in df.value.columns and "Project" in df.value.columns)
    assert len(raw_table) == 7
    assert "dv-exec" in set(raw_table["Id"])  # the ReportSuite entity, visible here though excluded from the aggregated table
    caption_text = " ".join(c.value for c in at.caption)
    assert "2 project(s) bound to this data view" in caption_text


def test_sdr_page_schema_fields_table_shows_data_governance_labels():
    """The schema fields table's "Labels" column — DULE labels (e.g.
    core/I2) fetched from the Schema Registry's Descriptors API, per field
    path. Loyalty Events' default-selected schema has 2 labeled fields
    (one with 3 labels on it, joined into one cell) and 2 unlabeled ones
    in mock data."""
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("SDR").run()
    assert at.exception == []

    fields_table = next(df.value for df in at.get("dataframe") if "Field path" in df.value.columns)
    assert "Labels" in fields_table.columns
    by_path = fields_table.set_index("Field path")["Labels"]
    assert by_path["_acmecorp.loyaltyId"] == "core/I2, custom/Restricted, custom/Confidential"
    assert by_path["_acmecorp.pointsBalance"] == "core/C1"
    assert by_path["timestamp"] == "—"  # unlabeled field falls back cleanly, not blank/NaN


def test_sdr_page_shows_a_raw_label_descriptors_debug_expander():
    """Added after "labels not showing up" turned out to be a real bug
    (xdm:sourceSchema is a field-group id, not the schema's own $id — see
    data.py's fetch_schema_field_labels() docstring) that took a live
    round-trip with the user to diagnose. This expander exists so the next
    "labels aren't showing up" case is diagnosable from inside the app —
    every fetched descriptor's path, independent of whether it matched the
    currently-selected schema — instead of needing another such
    round-trip. Mock data includes a descriptor for a path that isn't in
    any mock schema specifically so this shows a descriptor beyond just
    the ones that matched."""
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("SDR").run()
    assert at.exception == []

    expander_labels = [e.label for e in at.expander]
    assert any("Raw label descriptors" in label and "3 fetched" in label for label in expander_labels)
    debug_table = next(df.value for df in at.get("dataframe") if "Source schema (field group id)" in df.value.columns)
    assert "notInAnyMockSchema.someField" in set(debug_table["Path"])  # visible even though it didn't match


def test_sdr_page_surfaces_a_label_fetch_failure_instead_of_hiding_it(monkeypatch):
    """Regression: the first version of this feature silently swallowed
    any label-fetch exception, which meant a real request failure (e.g. a
    bad filter param, an auth issue) looked identical to "no labels
    configured" — exactly the ambiguity that made the original live bug
    report hard to diagnose. A failure must now be visible."""
    from aep_monitor import data as data_module

    def _boom(sandbox=None):
        raise RuntimeError("simulated descriptors fetch failure")

    monkeypatch.setattr(data_module, "fetch_label_descriptors", _boom)

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("SDR").run()

    assert at.exception == []  # the fields table itself still renders fine
    warning_text = " ".join(w.value for w in at.warning)
    assert "simulated descriptors fetch failure" in warning_text


def test_dc_page_property_detail_shows_environments_and_data_elements_tabs():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Data Collection").run()

    assert at.exception == []
    tab_labels = [t.label for t in at.tabs] if hasattr(at, "tabs") else []
    assert "Environments" in tab_labels
    assert "Data Elements" in tab_labels
    # PR1 (the default selectbox choice) has a failed production
    # environment and a dirty data element in mock data — the page text
    # should surface both rather than just "no exception".
    body_text = " ".join(m.value for m in at.markdown)
    assert "Production" in body_text
    assert "Consent Status" in body_text


def test_init_session_state_gives_each_call_its_own_mutable_defaults(monkeypatch):
    """Regression: DEFAULT_STATE's dict/list defaults (e.g.
    sdr_components_cache) were originally assigned by bare reference in
    init_session_state() — since Streamlit runs one process for every
    session, every session would receive the literal same dict object, and
    one session populating its cache (live Adobe data included) would leak
    into every other session's state. copy.deepcopy() at init time is what
    fixes this; this test calls the real function against two independent
    session-state dicts and confirms mutating one's cache doesn't touch
    the other's."""
    from aep_monitor.ui import shared

    session_a: dict = {}
    session_b: dict = {}

    monkeypatch.setattr(shared.st, "session_state", session_a)
    shared.init_session_state()
    monkeypatch.setattr(shared.st, "session_state", session_b)
    shared.init_session_state()

    session_a["sdr_components_cache"]["dv-exec"] = {"dimensions": ["leaked data"]}
    assert session_b["sdr_components_cache"] == {}


def test_compare_page_schemas_tab_shows_a_real_diff(monkeypatch):
    from aep_monitor.config import settings
    monkeypatch.setattr(settings, "adobe_sandboxes", "prod,dev")

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()

    assert at.exception == []
    # Default selectbox indices give Sandbox A=prod, Sandbox B=dev, Schema
    # A/B both default to the first title ("Loyalty Events"), and mock data
    # seeds a real difference between prod/dev for that schema
    # (mock_schema_fields_for_sandbox in clients/mock.py) — one metric
    # labeled "Only in ... (dev)" should be non-zero, reflecting that
    # instead of "no differences found".
    metrics = {m.label: m.value for m in at.metric}
    dev_only_metric = next(v for label, v in metrics.items() if label.startswith("Only in") and "(dev)" in label)
    assert dev_only_metric == "1"


def test_compare_page_datasets_tab_shows_a_real_diff(monkeypatch):
    from aep_monitor.config import settings
    monkeypatch.setattr(settings, "adobe_sandboxes", "prod,dev")

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()

    assert at.exception == []
    # Default selectbox indices give Sandbox A=prod, Sandbox B=dev, Dataset
    # A/B both default to the first dataset name, and mock data seeds a real
    # identity_enabled difference between prod/dev for it
    # (mock_datasets_for_sandbox in clients/mock.py) — the Datasets tab's
    # table (a plain "Changed" column, not metrics — unlike every other
    # Compare tab, since a dataset is a single flat object, not a list of
    # named sub-items) should show at least one 🔴 row instead of "no
    # differences".
    dataset_tables = [df.value for df in at.get("dataframe") if "Changed" in df.value.columns]
    assert len(dataset_tables) == 1
    assert (dataset_tables[0]["Changed"] == "🔴 yes").any()
    # Regression: the "Schema" row originally showed a raw $id/URL instead
    # of the schema's title, same gap as the Datasets page.
    schema_row = dataset_tables[0][dataset_tables[0]["Field"] == "Schema"].iloc[0]
    assert schema_row["Value (prod)"] == "Loyalty Events"


def test_compare_page_datasets_tab_shows_schema_field_level_differences(monkeypatch):
    """Regression: reported live — the "Schema" row only said the binding
    *changed* (by name/id), never what was actually different about the
    two schemas' fields, which is the "actual difference" a user actually
    wants to see. This pins that the embedded field-level diff (reusing
    fetch_schema_diff()/_render_diff(), the same engine the Schemas tab
    itself uses) renders real, non-zero metrics for the default dataset
    selection (Loyalty Events), whose schema genuinely differs prod-vs-dev
    in mock data (mock_schema_fields_for_sandbox in clients/mock.py)."""
    from aep_monitor.config import settings
    monkeypatch.setattr(settings, "adobe_sandboxes", "prod,dev")

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()

    assert at.exception == []
    markdown_text = " ".join(m.value for m in at.markdown)
    assert "Schema field differences" in markdown_text

    def any_nonzero(label: str) -> bool:
        return any(m.value not in (None, "0") for m in at.metric if m.label == label)

    assert any_nonzero("Only in Loyalty Events (dev)")  # dev has a field prod doesn't, per mock data


def test_compare_page_datasets_tab_flags_a_description_difference(monkeypatch):
    """Regression: reported live as "not showing the actual differences" —
    description was shown on the Datasets page but silently excluded from
    Compare's diff. Web SDK Events (not Loyalty Events, which only differs
    in identity_enabled — see the test above) has a description that
    varies between prod/dev in mock data specifically to pin this."""
    from aep_monitor.config import settings
    monkeypatch.setattr(settings, "adobe_sandboxes", "prod,dev")

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()
    at.selectbox(key="compare_dataset_name_a").set_value("Web SDK Events").run()
    at.selectbox(key="compare_dataset_name_b").set_value("Web SDK Events").run()

    assert at.exception == []
    dataset_tables = [df.value for df in at.get("dataframe") if "Changed" in df.value.columns]
    description_row = dataset_tables[0][dataset_tables[0]["Field"] == "Description"].iloc[0]
    assert description_row["Changed"] == "🔴 yes"
    assert description_row["Value (prod)"] != description_row["Value (dev)"]


def test_datasets_page_shows_profile_and_identity_columns():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Datasets").run()

    assert at.exception == []
    tables = [df.value for df in at.get("dataframe") if "Schema" in df.value.columns]
    assert len(tables) == 1
    assert "Profile-enabled" in tables[0].columns
    assert "Identity-enabled" in tables[0].columns
    assert len(tables[0]) == 3  # 3 datasets in mock data


def test_datasets_page_shows_schema_titles_not_raw_ids():
    """Regression: reported live as a usability gap — the Schema column
    originally showed a truncated $id slug ("loyalty-events") instead of
    the schema's actual title ("Loyalty Events")."""
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Datasets").run()

    assert at.exception == []
    tables = [df.value for df in at.get("dataframe") if "Schema" in df.value.columns]
    schema_values = set(tables[0]["Schema"])
    assert "Loyalty Events" in schema_values
    assert not any("ns.adobe.com" in str(v) for v in schema_values)  # no raw $id URL leaked through


def test_compare_page_cja_tab_shows_a_calculated_metrics_sub_tab():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()

    assert at.exception == []
    tab_labels = [t.label for t in at.tabs] if hasattr(at, "tabs") else []
    assert "Calculated Metrics" in tab_labels
    # Default selectbox indices give Data view A=dv-exec, B=dv-mktg, whose
    # calculated metrics don't overlap at all in mock data (Conversion
    # Rate/Average Order Value vs. Cost per Lead) — at least one "Only in"
    # metric should be non-zero.
    def any_nonzero(label: str) -> bool:
        return any(m.value not in (None, "0") for m in at.metric if m.label == label)

    assert any_nonzero("Only in Executive Dashboard View") or any_nonzero("Only in Marketing Attribution View")


def test_compare_page_dc_tab_shows_a_real_diff():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()

    assert at.exception == []
    # Default selectbox indices give Property A=PR1, Property B=PR2. The DC
    # tab has 5 sub-tabs (Extensions/Rules/Libraries/Environments/Data
    # Elements), each producing a metric with the *same* label ("Only in
    # acme.com — Web", ...) — a naive {label: value} dict would silently
    # keep only the last one (whichever sub-tab happens to have 0 for that
    # side even though others don't), so this checks across every matching
    # metric instead.
    def any_nonzero(label: str) -> bool:
        return any(m.value not in (None, "0") for m in at.metric if m.label == label)

    assert any_nonzero("Only in acme.com — Web")
    assert any_nonzero("Only in Acme Mobile App")


def test_compare_page_schemas_tab_drift_mode_shows_no_baseline_then_a_real_diff():
    """"Compare against: Last snapshot (drift)" mode, Schemas tab. First
    visit ever for this schema+sandbox has no baseline — the "just became
    the baseline" banner, not a diff. A second drift function call (after
    manually staling the recorded snapshot, simulating time passing between
    two app visits) should surface a real diff against it."""
    from aep_monitor import data, database

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()
    at.radio(key="compare_schema_mode").set_value("Last snapshot (drift)").run()

    assert at.exception == []
    info_text = " ".join(i.value for i in at.info)
    assert "No prior snapshot" in info_text

    # Stale the snapshot fetch_schema_drift just recorded above, so the next
    # call has something real to diff against.
    fields, _ = data.fetch_schema_fields("https://ns.adobe.com/acmecorp/schemas/loyalty-events", sandbox="prod")
    stale_fields = fields[1:] + [{"path": "removedLater/fake", "type": "string", "title": "Fake Removed Field", "description": ""}]
    database.record_entity_snapshot("schema", "prod::https://ns.adobe.com/acmecorp/schemas/loyalty-events", "Loyalty Events", stale_fields)

    at2 = AppTest.from_file(APP_PATH, default_timeout=30)
    at2.run()
    at2.radio(key="navigation").set_value("Compare").run()
    at2.radio(key="compare_schema_mode").set_value("Last snapshot (drift)").run()

    assert at2.exception == []
    caption_text = " ".join(c.value for c in at2.caption)
    assert "Comparing against the snapshot taken" in caption_text
    metrics = {m.label: m.value for m in at2.metric}
    assert metrics["Only in Previous snapshot"] == "1"
    assert metrics["Only in Current"] == "1"


def test_compare_page_datasets_tab_drift_mode_shows_a_real_diff():
    from aep_monitor import database

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()
    at.radio(key="compare_dataset_mode").set_value("Last snapshot (drift)").run()
    assert at.exception == []  # first visit: just establishes the baseline

    database.record_entity_snapshot(
        "dataset", "prod::5f1a2b3c4d5e6f7a8b9c0d1e", "Loyalty Events",
        {"name": "Loyalty Events (OLD)", "schema_id": "old-schema", "profile_enabled": False, "identity_enabled": False},
    )

    at2 = AppTest.from_file(APP_PATH, default_timeout=30)
    at2.run()
    at2.radio(key="navigation").set_value("Compare").run()
    at2.radio(key="compare_dataset_mode").set_value("Last snapshot (drift)").run()

    assert at2.exception == []
    dataset_tables = [df.value for df in at2.get("dataframe") if "Changed" in df.value.columns]
    assert len(dataset_tables) == 1
    assert (dataset_tables[0]["Changed"] == "🔴 yes").any()
    name_row = dataset_tables[0][dataset_tables[0]["Field"] == "Name"].iloc[0]
    assert name_row["Previous snapshot"] == "Loyalty Events (OLD)"
    assert name_row["Current"] == "Loyalty Events"


def test_compare_page_dc_tab_drift_mode_shows_a_real_diff():
    from aep_monitor import database

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()
    at.radio(key="compare_dc_mode").set_value("Last snapshot (drift)").run()
    assert at.exception == []  # first visit: just establishes the baseline

    # PR1 ("acme.com — Web") is the default selectbox choice — stale its
    # recorded extensions list so the second visit has a real diff.
    database.record_entity_snapshot(
        "dc_property", "PR1", "acme.com — Web",
        {"extensions": [], "rules": [], "libraries": [], "environments": [], "data_elements": []},
    )

    at2 = AppTest.from_file(APP_PATH, default_timeout=30)
    at2.run()
    at2.radio(key="navigation").set_value("Compare").run()
    at2.radio(key="compare_dc_mode").set_value("Last snapshot (drift)").run()

    assert at2.exception == []

    def any_nonzero(label: str) -> bool:
        return any(m.value not in (None, "0") for m in at2.metric if m.label == label)

    # Every component (extensions/rules/libraries/environments/data
    # elements) was staled to empty, so "Current" now has entries the
    # (empty) baseline doesn't -- "Only in Current" should be non-zero
    # somewhere among the 5 sub-tabs.
    assert any_nonzero("Only in Current")


def test_compare_page_cja_tab_drift_mode_shows_a_real_diff():
    from aep_monitor import database

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()
    at.radio(key="compare_cja_mode").set_value("Last snapshot (drift)").run()
    assert at.exception == []  # first visit: just establishes the baseline

    # dv-exec is the default selectbox choice — stale its recorded
    # dimensions/metrics/calculated metrics so the second visit has a real diff.
    database.record_entity_snapshot("cja_dataview", "dv-exec", "Executive Dashboard", {"dimensions": [], "metrics": [], "calculated_metrics": []})

    at2 = AppTest.from_file(APP_PATH, default_timeout=30)
    at2.run()
    at2.radio(key="navigation").set_value("Compare").run()
    at2.radio(key="compare_cja_mode").set_value("Last snapshot (drift)").run()

    assert at2.exception == []

    def any_nonzero(label: str) -> bool:
        return any(m.value not in (None, "0") for m in at2.metric if m.label == label)

    assert any_nonzero("Only in Current")


def test_compare_sandboxes_tab_shows_differentiated_data_for_multiple_sandboxes(monkeypatch):
    from aep_monitor.config import settings
    monkeypatch.setattr(settings, "adobe_sandboxes", "prod,dev,stage")

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Compare").run()

    assert at.exception == []
    # Streamlit renders every tab's content on each script run regardless of
    # which is visually active, and the Compare page now has 4 tabs — find
    # the Sandboxes tab's table by its distinctive "Sandbox" column rather
    # than assuming it's the only dataframe on the page.
    sandbox_tables = [df.value for df in at.get("dataframe") if "Sandbox" in df.value.columns]
    assert len(sandbox_tables) == 1
    table = sandbox_tables[0]
    assert list(table["Sandbox"]) == ["prod", "dev", "stage"]
    # prod is seeded clean in mock data; at least one other sandbox isn't —
    # pins the "these vary per sandbox" behavior the tab exists to show.
    assert table.set_index("Sandbox").loc["prod", "Failing flows"] == 0
    assert table["Failing flows"].sum() > 0


def test_cja_page_explains_zero_connections_instead_of_a_generic_empty_message(monkeypatch):
    """Reported live: a Server-to-Server credential without CJA 'product
    administration' privileges gets a *successful* empty response from
    Adobe (200 OK, zero items) rather than an error — so there's no
    exception to intercept, and the generic "No connections found" message
    would otherwise leave a real, actionable, well-documented Adobe access
    quirk looking indistinguishable from "you just have no connections."""
    from aep_monitor.clients import mock as mock_module
    monkeypatch.setattr(mock_module, "MOCK_CONNECTIONS", [])
    monkeypatch.setattr(mock_module, "MOCK_DATAVIEWS", [])

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("CJA").run()

    assert at.exception == []
    info_text = " ".join(i.value for i in at.info)
    assert "product administration" in info_text.lower()


def test_cja_page_shows_connection_and_dataview_names_not_raw_ids():
    """Regression: reported live — Connections and Data views both showed
    raw ids instead of names. Root cause was Adobe's /connections and
    /dataviews only include `name` (and other fields) when explicitly
    requested via the `expansion` query param — confirmed via Adobe's docs
    — which list_connections()/list_dataviews() weren't sending."""
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("CJA").run()

    assert at.exception == []
    conn_table = next(df.value for df in at.get("dataframe") if "Connection" in df.value.columns and "Status" in df.value.columns)
    assert "Web + Mobile Unified" in set(conn_table["Connection"])
    assert not any("conn-" in str(v) for v in conn_table["Connection"])  # no raw id leaked through

    dv_table = next(df.value for df in at.get("dataframe") if "Data view" in df.value.columns)
    assert "Executive Dashboard View" in set(dv_table["Data view"])
    # Regression: the FK back to the connection was read from the wrong
    # field (connectionId/dataConnectionId, guessed) instead of the real
    # `parentDataGroupId` — this resolved to the connection's raw id even
    # once the connection's own name was showing correctly elsewhere.
    assert "Web + Mobile Unified" in set(dv_table["Connection"])
    assert not any("conn-" in str(v) for v in dv_table["Connection"])


def test_cja_page_shows_projects_with_resolved_dataview_names():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("CJA").run()

    assert at.exception == []
    proj_table = next(df.value for df in at.get("dataframe") if "Project" in df.value.columns)
    assert len(proj_table) == 3  # all 3 mock projects, across both data views
    assert "Executive Weekly Report" in set(proj_table["Project"])
    # Resolved to the data view's name, not its raw id.
    assert "Executive Dashboard View" in set(proj_table["Data view"])
    assert not any(str(v).startswith("dv-") for v in proj_table["Data view"])
    # Resolved to the owner's display name (via expansion=ownerFullName),
    # not the opaque imsUserId/ownerId this endpoint returns by default.
    assert "Jordan Lee" in set(proj_table["Owner"])
    assert not any("@techacct.adobe.com" in str(v) or "@f6de294463f5897c495fa8.e" in str(v) for v in proj_table["Owner"])
    # Two-hop resolution (project -> data view -> connection): every mock
    # project's data view belongs to the same connection.
    assert set(proj_table["Connection"]) == {"Web + Mobile Unified"}


def test_cja_page_flags_an_unresolvable_reference_instead_of_a_bare_id(monkeypatch):
    """A project/data view can reference a connection or data view this
    credential can't itself see (Connections needs product administration,
    Data Views needs the credential's own Product Profile permissions —
    both real, expected access-model gaps, not bugs). Regression: that
    used to fall back to a bare id indistinguishable from an actual
    (coincidentally id-shaped) name; it must now be visibly flagged."""
    from aep_monitor.clients import mock as mock_module
    monkeypatch.setattr(mock_module, "MOCK_CONNECTIONS", [])  # nothing to resolve dv-exec's connection against

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("CJA").run()

    assert at.exception == []
    dv_table = next(df.value for df in at.get("dataframe") if "Data view" in df.value.columns)
    assert all(str(v).endswith("(unresolved)") for v in dv_table["Connection"])
    proj_table = next(df.value for df in at.get("dataframe") if "Project" in df.value.columns)
    assert all(str(v).endswith("(unresolved)") for v in proj_table["Connection"])


def test_cja_page_flags_a_projects_connection_as_unresolved_when_its_dataview_is_missing(monkeypatch):
    """Regression found by code review: a project referencing a data view
    this credential can't itself see (a real, expected access-model gap —
    Data Views needs the credential's own Product Profile permissions) has
    its Connection column resolved via a two-hop lookup
    (project -> data view -> connection). The first version fed the
    missed first hop's "" default straight into the generic id->name
    resolver, which short-circuits on a falsy id and returns the *same*
    "—" used for "this project genuinely has no connection" — so an
    unresolvable data view silently looked identical to "no connection",
    even though the same row's Data view column correctly flagged it as
    unresolved. Emptying MOCK_DATAVIEWS (not MOCK_CONNECTIONS, which the
    test above already covers) reproduces the missed-first-hop case
    specifically."""
    from aep_monitor.clients import mock as mock_module
    monkeypatch.setattr(mock_module, "MOCK_DATAVIEWS", [])

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("CJA").run()

    assert at.exception == []
    proj_table = next(df.value for df in at.get("dataframe") if "Project" in df.value.columns)
    # Every project's data view is unresolved, so its connection must be
    # flagged too — never the bare "—" that would look like "no connection".
    assert not any(str(v) == "—" for v in proj_table["Connection"])
    assert all("unresolved" in str(v) for v in proj_table["Connection"])


def test_cja_page_shows_data_views_and_projects_after_visiting_overview_first():
    """Regression: Overview's "Refresh everything" populates
    cja_connections (via refresh_all() -> refresh_cja()) but not
    cja_dataviews/cja_projects — it has no reason to know the CJA page also
    needs those. _ensure_loaded() originally only checked cja_connections,
    so landing on Overview (the app's default page) before clicking into
    CJA left cja_dataviews stuck at None — "No data views found" even
    though data views exist — until a manual refresh on the CJA page
    itself. This is exactly the sequence AppTest.run() -> navigate
    exercises, which is why the plain "renders without exception" smoke
    test never caught it. cja_projects was added to the same check from
    the start rather than needing its own separate live bug report first."""
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()  # lands on Overview by default, populating cja_connections only
    at.radio(key="navigation").set_value("CJA").run()

    assert at.exception == []
    info_text = " ".join(i.value for i in at.info)
    assert "No data views found" not in info_text
    assert "No CJA Workspace projects found" not in info_text
    dv_table = next(df.value for df in at.get("dataframe") if "Data view" in df.value.columns)
    assert len(dv_table) == 2  # both mock data views, not stuck empty
    proj_table = next(df.value for df in at.get("dataframe") if "Project" in df.value.columns)
    assert len(proj_table) == 3  # all 3 mock projects, not stuck empty


def test_audit_log_page_renders_all_three_product_sections():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="navigation").set_value("Audit Log").run()

    assert at.exception == []
    headers = " ".join(m.value for m in at.markdown)
    assert "AEP — who changed what" in headers
    assert "Data Collection — who changed what" in headers
    assert "CJA — who changed what" in headers
    # 3 tables (one per product) + 3 raw-response json expanders.
    assert len(at.get("dataframe")) == 3
    assert len(at.get("json")) == 3


def test_sandbox_switcher_changes_the_active_sandbox_and_triggers_a_refetch(monkeypatch):
    from aep_monitor.config import settings
    monkeypatch.setattr(settings, "adobe_sandboxes", "prod,dev")
    monkeypatch.setattr(settings, "adobe_sandbox", "prod")

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert at.exception == []

    switcher = at.selectbox(key="active_sandbox")
    assert set(switcher.options) == {"prod", "dev"}
    assert switcher.value == "prod"

    switcher.set_value("dev").run()
    assert at.exception == []

    at.radio(key="navigation").set_value("AEP Ingestion").run()
    assert at.exception == []
    # The page caption names the active sandbox, and the cache staleness
    # tracker recorded the refetch against "dev" — not still "prod".
    captions = " ".join(c.value for c in at.caption)
    assert "**dev**" in captions
    assert at.session_state["aep_rows_sandbox"] == "dev"
