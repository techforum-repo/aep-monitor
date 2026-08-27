# Adobe Experience Cloud Monitor

A single Streamlit dashboard for **AEP** (dataflow ingestion health, plus
Adobe's own Observability Insights metrics and Data Lifecycle quota usage),
**Data Collection / Tags** (property, extension & publish status), and
**CJA** (connections & data views) — with history charts, self-clearing
alerts, a side-by-side sandbox comparison, an audit-log view, and an
offline mock mode so it's explorable before any Adobe credential exists.

Sibling of [`adobe-access-manager`](../adobe-access-manager) — same
conventions (pydantic-settings config, mock/live client split, hardened
local SQLite storage, friendly error boxes), extended from user
provisioning to cross-product monitoring.

## What it watches

| Page | API | Signal |
|---|---|---|
| **Overview** | all of the below | One screen: open-alert banner, a summary card per product, a data-lifecycle quota breakdown, and an end-to-end data flow — one Graphviz flowchart, one connection at a time, covering Website domain → Property → Datastream → XDM Schema → AEP Dataset → CJA Connection → Data View → Project — the Website/Property/Datastream hops closed via Reactor plus a small git-ignored mapping file, since no public Adobe API exposes that link |
| **AEP Ingestion** | Flow Service | Per-dataflow run status, record volume, failed records, history trend — plus a **Connector** column resolving each flow's `flowSpec` to a display name, since `/flows` returns inbound ingestion and outbound activation flows undifferentiated (see Known Limitations) |
| **AEP Ingestion** (org-wide section) | Observability Insights | Adobe's own sandbox-wide historical metrics — independent of, and richer than, this app's own per-flow polling |
| **Datasets** | Catalog Service | Dataset metadata, the schema each dataset is bound to, Profile/Identity enablement — follows the sandbox switcher |
| **Data Collection** | Reactor | Extension review status, rule state, every library's build state (not just an assumed "latest" one — see limitations), environment build status (dev/staging/**production**), data element publish state |
| **CJA** | CJA APIs | Connection status, data views built on each connection, and Workspace projects built on those data views |
| **Segments** | Segmentation Service (Unified Profile) | Segment definitions and recent segment evaluation jobs — the layer between ingestion and activation that was previously unwatched; a failed job here is very often the real cause of "the audience never reached the destination" (see Known Limitations — newest, least-verified integration) |
| **Query Service** | Query Service + User Management API (optional) | Recent ad-hoc/scheduled queries against the data lake — status, row count, elapsed time, and the actual SQL text per query (a "Query detail" picker, not a table column), who ran it (**"Run by"**, resolved to a name via a separate, optional User Management API call — see Known Limitations) — plus which queries are on a schedule |
| **Compare** | Flow Service + Observability + Schema Registry + Catalog + Reactor + CJA | Five comparison tabs — Sandboxes, Schemas, and Datasets are actual sandbox comparisons; DC Properties and CJA Data Views compare two picked entities instead (both are org-wide). Adobe has no built-in tool for any of these. |
| **SDR** | CJA Dimensions/Metrics/Calculated Metrics/Projects + Schema Registry (fields + Descriptors) | A live, auto-generated Solution Design Reference — browsable/exportable CJA data-view components and flattened AEP schema fields (with any data-governance labels applied per field), plus which components are actually referenced by a CJA Workspace project (and which aren't), pulled from reality instead of a hand-maintained doc that drifts |
| **Audit Log** | Audit Query + Reactor Audit Events + CJA Audit Logs | Who changed what and when, across all three products (best-effort — see below) |
| **Alerts** | (derived) | Failed runs, rejected extensions, failed builds, unhealthy connections, near-limit quotas — self-clearing, optional Slack push |
| **Diagnostics** | all clients | Per-product connection test, local SQLite health, log download |
| **Settings** | (config) | Effective configuration (secrets masked) — credential, thresholds, base URLs |

## Sandbox switcher

A sidebar dropdown (populated from `ADOBE_SANDBOXES`, or just `ADOBE_SANDBOX`
alone if that's not set) picks the **active AEP sandbox** for the whole app —
Overview's AEP card, AEP Ingestion (including its Observability Insights
section), Segments, Query Service, Datasets, Audit Log, and SDR's AEP schema
section all follow it, refetching automatically when it changes. It's
session-only — it never writes back to `.env`. Data Collection, CJA, and the
Quota page are org-wide in Adobe's architecture, so they ignore it entirely;
Compare's Sandboxes, Schemas, and Datasets tabs ignore it too, since all
three let you pick sandboxes explicitly and are inherently multi-sandbox
already via `ADOBE_SANDBOXES`.

Diagnostics' connection tests are a known exception: they always test
against the `.env`-configured default sandbox, not whichever one is
currently active in the switcher.

## Names, not IDs

Every page shows a human name — a flow, property, connection, data view,
schema, or dataset's actual name/title — never a raw Adobe ID, including
where a reference crosses entities (a dataset's schema binding, a data
view's connection, or — the CJA page's Projects table — a two-hop chain
from project to data view to connection). `data.py` exposes small
`fetch_*_titles()`-style resolvers for exactly this (e.g.
`fetch_schema_titles()`) so a page never has to show an unresolved ID
while it waits on a separate lookup; every resolver falls back to
something readable (a shortened ID, never a full raw URL) if a reference
can't be resolved (e.g. a schema in a different container, or deleted
since the reference was created) rather than showing nothing. The CJA
page's cross-entity lookups (`_resolve_name()` in `ui/cja_page.py`) go a
step further and flag that fallback visibly — `"<id> (unresolved)"`
rather than a bare ID — since a real, expected cause there is a
permission gap (Connections needs product administration to see the org's
full list; Data Views needs the credential's own Product Profile
permissions — see Known Limitations below) rather than a deleted
reference, and a flagged fallback makes that distinguishable from an
actual name at a glance instead of blending in.

## Compare

Five tabs, each a different axis — worth being precise about since only
three are actually about sandboxes:

| Tab | Compares | Sandbox-based? |
|---|---|---|
| **Sandboxes** | AEP flow health + Observability metrics across every sandbox in `ADOBE_SANDBOXES` | Yes |
| **Schemas** | Any schema in sandbox A vs. any schema in sandbox B — each side picked independently | Yes |
| **Datasets** | Any dataset in sandbox A vs. any dataset in sandbox B — same independent-per-side pattern as Schemas; compares name, description, schema binding, Profile/Identity enablement, plus the two datasets' *schemas'* own field-level diff | Yes |
| **DC Properties** | Two picked properties' extensions/rules/libraries/environments/data elements | No — DC is org-wide |
| **CJA Data Views** | Two picked data views' dimensions/metrics | No — CJA is org-wide |

The Datasets tab's own attribute table renders differently from the other
four: a dataset is a single flat object (name, description, schema
binding, two booleans), not a list of named sub-items, so there's no
natural "only in A / only in B" bucket the way there is for a property's
extensions or a schema's fields — it's a plain field-by-field
"changed / not changed" table instead of the metrics-plus-buckets layout
every other tab uses. That table's "Schema" row only says the binding
*changed* (by name/id), not what's actually different about the two
schemas — so directly underneath it, the tab also renders a full
field-level diff of the two datasets' bound schemas (reusing the Schemas
tab's own `fetch_schema_diff()`/buckets layout), so "the schema changed"
comes with what specifically changed, not just that it did.

The Schemas tab picks sandbox and schema independently on each side —
side B defaults to the same schema *title* as side A when that title
exists in side B's sandbox too (the common case: comparing "the same"
schema across two sandboxes, where each sandbox has its own independent
copy under a different `$id`, so there's no way to default by ID), but
nothing forces it — pick a different schema on either side to compare
genuinely different schemas instead, and the tab says so explicitly when
the two titles don't match. Every tab's diff shows the same three
buckets: only in A, only in B, and
*changed* (present in both but with a different value on a compared field
— e.g. a schema field whose type changed, or a rule that's enabled on one
side and disabled on the other) — not just presence/absence.

### Drift: comparing against your own history

Schemas, Datasets, DC Properties, and CJA Data Views each have a
**"Compare against"** switch: *Another sandbox/entity* (above) or **Last
snapshot (drift)** — the same entity checked against its own most recent
recorded state, instead of against a different sandbox or entity. Useful
for catching "did this change since I last looked?" on a single schema,
dataset, property, or data view, without needing a second one to compare
it to.

Snapshots are **opt-in, per entity** — nothing is recorded until you
actually pick an entity in drift mode. The first time is always "no prior
snapshot — this is now the baseline"; only the *second* time (later in the
same session, or on a later visit) shows an actual diff, against whatever
was recorded last. Every drift check also re-records the current state as
the new latest snapshot, so the next check compares against *this* one.
Sandboxes tab has no drift mode — org-wide sandbox comparisons don't have
a single "entity" to snapshot.

