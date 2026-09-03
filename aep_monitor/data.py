from __future__ import annotations

"""Single entry point every UI page calls to get parsed data for one
product. Branches mock vs. live here, once — pages never check
`settings.mock_mode` themselves. Mock data is run through the exact same
parse_*() functions as live data (see clients/mock.py), so this is the only
place the two paths diverge.
"""

from datetime import datetime, timezone
from typing import Any

from . import database, diffing
from .clients import (
    aep_client,
    audit_client,
    catalog_client,
    cja_client,
    observability_client,
    query_service_client,
    quota_client,
    reactor_client,
    schema_registry_client,
    segmentation_client,
    user_management_client,
)
from .clients import aep as aep_api
from .clients import audit as audit_api
from .clients import catalog as catalog_api
from .clients import cja as cja_api
from .clients import mock
from .clients import observability as observability_api
from .clients import query_service as query_service_api
from .clients import quota as quota_api
from .clients import reactor as reactor_api
from .clients import schema_registry as schema_registry_api
from .clients import segmentation as segmentation_api
from .clients import user_management as user_management_api
from .config import settings
from .datastream_map import load_datastream_map
from .logging_setup import get_logger
from .utils import run_async


def fetch_aep(sandbox: str | None = None) -> list[dict[str, Any]]:
    """One row per dataflow, with its most recent run's status/record counts
    folded in (`latest_run` is the empty dict when a flow has no runs yet).
    `sandbox` overrides the configured ADOBE_SANDBOX for this call only —
    used by fetch_sandbox_comparison() to poll multiple sandboxes; every
    other caller leaves it as None (the configured default)."""
    if settings.mock_mode:
        flows_raw = mock.MOCK_FLOWS
        runs_by_flow = mock.MOCK_RUNS
    else:
        async def _load() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
            async with aep_client._new_http_client() as http:  # noqa: SLF001 (same module family)
                flows = await aep_client.list_flows(http, sandbox=sandbox)
                runs = await aep_client.recent_runs_for_flows(http, flows, sandbox=sandbox)
                return flows, runs
        flows_raw, runs_by_flow = run_async(_load())

    connector_names = fetch_flow_spec_titles()
    rows: list[dict[str, Any]] = []
    for flow_raw in flows_raw:
        flow = aep_api.parse_flow(flow_raw)
        runs = [aep_api.parse_run(r) for r in runs_by_flow.get(flow["flow_id"], [])]
        latest = runs[0] if runs else {}
        connector_name = connector_names.get(flow["flow_spec_id"], flow["flow_spec_id"]) if flow["flow_spec_id"] else ""
        rows.append({**flow, "connector_name": connector_name, "latest_run": latest, "runs": runs})
    return rows


def fetch_flow_spec_titles() -> dict[str, str]:
    """{flow_spec_id: connector display name} — e.g. resolves to "Amazon S3"
    or "Google Ads Data Connector" instead of a raw flowSpec UUID, the same
    "names, not IDs" resolver pattern as fetch_schema_titles(). See
    clients/aep.py's list_flow_specs()/parse_flow_spec() docstrings for what
    isn't yet confirmed live about this one."""
    if settings.mock_mode:
        raw = mock.MOCK_FLOW_SPECS
    else:
        async def _load():
            async with aep_client._new_http_client() as http:  # noqa: SLF001
                return await aep_client.list_flow_specs(http)
        raw = run_async(_load())
    return {spec["flow_spec_id"]: spec["name"] for spec in (aep_api.parse_flow_spec(item) for item in raw) if spec["flow_spec_id"] and spec["name"]}


def fetch_dc() -> list[dict[str, Any]]:
    """One row per property, with its extensions/rules/libraries fetched and
    summarized. Reactor has no single "all properties" endpoint — this walks
    companies -> properties, same fan-out shape as the AEP flow/run walk."""
    if settings.mock_mode:
        properties_raw = mock.MOCK_PROPERTIES
        extensions_by_prop = mock.MOCK_EXTENSIONS
        rules_by_prop = mock.MOCK_RULES
        libraries_by_prop = mock.MOCK_LIBRARIES
        environments_by_prop = mock.MOCK_ENVIRONMENTS
        data_elements_by_prop = mock.MOCK_DATA_ELEMENTS
    else:
        async def _load():
            async with reactor_client._new_http_client() as http:  # noqa: SLF001
                companies = await reactor_client.list_companies(http)
                properties: list[dict[str, Any]] = []
                for company in companies:
                    properties.extend(await reactor_client.list_properties(http, company["id"]))
                extensions, rules, libraries, environments, data_elements = {}, {}, {}, {}, {}
                for prop in properties:
                    pid = prop["id"]
                    extensions[pid] = await reactor_client.list_extensions(http, pid)
                    rules[pid] = await reactor_client.list_rules(http, pid)
                    libraries[pid] = await reactor_client.list_libraries(http, pid)
                    environments[pid] = await reactor_client.list_environments(http, pid)
                    data_elements[pid] = await reactor_client.list_data_elements(http, pid)
                return properties, extensions, rules, libraries, environments, data_elements
        properties_raw, extensions_by_prop, rules_by_prop, libraries_by_prop, environments_by_prop, data_elements_by_prop = run_async(_load())

    rows: list[dict[str, Any]] = []
    for prop_raw in properties_raw:
        prop = reactor_api.parse_property(prop_raw)
        pid = prop["property_id"]
        extensions = [reactor_api.parse_extension(e) for e in extensions_by_prop.get(pid, [])]
        rules = [reactor_api.parse_rule(r) for r in rules_by_prop.get(pid, [])]
        libraries = [reactor_api.parse_library(lib) for lib in libraries_by_prop.get(pid, [])]
        environments = [reactor_api.parse_environment(e) for e in environments_by_prop.get(pid, [])]
        data_elements = [reactor_api.parse_data_element(d) for d in data_elements_by_prop.get(pid, [])]
        production_environments = [e for e in environments if e["stage"] == "production"]
        rows.append({
            **prop,
            "extensions": extensions,
            "extension_count": len(extensions),
            "extension_issue_count": sum(1 for e in extensions if e["has_issue"]),
            "rules": rules,
            "rule_count": len(rules),
            # Reactor's libraries list has no documented "most recent first"
            # ordering guarantee, so rather than assume index 0 is "the
            # current one" (and silently miss a failed build sitting
            # elsewhere in the list), every bad-state library is surfaced —
            # see library_issue_count and alerts.evaluate_dc().
            "libraries": libraries,
            "library_count": len(libraries),
            "library_issue_count": sum(1 for lib in libraries if lib["is_bad"]),
            "environments": environments,
            "environment_count": len(environments),
            # Adobe allows at most one "production" environment per
            # property (confirmed via docs) but that's not enforced
            # client-side — every bad one is surfaced, same reasoning as
            # libraries above, rather than assuming there's exactly one.
            "production_environment_issue_count": sum(1 for e in production_environments if e["is_bad"]),
            "data_elements": data_elements,
            "data_element_count": len(data_elements),
            "data_element_issue_count": sum(1 for d in data_elements if d["has_issue"]),
        })
    return rows


def fetch_cja_connections() -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.MOCK_CONNECTIONS
    else:
        async def _load():
            async with cja_client._new_http_client() as http:  # noqa: SLF001
                return await cja_client.list_connections(http)
        raw = run_async(_load())
    return [cja_api.parse_connection(item) for item in raw]


def fetch_cja_dataviews() -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.MOCK_DATAVIEWS
    else:
        async def _load():
            async with cja_client._new_http_client() as http:  # noqa: SLF001
                return await cja_client.list_dataviews(http)
        raw = run_async(_load())
    return [cja_api.parse_dataview(item) for item in raw]


def fetch_cja_dimensions(dataview_id: str) -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.MOCK_DIMENSIONS.get(dataview_id, [])
    else:
        async def _load():
            async with cja_client._new_http_client() as http:  # noqa: SLF001
                return await cja_client.list_dimensions(http, dataview_id)
        raw = run_async(_load())
    return [cja_api.parse_dimension(item) for item in raw]


def fetch_cja_metrics(dataview_id: str) -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.MOCK_METRICS.get(dataview_id, [])
    else:
        async def _load():
            async with cja_client._new_http_client() as http:  # noqa: SLF001
                return await cja_client.list_metrics(http, dataview_id)
        raw = run_async(_load())
    return [cja_api.parse_metric(item) for item in raw]


def fetch_cja_calculated_metrics(dataview_id: str) -> list[dict[str, Any]]:
    """Unlike fetch_cja_dimensions()/fetch_cja_metrics() above, Calculated
    Metrics has no documented per-data-view endpoint — this fetches the
    full org-wide list (cja_client.list_calculated_metrics()) and filters
    client-side by the confirmed `dataId` field, both in mock and live
    mode, so the two code paths behave identically."""
    if settings.mock_mode:
        raw = mock.MOCK_CALCULATED_METRICS
    else:
        async def _load():
            async with cja_client._new_http_client() as http:  # noqa: SLF001
                return await cja_client.list_calculated_metrics(http)
        raw = run_async(_load())
    parsed = [cja_api.parse_calculated_metric(item) for item in raw]
    return [m for m in parsed if m["dataview_id"] == dataview_id]


def fetch_cja_projects() -> list[dict[str, Any]]:
    """Every CJA Workspace project, org-wide — a cheap list call with no
    definitions (see fetch_cja_component_usage() below for the per-project
    definition fetch this feeds into)."""
    if settings.mock_mode:
        raw = mock.MOCK_PROJECTS
    else:
        async def _load():
            async with cja_client._new_http_client() as http:  # noqa: SLF001
                return await cja_client.list_projects(http)
        raw = run_async(_load())
    return [cja_api.parse_project(item) for item in raw]


def fetch_cja_dataset_lineage(sandbox: str | None = None) -> list[dict[str, Any]]:
    """One row per confirmed hop-by-hop path through the pipeline: XDM
    Schema -> AEP Dataset (via the dataset's own `schemaRef`, already used
    on the Datasets page/Compare) -> CJA Connection (via the connection's
    own `dataset_ids`, confirmed live via Adobe's docs — see clients/cja.py's
    parse_connection()) -> CJA Data View (via connection_id) -> CJA
    Project (via dataview_id). Each row is
    {schema, dataset, connection, dataview, project} with the *name*
    already resolved (never a raw id) — a stage with nothing downstream
    yet (a connection with no data views, a data view with no projects)
    still gets a row with that stage's rest left blank, rather than being
    dropped, so the Overview page's lineage view can show where the
    pipeline dead-ends, not just where it's fully wired end to end.

    Datasets and Schemas are sandbox-scoped (Catalog Service/Schema
    Registry); Connections/Data Views/Projects are org-wide (see
    fetch_sandbox_comparison()'s docstring) — so a connection's
    dataset_ids can reference a dataset from a *different* sandbox than
    the one passed in here, which this function has no way to detect
    (there's no "which sandbox is this dataset id in" lookup) and will
    just show as an unresolved id, same as any other permission-based gap
    this app already surfaces that way. A dataset that IS resolved but
    whose schema id doesn't resolve to a title falls back to the id's last
    URL segment — same convention as the Datasets page's own schema
    column, not the CJA permission-gap "(unresolved)" flag, since a
    missing schema title here is far more likely a different container/
    deleted schema than a permission problem. An unresolved *dataset*
    (the id came from a connection but fetch_datasets() never returned it)
    has no schema information at all to show, so that row's schema stage
    is left blank rather than guessed.

    Deliberately excludes Data Collection properties/rules/data elements
    — there is no public API for Datastream configuration (which DC
    property's Web SDK datastream sends to which dataset), so that link
    can't be discovered programmatically; the Overview page shows DC
    properties as a separate, explicitly-unconnected group instead of
    guessing at a link here."""
    schema_titles = fetch_schema_titles(sandbox=sandbox)
    datasets_by_id = {d["dataset_id"]: d for d in fetch_datasets(sandbox=sandbox)}
    connections = fetch_cja_connections()
    dataviews = fetch_cja_dataviews()
    projects = fetch_cja_projects()

    dataviews_by_conn: dict[str, list[dict[str, Any]]] = {}
    for dv in dataviews:
        dataviews_by_conn.setdefault(dv["connection_id"], []).append(dv)
    projects_by_dv: dict[str, list[dict[str, Any]]] = {}
    for p in projects:
        projects_by_dv.setdefault(p["dataview_id"], []).append(p)

    def _schema_label(schema_id: str) -> str:
        if not schema_id:
            return ""
        return schema_titles.get(schema_id, schema_id.rsplit("/", 1)[-1])

    rows: list[dict[str, Any]] = []
    for conn in connections:
        dataset_ids = conn.get("dataset_ids") or [""]  # still show the connection even with no known dataset
        conn_dataviews = dataviews_by_conn.get(conn["connection_id"], [])
        for dataset_id in dataset_ids:
            dataset = datasets_by_id.get(dataset_id)
            dataset_label = dataset["name"] if dataset else (f"{dataset_id} (unresolved)" if dataset_id else "—")
            schema_label = _schema_label(dataset["schema_id"]) if dataset else ""
            if not conn_dataviews:
                rows.append({"schema": schema_label, "dataset": dataset_label, "connection": conn["name"], "dataview": "", "project": ""})
                continue
            for dv in conn_dataviews:
                dv_projects = projects_by_dv.get(dv["dataview_id"], [])
                if not dv_projects:
                    rows.append({"schema": schema_label, "dataset": dataset_label, "connection": conn["name"], "dataview": dv["name"], "project": ""})
                    continue
                for p in dv_projects:
                    rows.append({
                        "schema": schema_label, "dataset": dataset_label, "connection": conn["name"],
                        "dataview": dv["name"], "project": p["name"],
                    })
    return rows