Snapshots accumulate in `aep_monitor.db`'s `entity_snapshots` table and
persist across app restarts. `poller_cli.py` (see below) also sweeps every
entity that already has at least one snapshot on each scheduled run, so
baselines stay fresh even if nobody opens Compare between two checks — but
it only *sweeps* existing baselines, it never originates a new one; that
still only happens the first time you pick an entity in the UI.

## Quick start

```bash
./start-unix.sh      # or start-windows.bat on Windows
```

This creates a `.venv`, installs dependencies, copies `.env.example` to
`.env` on first run, and launches the app at `http://localhost:8501` — in
**mock mode** by default, so every page has realistic sample data
immediately.

## Going live

One Adobe I/O credential covers every product this app talks to.

1. In [Adobe Developer Console](https://developer.adobe.com/console),
   create **one** project and add all three: **Experience Platform API**
   (AEP Flow Service / Audit Query / Observability / Quota / Catalog /
   Schema Registry / **Segmentation Service** / **Query Service** — all of
   this app's AEP-family integrations live under this one API product,
   not separate ones), **Experience Platform Launch API** (Data
   Collection), and **Customer Journey Analytics API** (CJA). Choose
   **OAuth Server-to-Server** and select a product profile with access to
   each.
   - **Optional, separate API**: add **User Management API** too if you
     want Query Service's "Run by" column resolved to a name instead of
     an opaque id (see Known Limitations) — this is a genuinely different
     Adobe API product from the three above, not bundled into any of
     them, and skipping it just leaves "Run by" showing `(unresolved)`
     rather than breaking anything else. Adding it may also need the
     technical account granted an explicit org-level role in [Adobe Admin
     Console](https://adminconsole.adobe.com) beyond ordinary product
     profile membership — **not confirmed live** the way CJA's
     product-administration requirement below is; check what Developer
     Console/Admin Console actually asks for when you add it, and see
     Known Limitations for this integration's own strict rate limit
     before turning it on for a large org.
2. Fill in `.env` — `ADOBE_ORG_ID`, `ADOBE_CLIENT_ID`, `ADOBE_CLIENT_SECRET`,
   and `ADOBE_SCOPES` (the combined scope string the console shows once
   every API you added is added — this grows if you added User Management
   API too) — and set `MOCK_MODE=false`.
3. Restart the app. Use the **Diagnostics** page to test each product's
   connection individually.

Credentials always live in `.env`, never typed into the app or committed —
`.gitignore` excludes it, and `.env`'s file permissions are hardened to the
owning user at startup (POSIX).

## History & continuous polling

Every page's **Refresh from Adobe** button also writes a snapshot to
`aep_monitor.db` (SQLite) and re-evaluates alerts. History only accumulates
while something is actually refreshing — for a continuously-updating trend
line and alerts that fire even with the app closed, schedule the included
CLI poller:

```bash
*/15 * * * * cd /path/to/aep-monitor && ./.venv/bin/python poller_cli.py >> logs/poller_cron.log 2>&1
```

Both the app and `poller_cli.py` read/write the same database file.
`poller_cli.py` also sweeps every entity that already has a Compare
"vs. last snapshot" drift baseline (see [Drift: comparing against your own
history](#drift-comparing-against-your-own-history)), keeping those fresh
too — a sweep failure is logged and doesn't fail the rest of the cron run.

## Alerts

An alert is generated the moment a refresh finds:
- an AEP flow's latest run failed, or exceeded `ALERT_FAILED_RECORDS_THRESHOLD` failed records,
- a Data Collection extension with review status `rejected`/`failed`, *any* of a property's libraries in a `failed`/`rejected` build state, or its **production** environment's build status `failed` (dev/staging failures aren't alerted — only production),
- a CJA connection marked `disabled` or `deleted` — the only two health signals Adobe's API actually exposes (`isDisabled`/`isDeleted`; there's no status enum, unlike the other products above),
- a Segmentation Service segment job in a failed state — often the real, upstream cause of "the audience never reached the destination," ahead of the activation flow itself,
- a Query Service query in a failed/cancelled state,
- a data-lifecycle quota reaching `ALERT_QUOTA_THRESHOLD_PCT` percent consumed, **or** — separately — projected to reach 100% within `ALERT_QUOTA_TREND_DAYS` days at its own recent linear rate of change (from the same history the Overview page charts), so a slow-moving governance quota gets flagged with lead time to act instead of only after the threshold's already crossed. Set `ALERT_QUOTA_TREND_DAYS=0` to disable the trend alert and keep only the plain threshold one.

Separately from all of the above, **`alerts.evaluate_freshness()`** is a
dead-man's-switch: if a source's last recorded snapshot is older than
`ALERT_STALE_AFTER_HOURS` (default 6), it raises a `Monitor`-sourced alert —
independent of whether the poller that would normally refresh that source
is even still running. This can't be evaluated as part of polling itself
(code that only runs *as part of* a poll can never notice the poll has
stopped happening at all), so it runs on a read path instead — every time
the Overview or Alerts page is opened — so the dashboard self-diagnoses
"have I gone quiet?" the next time a human actually looks, rather than
silently showing stale data as if it were current. A source that's never
been polled at all (fresh install) is skipped, not flagged.

Adobe also has its own native alerting on top of Observability Insights
metrics (UI notification bell, forwardable to Slack via an App Builder
proxy) — a second, Adobe-owned alert path independent of this app's, worth
knowing about if you want alerting Adobe manages centrally instead.

Each alert is deduplicated by a fingerprint (so repeated polls don't spam
duplicates) and **automatically resolves** the next time that condition is
no longer present — no manual bookkeeping required, though you can also
resolve one by hand from the Alerts page. Set `SLACK_WEBHOOK_URL` to also
push newly-opened alerts to a Slack channel (an [Incoming Webhook](https://api.slack.com/messaging/webhooks)),
once per alert, not on every subsequent poll while it's still open.

## Known limitations / things to verify against your tenant

- **AEP Ingestion doesn't distinguish inbound ingestion from outbound
  activation flows.** `GET /flows` (`clients/aep.py`'s `list_flows()`)
  returns every flow undifferentiated — both a source landing data into a
  dataset and an AEP segment activating out to an external destination
  (Meta, Google Ads, email, …) are the same object, with no boolean
  direction field. This matters more than it might look: a broken
  destination sync is often the single most business-visible failure in
  the whole stack (a marketing team notices immediately when an audience
  doesn't land), and until this was addressed it had **no distinct
  visibility at all** — a failed activation flow just looked like a failed
  ingestion flow. The fix implemented is a visibility one, not a
  classification one: each flow's `flowSpec.id` is resolved to a
  human-readable connector name (`fetch_flow_spec_titles()` in `data.py`,
  via a new `list_flow_specs()` call — `GET /flowSpecs`) and shown as its
  own **Connector** column (e.g. "Amazon S3" vs. "Google Ads Data
  Connector"), so a human can tell ingestion and activation flows apart at
  a glance, and a failed-run alert's message includes the connector name.
  **Not implemented:** automatic boolean classification (ingestion vs.
  activation) — that would need each flow's connection ids resolved to
  their own `connectionSpec` too, which hasn't been verified against a
  live tenant. Also not confirmed live: whether `GET /flowSpecs` returns a
  human-readable `name` at all (vs. only `id`/`version`) — if the Connector
  column shows raw ids instead of names on your tenant, that's why; the
  underlying `flow_id`/`state` columns are unaffected either way.
- **Segmentation Service and Query Service** (`clients/segmentation.py`,
  `clients/query_service.py`) were added to close a real coverage gap
  rather than a peripheral one: this app already watched ingestion (Flow
  Service) and consumption (CJA connections/data views/projects), but
  nothing watched the layer in between that actually *produces* what an
  activation flow exports — a failed segment job is very often the real
  upstream cause of "the audience never reached the destination."

  **Query Service's Queries API is now confirmed against Adobe's own
  published example response** (not just docs prose) — and doing that
  caught three real mistakes in the original, guessed version of
  `parse_query()`, the same class of gap Connections/Data Views hit
  earlier in this document:
  - `sql` is **not top-level** — it's nested under `request.sql` (alongside
    `request.dbName`, the database context). The original `item.get("sql")`
    always returned `""` against a real tenant — this is why the Query
    Service page's detail view showed "No SQL text returned for this
    query" live even though mock mode looked fine (mock data had guessed
    the same wrong flat shape, so it validated the parser against its own
    mistake — same root cause as the Audit Query envelope bug above).
  - The client/origin field is `client` (e.g. `"Adobe Query Service UI"`),
    not `clientType` — kept as a fallback in case a different tenant/version
    uses it.
  - Error info is an `errors` **array**, not a single `errorMsg` string.
    Adobe's own example only shows an empty array, so a populated entry's
    exact shape isn't confirmed — handled defensively for either a plain
    string or a `{message: ...}` object.

  Also confirmed live (not a guess): the raw query object has **no `name`
  field at all** — unlike segments/flows elsewhere in this app, a query is
  identified by `id` only; falling back to `id` in the Query column is the
  *normal* path here, not an edge case. The list envelope is HAL-style
  (`{"queries": [...], "_page": {...}, "_links": {...}}`, confirmed live),
  and a query's `_links.referenced_datasets` — shown as raw ids, not
  resolved to names, in the detail section — is a real field too.
  **Not confirmed:** whether `is_scheduled`'s `scheduleId`/`isScheduled`
  detection matches anything on a real scheduled query — no scheduled-query
  example exists in Adobe's docs to check against.

  **The Schedules API (`list_schedules()`/`parse_schedule()`) is NOT
  independently confirmed the same way** — still the newest,
  least-verified piece of this integration, same caveat class as
  Segmentation below. Both pages' raw-response expanders show exactly what
  Adobe returned; check those against what `parse_segment_job()`/
  `parse_schedule()` assume before trusting a new tenant's numbers.

  **Segmentation Service is now confirmed against Adobe's own published
  example responses too** (Segment Definitions and Segment Jobs both) — and
  it caught a real, live-breaking bug, not just shape mismatches: the
  Segment Jobs list call's `sort` parameter was `"desc:createdAt"` (both
  the order and the attribute name backwards) — Adobe's documented syntax
  is `"[attribute]:[asc|desc]"`, e.g. `"creationTime:desc"`. Unlike most of
  the guesses elsewhere in this document, a malformed `sort` isn't
  something Adobe degrades gracefully on — it's rejected outright with a
  hard `HTTP 400 "The expression used is invalid"`, which surfaced as the
  entire Segments page (and, before `refresh_all()`'s per-leg isolation
  fix just below, the entire Overview page) failing outright. Also
  corrected: a job's segment reference is a `segments` **list** of
  `{segmentId: ...}` objects, not a top-level `segmentId`/`definitionId`
  string; its timestamps are `creationTime`/`updateTime` in **epoch
  milliseconds**, not ISO `startTime`/`endTime` strings; and the
  profile-count field is `metrics.segmentedProfileCounter` (with the
  "er"), not `segmentedProfileCount`. Confirmed envelope keys: `"segments"`
  for definitions, `"children"` (HAL-style, with `_page`/`_links`) for
  jobs — both handled with defensive fallbacks in case a different
  tenant/version varies.

  Both clients send `x-sandbox-name` defensively (same reasoning as
  Quota/Audit Query below).

- **User Management API** (`clients/user_management.py`) resolves Query
  Service's opaque `userId` to a display name for the "Run by" column —
  added because Query Service's own API has no CJA-style `expansion`
  parameter to do this itself (confirmed via Adobe's docs: the complete
  documented parameter list for `GET /queries` is `orderby`, `limit`,
  `start`, `property`, `excludeSoftDeleted`, `excludeHidden`, `isPrevLink`
  — no expansion/properties/fields option exists, and `userId` is the only
  user-identifying field documented on a query object at all). Confirmed
  live via Adobe's own published docs: base URL
  `usermanagement.adobe.io/v2/usermanagement`, endpoint `GET
  /users/{orgId}/{page}` (zero-indexed, paginated via a `lastPage`
  boolean), user object fields `id`/`email`/`username`/`firstname`/
  `lastname`/`type`/`domain`/`country`.

  **Not confirmed**: whether a user's `id` in this API is actually the
  same identifier Query Service's `userId` returns — these are two
  separate Adobe systems with no documented guarantee their id spaces
  line up, unlike CJA's `expansion=ownerFullName` (which resolves an id
  *within the same API* that produced it). If "Run by" stays unresolved
  for every query on your tenant even after adding this API, a mismatched
  id space — not a broken integration — is the first thing to check via
  the Diagnostics page's raw connection test. Also expected, not a bug:
  Adobe's own docs mark `id` "optional if unpopulated," and a technical/
  service account (like the one this app's own credential authenticates
  as) very plausibly has no directory entry at all — an unresolved id on
  a scheduled/API-run query is normal, not a resolution failure.

  **Rate limit — confirmed via Adobe's own docs, the strictest of any API
  this app talks to by a wide margin**: 25 requests/minute per client,
  plus a separate 100/minute cap shared across every client in the org
  (this app has no way to protect that shared cap if other tools use the
  same org). Unlike every other client in this app, User Management API's
  `RequestPacer` is fixed at its own `USER_MANAGEMENT_REQUESTS_PER_SECOND`
  (default ~21/min) instead of sharing the global `REQUESTS_PER_SECOND`
  every other client uses — see `clients/base.py`'s `RequestPacer`/
  `BaseAdobeClient.requests_per_second_override`.
  The resolved directory is also cached in `aep_monitor.db`
  (`database.replace_user_directory()`) and only refetched once
  `USER_DIRECTORY_CACHE_HOURS` (default 12h) has passed — independent of
  how often the Query Service page itself is refreshed, since Adobe's own
  guidance recommends syncing this API hourly at the fastest. A directory
  refresh failure (e.g. the API product hasn't been added yet, or the
  technical account lacks the org-level role it needs) is caught and
  logged rather than propagated — every `userId` just stays unresolved,
  Query Service's own page keeps working either way.

- **`refresh_all()` now isolates each of its six legs' failures
  independently** (`poller.py`) — found via the Segmentation bug above,
  which exposed a real design gap: one leg raising used to abort the whole
  function before it could return *anything*, silently losing every other
  leg's already-fetched data too. Concretely: Quota's own fetch had
  already succeeded, but its result never reached the Overview page,
  because Segments raised before the surrounding dict literal finished
  building — so a specific "Data lifecycle quotas: No quota data" symptom
  was actually a downstream consequence of an unrelated Segments bug, not
  a Quota bug at all (the Quota client's request/response shape was
  already correct, confirmed via Adobe's own published example — see
  above). Each leg now runs in its own try/except; a failure contributes
  an empty list plus its exception under a returned `"errors"` key
  (`ui/overview.py` shows a per-product warning instead of losing the
  page; `poller_cli.py` prints each failure and exits non-zero if any leg
  failed, for cron-failure monitoring). A failed leg also never records a
  fresh snapshot, so `alerts.evaluate_freshness()`'s dead-man's-switch
  independently catches a *persistent* failure on its own, on top of the
  immediate feedback above.
- **Audit Query API** parsing (`aep_monitor/clients/audit.py`) is the least
  exercised part of this app — its exact query-parameter and response
  contract wasn't verified against a live tenant while building this.
  Check your first live response (the Audit Log page shows the raw JSON)
  and adjust `list_events()`/`parse_event()` if your tenant's shape
  differs. Two real gaps found and fixed this way already:
  - It originally shipped without an `x-sandbox-name` header, which
    Adobe's own docs didn't call out as required for this endpoint — it
    is, and omitting it is a hard `HTTP 400 "Missing Sandbox
    Information"`. The Quota client now sends it defensively for the same
    reason, even though its docs didn't flag it as required either.
  - Events sit under a HAL-style `_embedded.events` envelope, not a
    top-level `events`/`data`/`items` key as originally guessed. This one
    is worth calling out specifically: it produced *no error at all* —
    the request succeeded, the parser just silently found nothing at the
    wrong key, and the page showed "No audit events returned" as if
    there genuinely were none. (The mock data was built to the same wrong
    guessed shape too, so the test suite validated the parser against its
    own mistake and could never have caught this — now fixed to mirror
    the real raw shape, per mock.py's own stated convention.) Also
    unresolved: Adobe's own docs page for this endpoint labels it GET in
    one section and shows a POST curl example in another, self-flagged as
    an inconsistency — left as GET (what was already in place and, per
    the fix above, apparently correct), switch to POST if you see a
    404/405 against your tenant.
- **Reactor Audit Events** (`list_audit_events()`/`parse_audit_event()` in
  `clients/reactor.py`) — Adobe's own docs for `/audit_events` say
  plainly "the implementation... is in flux" as the feature evolves, so
  treat field names (`attributed_to_email`, `type_of`, ...) as more
  likely to drift here than anywhere else in this app.
- **Reactor Environments/Data Elements** (`list_environments()`/
  `list_data_elements()` in `clients/reactor.py`) are documented (unlike
  Audit Events above) but, like the rest of this Reactor client, weren't
  exercised against a live tenant while building this — the same
  `attributes.*` field names Adobe's docs give (`stage`, `status`,
  `dirty`, `review_status`, ...) are used, parsed defensively. Adobe's
  docs also don't enumerate every possible `status` value for an
  environment — only `succeeded`/`pending` are shown in examples —
  `failed` is assumed (consistent with every other build-status field in
  this app) but not confirmed exhaustively; adjust
  `_BAD_ENVIRONMENT_STATUSES`/`_GOOD_ENVIRONMENT_STATUSES` in
  `clients/reactor.py` if your tenant uses a value neither set catches.
- **AEP Catalog (Datasets)** (`clients/catalog.py`) has two shape details
  confirmed via Adobe's docs that are genuinely different from every other
  Adobe API this app talks to: `GET /dataSets` returns an object **keyed
  by dataset ID**, not an array (the id only exists as the dict key,
  never inside the dataset's own value object — `parse_dataset()` takes
  the id and the value as two separate arguments for exactly this
  reason), and Adobe only returns a small default field subset unless you
  explicitly request more via the `properties` query parameter — this
  app requests `name,description,schemaRef,tags,created,updated`
  explicitly rather than relying on the default. Also: `tags.unifiedProfile`/
  `tags.unifiedIdentity` are lists of strings like `["enabled:true"]`, not
  booleans — read carefully (a naive `bool(tags.get(...))` would
  incorrectly read `True` for `["enabled:false"]` too, since a non-empty
  list is truthy regardless of its contents).
- **CJA Audit Logs** (`list_audit_logs()`/`parse_audit_log()` in
  `clients/cja.py`) lives at a genuinely separate base URL
  (`cja.adobe.io/auditlogs/api/v1`, not the `/data` path every other CJA
  endpoint uses) — confirmed via Adobe's own docs, which is why this one
  bypasses `self.get()`'s base-URL prefixing and calls `_request()`
  directly with a full URL. If it comes back empty, it's likely the same
  CJA "product administration" privilege gap documented above for
  Connections/data views, not a separate issue.
- **CJA Calculated Metrics** (`list_calculated_metrics()`/
  `parse_calculated_metric()` in `clients/cja.py`) is a *third* separate
  CJA base URL (`cja.adobe.io/calculatedmetrics`), confirmed the same way
  as Audit Logs above. Two things are explicitly *not* confirmed and
  handled defensively rather than assumed: (1) there's no documented
  per-data-view filter query parameter for this endpoint, unlike
  dimensions/metrics — so this app fetches the full org-wide list and
  filters client-side by the response's `dataId` field instead of trusting
  an unconfirmed parameter; (2) Adobe's docs don't explicitly state that
  `dataId` *is* the data view id (only that it's present on the response
  and lines up with that id space in every example seen) — treat that
  association as reasonably confident, not fully confirmed, and check your
  own tenant's response if calculated metrics don't show up where
  expected.
- **Schema field labels** (SDR page's "Labels" column, `list_label_descriptors()`/
  `extract_label_descriptors()`/`parse_label_descriptor()` in
  `clients/schema_registry.py`) are data-governance/DULE labels (e.g.
  `core/I2` Identifiable, `core/S2` Sensitive, `core/C1` Contract data)
  read from the Schema Registry's Descriptors API (`GET /tenant/descriptors`,
  `@type: xdm:descriptorLabel`). Confirmed **live**, not just from docs
  (Adobe's own reference doc for this endpoint doesn't even list
  `xdm:descriptorLabel` as a supported type): the list response is grouped
  by `@type` with full descriptor objects (`{"xdm:descriptorLabel": [{...}]}`),
  and `property=<field>==<value>` is a real, repeatable, ANDed server-side
  filter (undocumented — Adobe's own UI uses it under the hood) — this app
  uses `property=@type==xdm:descriptorLabel` to fetch only label
  descriptors instead of every descriptor type.

  One thing that *did* need a real fix (not just confirming a guess): a
  label descriptor's `xdm:sourceSchema` is a **field group** id (e.g.
  `.../mixins/xxxx`), not the composite schema's own `$id` — matching
  against the schema's `$id` (the first version of this feature) silently
  matched nothing, ever. There's also no way to resolve which field groups
  compose a given schema (the "full resolved" schema response has no
  `allOf` field-group list, confirmed live), so `fetch_schema_field_labels()`
  matches by **field path** instead — correct even for a label on a field
  group shared across multiple schemas, since `flatten_fields()` already
  merges every field group's properties into one flat tree per schema.

  A second real fix, also found live: this app originally sent `limit=500`
  (the general Schema Registry docs' page-size max elsewhere), and Adobe
  returned an actual HTTP 400 `"Query limit out of range... valid query
  limit is 0 - 300"` — this endpoint's real max, confirmed live, is 300.
  If labels still don't show up (or a warning appears instead) after all
  of the above, the SDR page's "Raw label descriptors" expander (next to
  "Raw schema response") shows every descriptor Adobe actually returned
  for the active sandbox, and surfaces a fetch failure as a visible
  warning instead of silently defaulting to empty — check that before
  assuming it's another shape/limit surprise.

  **Still not confirmed:** how a field nested inside an array renders in a
  descriptor's JSON-pointer `sourceProperty` (the schema fields table marks
  those `arrayField[]...`, a convention this app invented for display —
  no live example of a labeled array-nested field has been seen), so such
  a field's label may not match up. Pagination beyond 300 descriptors also
  isn't implemented (the documented mechanism for it, a separate `v2`
  `Accept` header, isn't confirmed) — a sandbox with 300+ label descriptors
  specifically could miss some.
- **SDR's Component Usage tab** (`list_projects()`/`get_project()`/
  `extract_entity_references()` in `clients/cja.py`) shows which
  dimensions/metrics/calculated metrics on a data view are actually
  referenced by a CJA Workspace project — and, by omission, which aren't.
  Confirmed live: `GET https://cja.adobe.io/projects` (list) returns a
  **bare JSON array**, not the `{"content": [...]}` envelope every other
  CJA list endpoint uses, and has no `lastPage`/`totalElements` to page on
  — this app stops paging when a page comes back with fewer items than
  requested instead. `expansion=definition` only populates a project's
  `definition` on the single-project `GET .../projects/{id}` call, not the
  list call, despite Adobe's docs describing it as available on both.
  Both calls also send `includeType=all` — confirmed via Adobe's own docs
  as the admin-scoped option (the default is narrower), the same
  owner-only-by-default pattern CJA Connections has; a technical account
  without CJA product administration may still get a restricted or empty
  list back even with it, same known tradeoff as Connections, not a new
  failure mode (the CJA page's "no projects found" message says as much).
  `list_projects()` also sends `expansion=ownerFullName` — a project's
  `owner.name` came back `null` in a real response (only the opaque
  `ownerId`/`imsUserId` were populated), and this expansion value is
  documented for the list endpoint specifically as resolving it to a
  display name, in the one bulk call rather than a per-project or
  per-user lookup. **Not confirmed** which field the resolved name
  actually lands in from a real populated example — `parse_project()`
  checks a top-level `ownerFullName` (matching the expansion's own name)
  first, then falls back to `owner.name` (the field that came back null
  without it), then the opaque id if neither is populated.
  Every referenced component (a date range, the data view itself, and —
  expected but not confirmed from a populated example — dimensions/
  metrics/calculated metrics/segments) is tagged `__entity__: true`
  wherever it sits in the deeply nested panel/subPanel/reportlet tree;
  this app walks the whole tree recursively rather than assuming a fixed
  path, since that path likely varies by visualization type (Freeform vs.
  Trended vs. Cohort, etc.) and only a Freeform panel was seen.

  Matching a project's referenced components back to the data view's own
  dimensions/metrics/calculated metrics is done by **id** (against the
  already-confirmed Dimensions/Metrics/Calculated Metrics endpoints), not
  by an entity's `type` string — so the unconfirmed exact `type` spelling
  for a Dimension/Metric/CalculatedMetric reference (only an empty test
  project was available, which had none to check against) isn't a
  correctness risk for the usage counts themselves; a `type` this app
  doesn't recognize just means that reference's *label* in the "referenced
  but not in this data view's current component list" section shows
  whatever Adobe actually returned, verbatim, rather than the count being
  wrong. `type` is only load-bearing for the two confirmed exclusions —
  `"ReportSuite"`/`"DateRange"` (panel framing, not a shared component) —
  and if some other framing-only entity type exists that this app hasn't
  seen, worst case it shows up in that "not in current component list"
  section rather than corrupting a real component's count. This is also,
  deliberately, the only SDR tab that isn't auto-fetched — building the
  usage map costs one API call per project bound to the selected data
  view (no bulk "definitions for every project" endpoint exists), so it's
  gated behind an explicit "Load project usage" button rather than loaded
  with the other three tabs.
- **Flow Service** response field names (`recordSummary`, `statusSummary`,
  ...) come from Adobe's published docs but are known to vary slightly by
  source type. Parsing is defensive (`.get()` with fallbacks) and every
  page keeps the raw JSON in an expander specifically so a shape mismatch
  is visible instead of silently wrong.
- There is no documented "all runs org-wide" Flow Service endpoint —
  monitoring fans out one `/runs?property=flowId==...` call per flow
  (capped to the flows returned by `/flows`) rather than guessing at an
  undocumented one.
- CJA's `/connections` and `/dataviews` list-response envelope
  (`content` vs `data` vs a bare array) is handled defensively for the
  same reason. (Historical: the CJA base URL itself was originally missing
  the `/data` path prefix every CJA endpoint actually lives under — a
  live-only bug, since mock mode never hits a real URL, so it went
  unnoticed until confirmed against Adobe's endpoint docs and fixed.)
- (Historical, fixed) **CJA Connections and Data views showed raw ids
  instead of names.** Root cause, confirmed via Adobe's docs: `/connections`
  and `/dataviews` only include `name`/`owner`/etc. when explicitly
  requested via the `expansion` query param — not by default — which
  `list_connections()`/`list_dataviews()` weren't sending. Also fixed in
  the same pass, found via the same docs check: a data view's FK back to
  its connection is `parentDataGroupId`, not `connectionId`/
  `dataConnectionId` as originally guessed (so the Data views table's
  "Connection" column couldn't resolve to a name even once `name` itself
  was fixed); and CJA connections have no status enum at all — no
  `status`/`serviceStatus` field exists — only `isDeleted`/`isDisabled`
  booleans, which the connection health status/alert (see Alerts above)
  now derives from instead of a field that was always empty in live mode.
  Because mock data mirrored the *intended* parsed shape rather than the
  real (expansion-gated) raw response, none of this showed up in mock mode
  — same class of gap as the Audit Query envelope bug elsewhere in this
  list, and the reason mock data is held to "shaped exactly like the raw
  API response" as a rule, not just "has the right fields eventually."
- **CJA Connections showing 0 with no error** is expected, not a bug, for
  a Server-to-Server (technical account) credential without extra
  privileges: Adobe's own docs for this endpoint say plainly, "In order to
  view all connections, you must have product administration privileges
  associated with your account" — without that, the API call succeeds
  (200 OK) and returns only connections *owned by* the calling account,
  which for a service account is normally none. Selecting a product
  profile during Developer Console credential setup only makes the
  technical account a basic *member* of that profile (why the API call
  already succeeds at all) — not an *admin* of it, which is the extra
  step actually needed here.

  **Data Views is governed separately — confirmed live, not just
  theorized**: granting Product Administrator fixes Connections, but
  Data Views only needs the technical account's Product Profile to have
  the required Data Views assigned under its own Permissions tab (an
  ordinary permission, unrelated to the admin flag). Tested directly:
  revoking the admin grant and keeping just that profile assignment left
  Data Views working while Connections went back to showing 0. Since
  Product Administrator also grants managing the profile itself (not
  just read visibility), **only grant it if you actually need
  Connections** — for Data Views alone, the profile assignment is
  sufficient and is the least-privilege choice.

  To find the technical account email (only needed if you do want
  Connections too): easiest is Developer Console → this app's project →
  the credential itself → its overview page shows "Technical account
  email" right near the Client ID/Secret. (Admin Console → Users →
  **API Credentials** — a distinct sub-item, *not* the regular Users
  list, which won't show it — works too.) Then: Admin Console → Products
  → Customer Journey Analytics → the product profile this credential
  uses → **Admins** tab → paste that email, select it from the dropdown
  (resolves to an Enterprise ID), assign as Product Profile
  Administrator. The CJA and SDR pages show this same explanation in-app
  when Connections comes back empty.
- **Overview's end-to-end data flow** (`fetch_cja_dataset_lineage()` and
  `fetch_property_datastream_edges()` in `data.py`, `_build_lineage_flowchart()`
  and `_relevant_property_edges()` in `ui/overview.py`) is one Graphviz
  flowchart (boxes + arrows, via `st.graphviz_chart` — no new dependency,
  it renders a raw DOT string directly) covering the whole chain: **Website
  domain → (Data Collection) Property → Datastream → XDM Schema → AEP
  Dataset → CJA Connection → CJA Data View → CJA Project**.

  This went through two earlier shapes before landing here, both directly
  from live feedback:
  1. One seven-stage chart (no Website domain yet) — a Plotly **Sankey**,
     which turned up a genuine, reproducible rendering defect ("the mock
     not looks good"), confirmed by re-rendering the exact returned figure
     standalone: scoped to one connection, most stages boil down to
     exactly one path, and Plotly draws a link with nothing to compare its
     flow against as a solid, unlabeled grey block spanning the full node
     height. A Sankey's proportional-flow-width encoding was never
     actually the point here — nothing in this pipeline is a volume
     metric, every link is just "N paths go through here" — so it was
     replaced with a plain **Graphviz flowchart**, which never had that
     failure mode to begin with since it isn't trying to encode width at
     all; a path count still shows, as a small "×N" edge label, only when
     it's more than one. Graphviz also sidesteps every Sankey-specific
     sizing/height-tuning problem this app had previously fought (fixed
     height crushing a busy stage, margin clipping at the plot edge): its
     own automatic layered layout sizes itself to content, including a
     same-rank "anchor" per stage (`_build_lineage_flowchart()`'s
     docstring) so stage order stays left-to-right even when a stage has
     no real edge into the next one (e.g. a connection with no data view
     at all).
  2. Website domain/Property/Datastream were then split *out* of that
     five-stage flowchart entirely, into their own separate,
     collapsed-by-default table — a real usability problem on the Sankey
     from step 1, where those stages almost always collapsed to a single
     node each, rendering as a huge, mostly-empty solid block next to the
     genuinely dense fan-out further along. That specific failure mode
     doesn't exist on a Graphviz flowchart (a 1-node stage is just a small
     box, not a rendering problem), so on request ("include this also to
     the diagram and remove the separate section") they were merged back
     in here, joined onto the CJA-side chain's own Dataset node by dataset
     *name* (see `_build_lineage_flowchart()`'s docstring) — one diagram
     again, this time without reintroducing what made the first one look
     bad.

  The five CJA-side hops are genuinely confirmed cross-product links: a
  dataset's own schema binding (already used on the Datasets page/Compare),
  and a CJA connection's own `dataSets` field (`expansion=dataSets`,
  confirmed via Adobe's docs — `{dataSetId, domain, type, timestampId,
  visitorId, identityNamespace, usePrimaryIdNamespace, identityMap, name,
  streaming}` per entry).

  The Website/Property/Datastream chain closes a real gap Adobe doesn't
  expose via any documented API — but not by guessing at it. There is no
  official, documented API for Datastream *configuration* (which datastream a
  property's Web SDK extension is set to use, and which dataset that
  datastream forwards to). Confirmed, not just assumed: Adobe's own
  community forum has staff confirming an internal API exists at
  `edge.adobe.io` ("DataStreams" were originally called "EdgeConfigs") but
  explicitly *not* publicly documented or supported — "not really a public
  API in the sense that it has not been made publicly aware nor does it
  come with any up-to-date documentation." Building against it would be a
  different risk category from every other integration in this app (all
  built against Adobe's actual published docs), so it's not used.

  The *very first* hop (website → property) needs no workaround at all:
  Adobe's own Properties endpoint already returns a `domains` attribute —
  a plain array of the web domain(s) a property is configured for
  (confirmed via Adobe's own docs: required for web properties) — on the
  same `GET /properties` response this app already fetches for every
  other property field. No extra call, no extra scope, just one more field
  read off a response already in hand (`parse_property()` in
  `clients/reactor.py`). A non-web property (the mock mobile property, for
  instance) simply carries none, which is expected, not an error.

  Instead, the *next* hop (property → datastream id) is fully automated
  through an API this app already uses: a property's Web SDK extension
  carries its own configured datastream id(s) in Reactor's own, fully
  public `GET /properties/{id}/extensions` response — confirmed via
  Adobe's docs that the *list* response (not just the single-item GET)
  already includes each extension's full `settings` attribute, a
  JSON-*encoded string* (not a nested object).

  **Confirmed live against a real tenant's raw extension response** (not
  a guess, and it caught a real bug — two earlier versions of this
  extraction both looked at the wrong nesting level entirely and silently
  found nothing, on every property, always): the datastream ids are
  **not** top-level keys on `settings` — they live inside
  `settings["instances"]`, a *list* of named Web SDK instance configs
  (`clients/reactor.py`'s `_extract_datastream_ids()`; the extension
  supports configuring more than one instance, though the confirmed-live
  common case is exactly one, named `"alloy"`). The extension's own
  Reactor `name` is confirmed live to be `"adobe-alloy"`, for what it's
  worth — this extraction still doesn't key off it, since a setting name
  it's uniquely known to carry remains the more robust signal (Adobe's
  docs don't show a live example of that string to match against, and a
  future extension version could rename the package without renaming its
  settings).

  Also confirmed live, and easy to miss: a single instance configures a
  genuinely **different datastream per build environment** — production,
  staging, and development each get their own id, not just one flat
  value, all inside that same instance object: `edgeConfigId` (production),
  `stagingEdgeConfigId` (staging), `developmentEdgeConfigId` (development)
  — confirmed live with exactly this naming. The newer `datastreamId`-style
  rename Adobe's docs describe (`datastreamId`/`stagingDatastreamId`/
  `developmentDatastreamId`) is checked first as a fallback in case a
  different tenant/extension version has migrated to it, but no live
  example of that has actually been seen — only the older names are
  confirmed to exist. Every environment with a configured id becomes its
  own row/node, labeled with that environment (e.g. "Prod Web Datastream
  (production)") so two different real datastreams on the same property
  are never conflated into one; multiple *instances* (rare) are
  distinguished the same way, by instance name, only when more than one
  is actually present. The DC page's Extensions tab shows every
  environment's raw id directly (and a
  "Raw extension responses" expander) — the fastest way to check this
  extraction against what a live tenant's `settings` actually contains
  before assuming `datastream_map.json` itself is wrong.

  The *last* hop (datastream id → its name and destination dataset) is
  the one piece no public API exposes at all, so it's closed with one
  small, git-ignored, human-maintained file instead: `datastream_map.json`
  (`aep_monitor/datastream_map.py`), `{datastream_id: {name, dataset_id}}`
  — the same `.env`/`.env.example` convention as every other local,
  tenant-specific file in this app, with `datastream_map.sample.json`
  committed as both the template and mock mode's demo content. This is the
  one deliberate manual step in an otherwise fully-automated chain — a
  human who configured Datastreams already knows this mapping; nothing
  public exposes it for this app to discover on its own. A datastream id
  with no entry in the file still gets a row (Dataset shown as "(not
  mapped)"), never silently dropped. Editing this file and clicking
  **"Refresh everything"** on the Overview page picks it up immediately —
  an earlier version of this app only ever recomputed the lineage chart on
  a *sandbox change*, silently ignoring a plain file edit; the refresh
  button now re-reads it too.

  The flowchart is always scoped to one connection at a time via a **"Focus
  on connection"** picker — an unfiltered, all-connections view was tried
  first, but at real-org scale (dozens of connections/projects) it's
  reliably too dense to read no matter how much the rendering is tuned, so
  the option was removed rather than merely defaulted away from. That
  picker is itself filtered to connections with at least one dataset
  **actually resolving** in the *currently active sandbox* (deliberately
  strict — a connection with no configured datasets at all, or only
  unresolved ones here, doesn't count) — an **inference**, not something
  Adobe's API states directly (Connections are org-wide and carry no
  sandbox field of their own to check), with a "Show connections with no
  resolved data in this sandbox too" checkbox as an explicit opt-out so a
  connection is never silently unreachable, only filtered by default.

  The Website domain/Property/Datastream portion of the *same* flowchart
  is independently scoped too, via `_relevant_property_edges()` —
  filtered to just the edges whose dataset the focused connection actually
  resolves, directly implementing the "only show the datastream that maps
  to the corresponding sandbox" request. An earlier version of this app
  filtered this way *unconditionally* and had to walk it back once: a
  property's datastream very plausibly forwards to a dataset that isn't
  part of *any* CJA connection at all (e.g. a raw data-lake landing
  dataset), so if this were the *only* view of that mapping, filtering it
  by connection could silently hide a correctly-configured one no matter
  which connection was selected. The fix that stuck is keeping a second,
  always-unfiltered "Debug: every Property → Datastream → Dataset value
  extracted/matched" expander right below the chart as an escape hatch —
  the diagram shows "what feeds *this* connection", the debug table always
  has the full, never-hidden "did this extract/map at all" list regardless
  of scope. The Data Collection properties table further down the page
  shows every property's resolved datastream (and its website domains)
  too, independent of both and of whichever connection is focused.

  A dataset id a connection references but the active sandbox's own
  dataset list can't resolve (a real possibility — Datasets are
  sandbox-scoped, Connections are org-wide, so a connection can reference
  a dataset from a different sandbox) collapses into one shared
  "Unresolved dataset" node rather than one node per raw id — reported
  live that a real org's permission/sandbox gaps can produce dozens of
  them, and a wall of long, near-identical GUID labels was unreadable; the
  specific raw ids are still listed in a caption under the chart. Graphviz's
  own layered layout sizes the chart to content automatically (no manual
  height/margin tuning needed, unlike the Sankey this replaced), and a
  color-coded legend plus a stage-prefixed tooltip on every node
  ("Schema: X") make all eight stage colors identifiable without
  memorizing them.
- **SDR page** (`aep_monitor/clients/cja.py`'s dimensions/metrics
  endpoints, `aep_monitor/clients/schema_registry.py`) is the newest,
  least-exercised integration in this app — same caveat as Audit Query.
  The Schema Registry list-response envelope key (`results` vs
  `resources` vs `data`) and the exact resolved-schema `properties` shape
  after requesting `xed-full+json` weren't verified against a live
  tenant; `flatten_fields()` is defensive and depth-capped, but if a
  schema shows zero fields where you expect some, check the page's
  underlying raw response shape against what `parse_schema_summary()`/
  `flatten_fields()` assume before concluding the schema is actually
  empty.
- **Observability Insights** (`aep_monitor/clients/observability.py`) only
  wraps the one endpoint confirmed in Adobe's own published Postman
  collection (`POST /metrics`) and only two metric IDs confirmed from
  Adobe's own example request (`recordsuccess.count`, `batchfailed.count`).
  Adobe's marketing docs describe additional "health-check categories"
  (Query Service, Merge Policies, Segmentation, ...) but no distinct
  endpoint or metric IDs for them were found — add metric IDs to
  `DEFAULT_HEALTH_METRICS` once you've confirmed the exact string in your
  tenant rather than guessing. Also unresolved: whether `x-sandbox-id` is
  actually required (one doc says yes, the Postman collection says no) —
  left optional, set `ADOBE_SANDBOX_ID` only if requests fail without it.
  When Compare's Sandboxes or Schemas tabs override `x-sandbox-name` per
  sandbox, they drop `x-sandbox-id` from that request entirely rather
  than sending it paired with the wrong sandbox's name — there's no
  per-sandbox ID configured, so the global one is only valid for the
  configured default sandbox. Also: datapoints aren't documented as
  chronologically ordered, so the parser sorts them defensively — both
  the trend chart and Compare's Sandboxes tab's "latest value" lookup
  depend on that ordering.
- **Data Lifecycle Quota API** covers governance quotas (dataset
  expiration, consumer-delete/privacy-request identities) — it is *not* a
  live "requests remaining before a 429" API. Adobe doesn't publish one;
  its per-service rate limits are static numbers shown as reference text
  on the Settings page.
- **Compare's Sandboxes and Schemas tabs** only cover AEP (Flow Service,
  Observability Insights, Schema Registry) because that's the only one of
  the three products that's actually sandbox-scoped in Adobe's
  architecture — Data Collection properties, CJA connections/data views,
  and data-lifecycle quotas are org-wide, so they don't vary by sandbox.
  The DC Properties and CJA Data Views tabs compare two picked entities
  instead of two sandboxes, for the same reason.
- **Compare's Schemas tab** only *defaults* side B to matching side A's
  schema by `title` (each sandbox has its own independent copy under a
  different `$id`, so there's no way to default by ID) — both sides
  remain independently selectable, so comparing two genuinely different
  schemas (whether across sandboxes or the same sandbox) works too, and
  the tab says so explicitly whenever the two selected titles differ.

## Development

```bash
pip install -r requirements-dev.txt   # runtime deps + pytest/pyflakes
python -m pytest                        # unit tests + Streamlit AppTest page-render suite
python -m pyflakes aep_monitor app.py poller_cli.py tests
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for conventions (mock-first development, where
business logic vs. UI code belongs, how to add a new Adobe API integration) and
[`SECURITY.md`](SECURITY.md) to report a vulnerability privately. Licensed under
[MIT](LICENSE).

## Project layout

```
app.py                   Streamlit entry point / page router
poller_cli.py             Standalone poll-once-and-exit script for cron
datastream_map.sample.json  Template + mock mode's demo content for the file below (committed)
datastream_map.json         Real, tenant-specific datastream->dataset mapping (git-ignored, see below)
aep_monitor/
  config.py                Settings (pydantic-settings, .env-backed)
  auth.py                   Adobe IMS token issuance/caching
  errors.py, retry.py       Friendly errors + transient-failure retry policy
  database.py               SQLite: history snapshots + alert log
  data.py                    Mock/live fetch, parsed into consistent rows
  datastream_map.py          Loader for datastream_map.json/.sample.json (see Overview's lineage chart)
  poller.py                  fetch -> snapshot -> evaluate alerts, per product
  alerts.py                  Alert conditions, dedupe, Slack push
  clients/
    base.py                    Shared HTTP plumbing (pacing, auth headers, errors)
    aep.py, reactor.py,        One client + parse_*() per product
    cja.py, audit.py,
    observability.py, quota.py,
    segmentation.py,
    query_service.py,
    user_management.py
    mock.py                    Sample data, shaped like raw API responses
  ui/                        One module per Streamlit page
tests/                     pytest — business logic (unit) + tests/test_app_pages.py (Streamlit AppTest)
```