def fetch_property_datastream_edges(dc_rows: list[dict[str, Any]], sandbox: str | None = None) -> list[dict[str, Any]]:
    """{property, domains, environment, datastream_id, datastream, dataset,
    mapped} rows — the one remaining hop Overview's lineage chart can close
    without guessing at Adobe's undocumented Datastreams/EdgeConfig API
    (see README Known Limitations): a property's Web SDK extension already
    carries its own configured datastream id(s) in Reactor's own, fully
    public, already-used API (clients/reactor.py's parse_extension()/
    _extract_datastream_ids()). What's missing — a datastream's *name* and
    which dataset it forwards to — isn't exposed by any documented Adobe
    API at all, so it's closed with one small, git-ignored,
    human-maintained file instead (see datastream_map.py) — the one
    deliberate manual step in an otherwise fully-automated chain.

    Reported live: a single property can configure a genuinely *different*
    datastream per build environment (production/staging/development) —
    one row per (property, environment) pair with a configured id, not
    just one per property. Two environments happening to share the exact
    same underlying datastream id both still get their own row/label (kept
    distinguishable by environment) rather than being silently collapsed.

    Also reported live: two *separate extensions* on the same property can
    each configure their own "production" (etc.) instance with genuinely
    different datastream ids — every one still gets its own row, the
    environment label suffixed with the contributing extension's name only
    when they actually disagree (see the extension-merge loop below);
    an earlier version silently dropped every one past the first extension
    walked for a given environment string.

    Takes `dc_rows` (already-fetched property rows, e.g. from
    st.session_state) rather than fetching Data Collection itself — that
    fetch is already a full per-property walk over extensions/rules/
    libraries/environments/data_elements the DC page and Overview's
    refresh_all() already do; this just reuses it instead of duplicating
    that entire N+1 cost only to read one field off it.

    A property with no Web SDK extension (or no environment configured at
    all) contributes no row — nothing to chart for it. A datastream id
    with no entry in datastream_map.json still gets a row (`mapped=False`,
    `dataset=""`) rather than being silently dropped, so "this property's
    datastream isn't mapped yet" stays visible instead of just
    disappearing.

    The reverse gap, also reported live: a datastream_map.json entry whose
    id doesn't match *any* property's extracted datastream id at all (the
    property was deleted/reconfigured since the mapping was written, or
    the datastream was never tied to a Reactor property to begin with) —
    "a datastream with [a dataset] relationship should [still be]
    displayed" even with no property to show it under. Every such entry
    still gets its own row too (`property=""`, `mapped=True`), appended
    after the property walk below once every id it actually found is
    known — never silently invisible just because no property currently
    claims it.

    `domains` is the property's own `domains` attribute (confirmed via
    Adobe's Properties endpoint docs — an array of the web domains that
    load this property's library), passed through unchanged from
    parse_property() with no extra call or permission needed. A
    non-web-platform property (or one just missing the field) carries an
    empty list, not an error."""
    datastream_map = load_datastream_map()
    dataset_names = {d["dataset_id"]: d["name"] for d in fetch_datasets(sandbox=sandbox)}

    rows: list[dict[str, Any]] = []
    seen_datastream_ids: set[str] = set()
    for prop in dc_rows:
        # A property can have more than one extension with settings (rare,
        # but not impossible) — merge every environment found across all
        # of them rather than assuming exactly one extension carries them.
        #
        # Reported live: this used to merge via dict.setdefault(environment,
        # datastream_id), which silently *dropped* every extension's id for
        # an environment string beyond the first one walked — two separate
        # Web SDK extensions on the same property, each with its own
        # "production" instance but a genuinely different datastream id,
        # collapsed to whichever extension happened to come first, the
        # second one invisible with no error or indication anything was
        # lost. Collecting every (extension name, id, datastream id) triple
        # per environment first, then only disambiguating with a suffix
        # when two extensions actually disagree on the datastream id, fixes
        # that while still collapsing to one plain row when they happen to
        # agree (e.g. the same Web SDK extension appearing twice in
        # Reactor's response, which shouldn't manufacture a second row for
        # the exact same datastream).
        ids_by_env: dict[str, list[tuple[str, str, str]]] = {}
        for ext in prop.get("extensions", []):
            for environment, datastream_id in (ext.get("datastream_ids") or {}).items():
                ids_by_env.setdefault(environment, []).append((ext.get("name") or "", ext.get("extension_id") or "", datastream_id))

        datastream_ids: dict[str, str] = {}
        for environment, entries in ids_by_env.items():
            distinct_ids = {ds_id for _, _, ds_id in entries}
            if len(distinct_ids) == 1:
                datastream_ids[environment] = entries[0][2]
            else:
                # Extension *name* is Reactor's technical package slug
                # ("adobe-alloy"), not a user-facing label — two separate
                # installs of the same Web SDK extension share it, so name
                # alone can't disambiguate them; fall back to the
                # extension's own (always-unique) id whenever the names in
                # this colliding group aren't themselves all distinct.
                names = [name for name, _, _ in entries]
                names_are_unique = len(set(names)) == len(names)
                for idx, (ext_name, ext_id, ds_id) in enumerate(entries):
                    suffix = ext_name if (ext_name and names_are_unique) else (ext_id or f"extension {idx + 1}")
                    datastream_ids[f"{environment} ({suffix})"] = ds_id

        for environment, datastream_id in datastream_ids.items():
            seen_datastream_ids.add(datastream_id)
            mapped_entry = datastream_map.get(datastream_id)
            mapped_dataset_id = mapped_entry["dataset_id"] if mapped_entry else ""
            if mapped_entry:
                datastream_label = f"{mapped_entry['name'] or datastream_id} ({environment})"
                dataset_label = dataset_names.get(mapped_dataset_id, f"{mapped_dataset_id} (unresolved)" if mapped_dataset_id else "")
            else:
                datastream_label = f"{datastream_id} (unmapped, {environment})"
                dataset_label = ""
            rows.append({
                "property": prop["property_name"], "domains": list(prop.get("domains") or []),
                "environment": environment, "datastream_id": datastream_id,
                "datastream": datastream_label, "dataset": dataset_label, "mapped": mapped_entry is not None,
                # Raw, unformatted values kept alongside the display labels
                # above specifically for debugging a mapping that isn't
                # showing up as expected — reported live as needed to check
                # extracted ids directly against a real tenant's actual
                # Datastream/Dataset ids, not just the resolved display
                # text. See ui/overview.py's debug expander.
                "mapped_dataset_id": mapped_dataset_id,
            })

    # Reported live: a datastream_map.json entry with a real, human-written
    # mapping to a real dataset, but whose id was never actually extracted
    # from any property's Web SDK extension above — the property that once
    # used it may have been deleted/reconfigured since the mapping was
    # written, or the datastream was never tied to a Reactor property in
    # the first place (a server-side/direct-API datastream). These were
    # completely invisible anywhere in the app despite the mapping itself
    # resolving a real dataset — the same "never silently dropped"
    # treatment every other unmapped/unresolved case here already gets.
    # `property`/`domains`/`environment` are left blank rather than
    # fabricated — ui.overview._build_lineage_flowchart()'s _node() treats
    # a blank name as "no node", so this correctly skips the Property and
    # Website Domain stages entirely and links straight from Datastream to
    # Dataset, same honest dead-end/edge-skip treatment as every other
    # missing stage in that diagram.
    for datastream_id, entry in datastream_map.items():
        if datastream_id in seen_datastream_ids:
            continue
        dataset_label = dataset_names.get(entry["dataset_id"], f"{entry['dataset_id']} (unresolved)" if entry["dataset_id"] else "")
        rows.append({
            "property": "", "domains": [], "environment": "", "datastream_id": datastream_id,
            "datastream": f"{entry['name'] or datastream_id} (no property)",
            "dataset": dataset_label, "mapped": True, "mapped_dataset_id": entry["dataset_id"],
        })
    return rows


def fetch_rule_datastream_overrides(dc_rows: list[dict[str, Any]], sandbox: str | None = None) -> list[dict[str, Any]]:
    """{property, domains, environment, datastream_id, datastream, dataset,
    mapped, mapped_dataset_id, rule_id, rule_name, sandbox,
    sandbox_from_override} rows — same shape fetch_property_datastream_
    edges() produces plus two extra fields (`rule_name`, read by
    ui/overview.py to draw a Property → Rule → Datastream chain instead
    of a direct Property → Datastream edge), but closing a *different*
    gap: one rule's own action can override a property's default Web SDK
    datastream for just the events matching that rule (Adobe's "Send
    event" action, its "Datastream Configuration Overrides" — see
    reactor.py's _extract_rule_datastream_overrides()), which
    fetch_property_datastream_edges() can never see since it only ever
    reads the extension's own default `instances[]` settings. Reported
    live as the actual symptom this closes: a datastream used *only*
    through a rule override (never as any extension's default) still
    resolves a name/dataset via datastream_map.json, but had nowhere to
    attach to — it fell into that function's "(no property)" fallback
    despite genuinely belonging to a property, just reachable through one
    specific rule rather than the property's own default config.

    Called automatically alongside fetch_property_datastream_edges()
    every time the lineage chart is (re)built (ui/overview.py's
    _do_refresh_lineage()) — not a separate on-demand search. This is a
    real N (property) × M (rule) amount of extra Reactor calls on top of
    the six-leg walk fetch_dc() already does, on every sandbox change and
    every "Refresh everything" click; accepted deliberately (on request)
    so a rule-based override always shows up in the end-to-end flow
    without a separate action, even though most rules carry no override
    at all and the walk finds nothing for them. A rule component with no
    override contributes nothing to the result — this never surfaces
    "every rule on every property," only the ones that actually override
    something.

    One row per (rule, environment) pair — confirmed against a real
    tenant's Launch UI: the override is genuinely per-environment/sandbox
    (Development/Staging/Production each independently configured), not
    one flat value, exactly mirroring how fetch_property_datastream_
    edges() itself handles a property's default datastream carrying a
    different id per environment.

    Dataset resolution now uses each override's own **explicit** sandbox
    field when one was extracted (`sandbox_from_override=True`) — a
    literal fact read straight off the override, confirmed to exist in
    Adobe's own UI (each environment tab has its own "Sandbox" picker
    alongside its own "Datastream" picker) — rather than assuming
    whichever sandbox happens to be active in the sidebar. This is a real
    improvement over fetch_property_datastream_edges()'s own single-
    sandbox gap (that function's extension-level source has no such field
    to read at all): an override naming its own sandbox resolves
    correctly regardless of which sandbox is currently selected. Only
    when an override's sandbox couldn't be extracted
    (`sandbox_from_override=False` — either the fallback flat-key parse
    path, which carries no sandbox at all, or a genuinely blank field)
    does this fall back to whichever `sandbox` was passed in, the same
    inference-based gap every other lookup in this file has."""
    datastream_map = load_datastream_map()
    # One fetch_datasets() call per *distinct* sandbox actually named by
    # an override (typically small — often just one or two), not one per
    # row; cached here rather than in fetch_datasets() itself since this
    # is the only caller that ever needs more than the single active
    # sandbox in one pass.
    dataset_names_by_sandbox: dict[str, dict[str, str]] = {}

    def _dataset_names_for(sb: str) -> dict[str, str]:
        if sb not in dataset_names_by_sandbox:
            dataset_names_by_sandbox[sb] = {d["dataset_id"]: d["name"] for d in fetch_datasets(sandbox=sb)}
        return dataset_names_by_sandbox[sb]

    if settings.mock_mode:
        raw_triples = [
            (prop, rule, comp)
            for prop in dc_rows
            for rule in prop.get("rules", [])
            for comp in mock.MOCK_RULE_COMPONENTS.get(rule["rule_id"], [])
        ]
    else:
        async def _load():
            triples = []
            async with reactor_client._new_http_client() as http:  # noqa: SLF001
                for prop in dc_rows:
                    for rule in prop.get("rules", []):
                        components = await reactor_client.list_rule_components(http, prop["property_id"], rule["rule_id"])
                        for comp in components:
                            triples.append((prop, rule, comp))
            return triples
        raw_triples = run_async(_load())

    rows: list[dict[str, Any]] = []
    for prop, rule, comp in raw_triples:
        parsed = reactor_api.parse_rule_component(comp, rule["rule_id"], rule["name"])
        for environment, override in parsed["datastream_overrides"].items():
            datastream_id = override["datastream_id"]
            sandbox_from_override = bool(override["sandbox"])
            effective_sandbox = override["sandbox"] or (sandbox or "")
            mapped_entry = datastream_map.get(datastream_id)
            mapped_dataset_id = mapped_entry["dataset_id"] if mapped_entry else ""
            label_suffix = f"via rule: {rule['name']} ({environment})"
            if mapped_entry:
                datastream_label = f"{mapped_entry['name'] or datastream_id} ({label_suffix})"
                dataset_label = _dataset_names_for(effective_sandbox).get(
                    mapped_dataset_id, f"{mapped_dataset_id} (unresolved)" if mapped_dataset_id else "",
                )
            else:
                datastream_label = f"{datastream_id} (unmapped, {label_suffix})"
                dataset_label = ""
            rows.append({
                "property": prop["property_name"], "domains": list(prop.get("domains") or []),
                "environment": environment, "datastream_id": datastream_id,
                "datastream": datastream_label, "dataset": dataset_label, "mapped": mapped_entry is not None,
                "mapped_dataset_id": mapped_dataset_id, "rule_id": rule["rule_id"], "rule_name": rule["name"],
                "sandbox": effective_sandbox, "sandbox_from_override": sandbox_from_override,
            })
    return rows


_NON_COMPONENT_ENTITY_TYPES = {"ReportSuite", "DateRange"}


def fetch_cja_project_entity_references(dataview_id: str) -> list[dict[str, Any]]:
    """Every raw {id, type, name, project_id, project_name} entity
    reference extracted from every CJA Workspace project bound to this
    data view — the unaggregated form fetch_cja_component_usage() builds
    its usage map from below, exposed on its own for the SDR page's debug
    view. Whether nothing shows up as "used" is because no projects were
    found for this data view, because projects were found but nothing in
    their definitions was tagged `__entity__` (the extraction assumption
    itself may not hold for a populated project — only an empty test one
    was available to confirm the marker against), or because entities
    *were* found but their `id` values don't match a known component's own
    id — this function's raw output is what tells those apart; the
    aggregated usage map alone can't.

    One fetch_cja_projects() call plus one get_project(expansion=definition)
    call per project bound to this data view — N+1 by nature (Adobe's
    projects endpoint has no "give me every definition in one call"
    option). Filtered to this data view client-side — fetch_cja_projects()
    already returns every project org-wide, and Adobe's docs don't confirm
    a dataId filter query param for the list endpoint to push that
    filtering server-side instead."""
    projects = [p for p in fetch_cja_projects() if p["dataview_id"] == dataview_id]

    if settings.mock_mode:
        definitions = {p["project_id"]: mock.MOCK_PROJECT_DEFINITIONS.get(p["project_id"], {}) for p in projects}
    else:
        async def _load():
            async with cja_client._new_http_client() as http:  # noqa: SLF001
                result: dict[str, Any] = {}
                for p in projects:
                    full = await cja_client.get_project(http, p["project_id"])
                    result[p["project_id"]] = full.get("definition") if isinstance(full, dict) else {}
                return result
        definitions = run_async(_load())

    rows: list[dict[str, Any]] = []
    for p in projects:
        definition = definitions.get(p["project_id"]) or {}
        for ref in cja_api.extract_entity_references(definition):
            rows.append({**ref, "project_id": p["project_id"], "project_name": p["name"]})
    return rows


def aggregate_component_usage(entity_references: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{component_id: {"name", "type", "projects": [project names]}},
    built from fetch_cja_project_entity_references()'s raw rows — a plain
    function (not fetching anything itself) so a caller that already has
    the raw references (e.g. the SDR page's debug view, which needs them
    for display anyway) can derive the aggregated usage map from the same
    fetch instead of triggering a second N+1 round of API calls. Excludes
    "ReportSuite"/"DateRange" entity types — confirmed live (from a real
    project's definition) as panel *framing* (which data view / date
    range a panel uses), not a shared component in the sense this view is
    meant to surface."""
    usage: dict[str, dict[str, Any]] = {}
    for ref in entity_references:
        if not ref["id"] or ref["type"] in _NON_COMPONENT_ENTITY_TYPES:
            continue
        entry = usage.setdefault(ref["id"], {"name": ref["name"], "type": ref["type"], "projects": []})
        if ref["project_name"] not in entry["projects"]:
            entry["projects"].append(ref["project_name"])
    return usage


def fetch_cja_component_usage(dataview_id: str) -> dict[str, dict[str, Any]]:
    """{component_id: {"name", "type", "projects": [project names]}} for
    every dimension/metric/calculated-metric/etc. referenced by any CJA
    Workspace project bound to this data view — lets SDR's Component Usage
    view show what's actually *in use* (and, by omission, what isn't)
    rather than just what's defined. Fetches once via
    fetch_cja_project_entity_references() and aggregates via
    aggregate_component_usage() above; a caller that also needs the raw
    per-reference rows (e.g. for a debug view) should call those two
    separately instead of this, to avoid fetching twice."""
    return aggregate_component_usage(fetch_cja_project_entity_references(dataview_id))


def fetch_schemas(sandbox: str | None = None) -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.MOCK_SCHEMAS
    else:
        async def _load():
            async with schema_registry_client._new_http_client() as http:  # noqa: SLF001
                return await schema_registry_client.list_schemas(http, sandbox=sandbox)
        raw = run_async(_load())
    return [schema_registry_api.parse_schema_summary(item) for item in raw]


def fetch_schema_titles(sandbox: str | None = None) -> dict[str, str]:
    """{schema_id: title} for the given sandbox — the resolver every page
    that shows a dataset's schema binding uses to display the schema's
    actual title (e.g. "Loyalty Events") instead of its raw $id/slug, the
    same "resolve the id to a name for display" pattern cja_page.py already
    uses for connection_id -> connection name."""
    return {s["schema_id"]: s["title"] for s in fetch_schemas(sandbox=sandbox)}


def fetch_datasets(sandbox: str | None = None) -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.mock_datasets_for_sandbox(sandbox or "")
    else:
        async def _load():
            async with catalog_client._new_http_client() as http:  # noqa: SLF001
                return await catalog_client.list_datasets(http, sandbox=sandbox)
        raw = run_async(_load())
    # ID-keyed object, not an array — see catalog.py's module docstring.
    return [catalog_api.parse_dataset(dataset_id, item) for dataset_id, item in raw.items()]


def fetch_schema_fields(schema_id: str, sandbox: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(flattened fields, raw schema) — the raw response is returned
    alongside the parsed fields (not fetched separately) so the SDR page's
    "raw response" debug expander doesn't cost a second live call; this is
    the newest, least-verified integration in the app (see README), so
    that raw view matters more here than on most other pages."""
    if settings.mock_mode:
        raw = mock.mock_schema_fields_for_sandbox(schema_id, sandbox or "")
    else:
        async def _load():
            async with schema_registry_client._new_http_client() as http:  # noqa: SLF001
                return await schema_registry_client.get_schema(http, schema_id, sandbox=sandbox)
        raw = run_async(_load())
    return schema_registry_api.flatten_fields(raw), raw


def fetch_label_descriptors(sandbox: str | None = None) -> list[dict[str, Any]]:
    """Every parsed xdm:descriptorLabel descriptor for one sandbox
    (unfiltered by schema/field) — the shared fetch behind
    fetch_schema_field_labels() below, also exposed on its own for the SDR
    page's debug expander so a user can see exactly what Adobe returned
    (raw sourceSchema/sourceProperty/labels, count) when labels aren't
    showing up as expected, without needing external tooling. Labels are
    sandbox-scoped (`x-sandbox-name`) — a descriptor recorded against a
    different sandbox than the one currently selected simply won't be in
    this list at all, which looks identical to "no labels configured" from
    the caller's side; the debug expander's descriptor count is the way to
    tell those apart."""
    if settings.mock_mode:
        items = schema_registry_api.extract_label_descriptors(mock.MOCK_DESCRIPTORS)
    else:
        async def _load():
            async with schema_registry_client._new_http_client() as http:  # noqa: SLF001
                return await schema_registry_client.list_label_descriptors(http, sandbox=sandbox)
        items = run_async(_load())
    return [schema_registry_api.parse_label_descriptor(item) for item in items]


def fetch_schema_field_labels(field_paths: set[str] | list[str], sandbox: str | None = None) -> dict[str, list[str]]:
    """{flattened field path: [DULE label codes]}, restricted to whichever
    paths are passed in — the field paths of ONE schema, from
    fetch_schema_fields() — so the SDR page's schema fields table can show
    what data-governance labels (Identifiable/Sensitive/Contract data,
    etc.) are applied per field. Labels live on separate Descriptor
    objects (xdm:descriptorLabel), not on the field definition itself, so
    this is a second call alongside fetch_schema_fields() rather than
    something flatten_fields() could pull out of the schema response.

    Matches by field *path*, not by the descriptor's own `xdm:sourceSchema`
    — confirmed live that field is a *field group* id (e.g.
    ".../mixins/xxxx"), not the schema's own $id, and the "full resolved"
    schema response doesn't expose which field groups compose a schema (no
    `allOf`), so there's no way to filter by sourceSchema correctly. Path
    matching sidesteps that: flatten_fields() already merges every field
    group's properties into one flat tree per schema, so a labeled field
    shows up correctly here even when its label lives on a field group
    shared across multiple schemas — which is the normal, intentional XDM
    pattern, not an edge case. See clients/schema_registry.py's
    list_label_descriptors()/extract_label_descriptors() docstrings for
    what else is confirmed vs. not."""
    known_paths = set(field_paths)
    labels_by_path: dict[str, list[str]] = {}
    for parsed in fetch_label_descriptors(sandbox=sandbox):
        if parsed["path"] not in known_paths or not parsed["labels"]:
            continue
        labels_by_path.setdefault(parsed["path"], []).extend(parsed["labels"])
    return labels_by_path


def fetch_observability_metrics(days: int = 7, sandbox: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Adobe's own org/sandbox-wide historical metrics — richer than this
    app's own accumulated polling history, see clients/observability.py."""
    if settings.mock_mode:
        raw = mock.MOCK_OBSERVABILITY_METRICS
    else:
        async def _load():
            async with observability_client._new_http_client() as http:  # noqa: SLF001
                return await observability_client.get_metrics(http, observability_api.DEFAULT_HEALTH_METRICS, days=days, sandbox=sandbox)
        raw = run_async(_load())
    return observability_api.parse_metrics_response(raw)


def fetch_quotas() -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.MOCK_QUOTAS
    else:
        async def _load():
            async with quota_client._new_http_client() as http:  # noqa: SLF001
                return await quota_client.list_quotas(http)
        raw = run_async(_load())
    return [quota_api.parse_quota(item) for item in raw]


def fetch_segments(sandbox: str | None = None) -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.MOCK_SEGMENTS
    else:
        async def _load():
            async with segmentation_client._new_http_client() as http:  # noqa: SLF001
                return await segmentation_client.list_segments(http, sandbox=sandbox)
        raw = run_async(_load())
    return [segmentation_api.parse_segment(item) for item in raw]


def fetch_segment_jobs(sandbox: str | None = None) -> list[dict[str, Any]]:
    """Recent segment evaluation jobs, org/sandbox-wide (not filtered to one
    segment) — one row per job, newest first per the API's documented sort.
    A failed job here is very often the real cause of "the audience never
    reached the destination," upstream of the activation flow itself (see
    aep.py's parse_flow() docstring)."""
    segment_names = {s["segment_id"]: s["name"] for s in fetch_segments(sandbox=sandbox)}
    if settings.mock_mode:
        raw = mock.MOCK_SEGMENT_JOBS
    else:
        async def _load():
            async with segmentation_client._new_http_client() as http:  # noqa: SLF001
                return await segmentation_client.list_segment_jobs(http, sandbox=sandbox)
        raw = run_async(_load())
    rows = [segmentation_api.parse_segment_job(item) for item in raw]
    for row in rows:
        row["segment_name"] = segment_names.get(row["segment_id"], row["segment_id"] or "—")
    return rows


def fetch_queries(sandbox: str | None = None) -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.MOCK_QUERIES
    else:
        async def _load():
            async with query_service_client._new_http_client() as http:  # noqa: SLF001
                return await query_service_client.list_queries(http, sandbox=sandbox)
        raw = run_async(_load())
    rows = [query_service_api.parse_query(item) for item in raw]
    display_names = fetch_user_display_names()
    for row in rows:
        row["user_display_name"] = display_names.get(row["user_id"]) or (f"{row['user_id']} (unresolved)" if row["user_id"] else "—")
    return rows


def fetch_user_display_names() -> dict[str, str]:
    """{user_id: display_name} — resolves Query Service's opaque `userId`
    via a separate Adobe User Management API call, since Query Service's
    own API has no built-in resolution for this (confirmed via Adobe's
    docs — see clients/user_management.py's module docstring).

    Deliberately does NOT refetch on every call the way every other
    resolver in this app does (e.g. fetch_schema_titles()) — User
    Management API's own rate limit (25 req/min per client) is the
    strictest of any API this app talks to, and an org's user directory
    changes rarely, so the result is cached in aep_monitor.db and only
    refetched once settings.user_directory_cache_hours has passed (see
    database.replace_user_directory()/user_directory_fetched_at()).

    A fetch failure here (a real, expected case — see README: this needs a
    separate Developer Console API grant most setups won't have added yet)
    is caught and logged rather than propagated, so a missing/unconfigured
    grant degrades to "every userId stays unresolved" instead of breaking
    Query Service's own page."""
    cached_at = database.user_directory_fetched_at()
    is_stale = True
    if cached_at:
        try:
            age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(cached_at)).total_seconds() / 3600
            is_stale = age_hours >= settings.user_directory_cache_hours
        except ValueError:
            is_stale = True

    if is_stale:
        try:
            if settings.mock_mode:
                raw = mock.MOCK_USERS
            else:
                async def _load():
                    async with user_management_client._new_http_client() as http:  # noqa: SLF001
                        return await user_management_client.list_users(http)
                raw = run_async(_load())
            database.replace_user_directory([user_management_api.parse_user(item) for item in raw])
        except Exception:
            get_logger().warning("User directory refresh failed — Query Service's userId will show unresolved", exc_info=True)

    return {u["user_id"]: u["display_name"] for u in database.read_user_directory() if u["user_id"] and u["display_name"]}


def fetch_query_schedules(sandbox: str | None = None) -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.MOCK_SCHEDULES
    else:
        async def _load():
            async with query_service_client._new_http_client() as http:  # noqa: SLF001
                return await query_service_client.list_schedules(http, sandbox=sandbox)
        raw = run_async(_load())
    return [query_service_api.parse_schedule(item) for item in raw]


def fetch_sandbox_comparison() -> list[dict[str, Any]]:
    """One summary row per sandbox in settings.sandbox_list — AEP flow/run
    health plus Observability Insights totals. Only AEP is actually
    sandbox-scoped in Adobe's architecture (Data Collection, CJA, and Quota
    are org-wide), so this is the only page that varies by sandbox. One
    sandbox failing to fetch doesn't abort the others — its row carries the
    error message instead."""
    rows: list[dict[str, Any]] = []
    for sandbox in settings.sandbox_list:
        try:
            if settings.mock_mode:
                aep_summary = mock.mock_aep_summary_for_sandbox(sandbox)
                obs_summary = mock.mock_observability_summary_for_sandbox(sandbox)
            else:
                flows = fetch_aep(sandbox=sandbox)
                # Same failure criteria as alerts.evaluate_aep — a flow whose
                # latest run has a nonzero (above-threshold) failed-record
                # count is "failing" here too, not just an explicit
                # failed/error status, so this count can't understate a
                # sandbox that alerts.py would flag elsewhere in the app.
                def _is_failing(row: dict[str, Any]) -> bool:
                    latest = row.get("latest_run") or {}
                    status_failed = latest.get("status") in {"failed", "error"}
                    failed_records = int(latest.get("records_failed") or 0)
                    return status_failed or failed_records > settings.alert_failed_records_threshold
                failing = sum(1 for r in flows if _is_failing(r))
                records_failed = sum(int((r.get("latest_run") or {}).get("records_failed") or 0) for r in flows)
                aep_summary = {"sandbox": sandbox, "flow_count": len(flows), "failing_count": failing, "records_failed": records_failed}

                async def _load_metrics():
                    async with observability_client._new_http_client() as http:  # noqa: SLF001
                        return await observability_client.get_metrics(http, observability_api.DEFAULT_HEALTH_METRICS, days=1, sandbox=sandbox)
                metrics = observability_api.parse_metrics_response(run_async(_load_metrics()))
                success_points = metrics.get("timeseries.ingestion.dataset.recordsuccess.count", [])
                failed_points = metrics.get("timeseries.ingestion.dataset.batchfailed.count", [])
                obs_summary = {
                    "sandbox": sandbox,
                    "recordsuccess": success_points[-1]["value"] if success_points else None,
                    "batchfailed": failed_points[-1]["value"] if failed_points else None,
                }
            rows.append({**aep_summary, **{k: v for k, v in obs_summary.items() if k != "sandbox"}, "error": None})
        except Exception as exc:
            rows.append({"sandbox": sandbox, "flow_count": None, "failing_count": None, "records_failed": None, "recordsuccess": None, "batchfailed": None, "error": str(exc)})
    return rows


def fetch_schema_diff(schema_id_a: str, sandbox_a: str, schema_id_b: str, sandbox_b: str) -> dict[str, Any]:
    """Diff two schemas' fields — the common case is the same schema across
    two sandboxes, but the two sides are independent: any schema in
    sandbox A vs. any schema in sandbox B, including genuinely different
    schemas. The caller (compare_page.py) resolves schema_id per sandbox
    from that sandbox's own schema list — $id differs per sandbox even
    for what's conceptually "the same" schema, so there's no lookup-by-title
    here; the UI handles defaulting both sides to a matching title."""
    fields_a, _ = fetch_schema_fields(schema_id_a, sandbox=sandbox_a)
    fields_b, _ = fetch_schema_fields(schema_id_b, sandbox=sandbox_b)
    return {"diff": diffing.diff_by_key(fields_a, fields_b, key="path", compare_fields=["type", "title", "description"])}


def fetch_schema_drift(schema_id: str, sandbox: str, schema_title: str) -> dict[str, Any]:
    """Diff a schema's current fields against its own last-recorded
    snapshot ("vs. last snapshot" mode in Compare), rather than against
    another sandbox/schema. entity_key is scoped by sandbox — the same
    $id can legitimately have different fields per sandbox, and this
    should never conflate them into one drift history. Always records the
    current state as the new latest snapshot (whether or not a baseline
    existed), so the *next* call's baseline is *this* call's current state."""
    fields, _ = fetch_schema_fields(schema_id, sandbox=sandbox)
    baseline = database.latest_entity_snapshot("schema", f"{sandbox}::{schema_id}")
    database.record_entity_snapshot("schema", f"{sandbox}::{schema_id}", schema_title, fields)
    if baseline is None:
        return {"has_baseline": False, "baseline_checked_at": None}
    diff = diffing.diff_by_key(baseline["payload"], fields, key="path", compare_fields=["type", "title", "description"])
    return {"has_baseline": True, "baseline_checked_at": baseline["checked_at"], "diff": diff}


_DATASET_COMPARE_FIELDS = [
    ("name", "Name"), ("description", "Description"), ("schema_id", "Schema"),
    ("profile_enabled", "Profile-enabled"), ("identity_enabled", "Identity-enabled"),
]
# created_at/updated_at deliberately excluded — they differ on essentially
# every real comparison (any ingest touches updated_at) and would swamp
# "no differences" with noise that isn't a meaningful configuration drift,
# unlike every other field here.


def fetch_dataset_diff(dataset_id_a: str, sandbox_a: str, dataset_id_b: str, sandbox_b: str) -> dict[str, Any]:
    """Diff two datasets' attributes. Unlike fetch_schema_diff()/
    fetch_dc_property_diff() (which compare *lists* of named sub-items via
    diffing.diff_by_key), a dataset is a single flat object with a handful
    of scalar fields — there's no natural "only in A" bucket for a dataset's
    own name or schema binding, just "does this field differ" — so this
    returns a plain list of {field, label, value_a, value_b, changed} rows
    instead of reusing diff_by_key's only_a/only_b/common shape."""
    datasets_a = {d["dataset_id"]: d for d in fetch_datasets(sandbox=sandbox_a)}
    datasets_b = {d["dataset_id"]: d for d in fetch_datasets(sandbox=sandbox_b)}
    dataset_a, dataset_b = datasets_a.get(dataset_id_a), datasets_b.get(dataset_id_b)
    if dataset_a is None or dataset_b is None:
        return {"found_a": dataset_a is not None, "found_b": dataset_b is not None}
    rows = [
        {"field": field, "label": label, "value_a": dataset_a.get(field), "value_b": dataset_b.get(field), "changed": dataset_a.get(field) != dataset_b.get(field)}
        for field, label in _DATASET_COMPARE_FIELDS
    ]
    return {"found_a": True, "found_b": True, "rows": rows}


def fetch_dataset_drift(dataset_id: str, sandbox: str, dataset_name: str) -> dict[str, Any]:
    """Diff a dataset's current attributes against its own last-recorded
    snapshot. Same row-based shape as fetch_dataset_diff() (a dataset is a
    flat object, not a list of sub-items), but the "other side" is a stored
    payload dict instead of a second live-fetched dataset."""
    datasets = {d["dataset_id"]: d for d in fetch_datasets(sandbox=sandbox)}
    dataset = datasets.get(dataset_id)
    if dataset is None:
        return {"found": False}
    payload = {field: dataset.get(field) for field, _ in _DATASET_COMPARE_FIELDS}
    baseline = database.latest_entity_snapshot("dataset", f"{sandbox}::{dataset_id}")
    database.record_entity_snapshot("dataset", f"{sandbox}::{dataset_id}", dataset_name, payload)
    if baseline is None:
        return {"found": True, "has_baseline": False, "baseline_checked_at": None}
    baseline_payload = baseline["payload"]
    rows = [
        {"field": field, "label": label, "value_a": baseline_payload.get(field), "value_b": payload.get(field), "changed": baseline_payload.get(field) != payload.get(field)}
        for field, label in _DATASET_COMPARE_FIELDS
    ]
    return {"found": True, "has_baseline": True, "baseline_checked_at": baseline["checked_at"], "rows": rows}


def fetch_dc_property_diff(property_id_a: str, property_id_b: str) -> dict[str, Any]:
    """Diff two Data Collection properties' extensions/rules/libraries/
    environments/data elements. Fetches the full property list once (no
    per-property-only lookup exists for these in this app) and picks the
    two requested rows."""
    rows = fetch_dc()
    row_a = next((r for r in rows if r["property_id"] == property_id_a), None)
    row_b = next((r for r in rows if r["property_id"] == property_id_b), None)
    if row_a is None or row_b is None:
        return {"found_a": row_a is not None, "found_b": row_b is not None}
    return {
        "found_a": True,
        "found_b": True,
        "extensions": diffing.diff_by_key(row_a["extensions"], row_b["extensions"], key="name", compare_fields=["review_status", "published"]),
        "rules": diffing.diff_by_key(row_a["rules"], row_b["rules"], key="name", compare_fields=["enabled", "published"]),
        "libraries": diffing.diff_by_key(row_a["libraries"], row_b["libraries"], key="name", compare_fields=["state"]),
        "environments": diffing.diff_by_key(row_a["environments"], row_b["environments"], key="name", compare_fields=["status"]),
        "data_elements": diffing.diff_by_key(row_a["data_elements"], row_b["data_elements"], key="name", compare_fields=["published", "dirty", "review_status"]),
    }


_DC_DRIFT_COMPONENTS = [
    ("extensions", "name", ["review_status", "published"]),
    ("rules", "name", ["enabled", "published"]),
    ("libraries", "name", ["state"]),
    ("environments", "name", ["status"]),
    ("data_elements", "name", ["published", "dirty", "review_status"]),
]


def fetch_dc_property_drift(property_id: str) -> dict[str, Any]:
    """Diff a Data Collection property's extensions/rules/libraries/
    environments/data elements against its own last-recorded snapshot.
    Property label is derived from fetch_dc()'s own row rather than taken
    as a parameter — unlike schemas/datasets/data views, DC properties
    aren't sandbox-scoped and fetch_dc() already returns the name for free."""
    rows = fetch_dc()
    row = next((r for r in rows if r["property_id"] == property_id), None)
    if row is None:
        return {"found": False}
    payload = {component: row[component] for component, _, _ in _DC_DRIFT_COMPONENTS}
    baseline = database.latest_entity_snapshot("dc_property", property_id)
    database.record_entity_snapshot("dc_property", property_id, row["property_name"], payload)
    if baseline is None:
        return {"found": True, "has_baseline": False, "baseline_checked_at": None}
    baseline_payload = baseline["payload"]
    result: dict[str, Any] = {"found": True, "has_baseline": True, "baseline_checked_at": baseline["checked_at"]}
    for component, key, compare_fields in _DC_DRIFT_COMPONENTS:
        result[component] = diffing.diff_by_key(baseline_payload[component], payload[component], key=key, compare_fields=compare_fields)
    return result


def fetch_cja_dataview_diff(dataview_id_a: str, dataview_id_b: str) -> dict[str, Any]:
    """Diff two CJA data views' dimensions, metrics, and calculated metrics."""
    dims_a, dims_b = fetch_cja_dimensions(dataview_id_a), fetch_cja_dimensions(dataview_id_b)
    metrics_a, metrics_b = fetch_cja_metrics(dataview_id_a), fetch_cja_metrics(dataview_id_b)
    calc_metrics_a, calc_metrics_b = fetch_cja_calculated_metrics(dataview_id_a), fetch_cja_calculated_metrics(dataview_id_b)
    return {
        "dimensions": diffing.diff_by_key(dims_a, dims_b, key="name", compare_fields=["type", "approved"]),
        "metrics": diffing.diff_by_key(metrics_a, metrics_b, key="name", compare_fields=["type", "approved"]),
        "calculated_metrics": diffing.diff_by_key(calc_metrics_a, calc_metrics_b, key="name", compare_fields=["type", "polarity"]),
    }


_CJA_DRIFT_COMPONENTS = [
    ("dimensions", "name", ["type", "approved"]),
    ("metrics", "name", ["type", "approved"]),
    ("calculated_metrics", "name", ["type", "polarity"]),
]


def fetch_cja_dataview_drift(dataview_id: str, dataview_name: str) -> dict[str, Any]:
    """Diff a CJA data view's dimensions/metrics/calculated metrics against
    its own last-recorded snapshot. dataview_name is taken as a parameter
    (unlike fetch_dc_property_drift(), which derives its label from
    fetch_dc()'s own row) because none of fetch_cja_dimensions()/
    fetch_cja_metrics()/fetch_cja_calculated_metrics() return the data
    view's own name — only fetch_cja_dataviews() does, and the caller
    (compare_page.py) already has that list loaded."""
    payload = {
        "dimensions": fetch_cja_dimensions(dataview_id),
        "metrics": fetch_cja_metrics(dataview_id),
        "calculated_metrics": fetch_cja_calculated_metrics(dataview_id),
    }
    baseline = database.latest_entity_snapshot("cja_dataview", dataview_id)
    database.record_entity_snapshot("cja_dataview", dataview_id, dataview_name, payload)
    if baseline is None:
        return {"has_baseline": False, "baseline_checked_at": None}
    baseline_payload = baseline["payload"]
    result: dict[str, Any] = {"has_baseline": True, "baseline_checked_at": baseline["checked_at"]}
    for component, key, compare_fields in _CJA_DRIFT_COMPONENTS:
        result[component] = diffing.diff_by_key(baseline_payload[component], payload[component], key=key, compare_fields=compare_fields)
    return result


def fetch_audit_events(limit: int = 50, sandbox: str | None = None) -> list[dict[str, Any]]:
    if settings.mock_mode:
        raw = mock.MOCK_AUDIT_EVENTS
    else:
        async def _load():
            async with audit_client._new_http_client() as http:  # noqa: SLF001
                return await audit_client.list_events(http, limit=limit, sandbox=sandbox)
        raw = run_async(_load())
    return [audit_api.parse_event(item) for item in raw]


def fetch_dc_audit_events(limit: int = 50) -> list[dict[str, Any]]:
    """Reactor is org-wide, not sandbox-scoped — no sandbox param, same as
    every other Data Collection fetch in this module."""
    if settings.mock_mode:
        raw = mock.MOCK_DC_AUDIT_EVENTS
    else:
        async def _load():
            async with reactor_client._new_http_client() as http:  # noqa: SLF001
                return await reactor_client.list_audit_events(http, page_size=limit)
        raw = run_async(_load())
    return [reactor_api.parse_audit_event(item) for item in raw]


def fetch_cja_audit_logs(limit: int = 50) -> list[dict[str, Any]]:
    """CJA is org-wide too — no sandbox param."""
    if settings.mock_mode:
        raw = mock.MOCK_CJA_AUDIT_LOGS
    else:
        async def _load():
            async with cja_client._new_http_client() as http:  # noqa: SLF001
                return await cja_client.list_audit_logs(http, page_size=limit)
        raw = run_async(_load())
    return [cja_api.parse_audit_log(item) for item in raw]
