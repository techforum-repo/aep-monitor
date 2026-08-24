# Security Policy

## Reporting a vulnerability

If you find a security issue in this project, please report it privately rather than
opening a public GitHub issue — this tool handles Adobe API credentials and org/tenant
monitoring data, so a public issue could point at a live exposure before it's fixed.

Open a [GitHub Security Advisory](../../security/advisories/new) on this repository
("Report a vulnerability" under the Security tab). That reaches maintainers privately and
lets us coordinate a fix and disclosure timeline with you.

Please include:
- What you found and why it's exploitable (a reproduction, if possible)
- Which mode it applies to (mock / live) if relevant
- Your assessment of impact

## Scope

In scope: the application code in this repository (`app.py`, `aep_monitor/**`,
`poller_cli.py`).

Out of scope: vulnerabilities in Adobe's own AEP/CJA/Reactor/IMS services, or in
third-party dependencies (report those upstream — see `requirements.txt`; Dependabot is
enabled here to track known-vulnerable versions).

## What this app already does

Before reporting "there's no login screen" or "the SQLite file isn't encrypted" — these
are known, deliberate scope limits, not oversights:

- This is a trusted-operator tool, not a multi-tenant service. It has no built-in
  authentication — anyone who can run the app already has whatever Adobe access its
  configured credential grants.
- The Adobe credential (`ADOBE_CLIENT_SECRET`) and `SLACK_WEBHOOK_URL` are `.env`-only
  and never exposed in the UI — the Settings page masks every secret it displays
  (`_mask()` in `aep_monitor/ui/settings_page.py`).
- `.env` and `aep_monitor.db` are both permission-restricted to the owning user on POSIX
  systems at startup (`harden_file_permissions()` in `aep_monitor/utils.py`, called from
  `config.harden_env_file()` and `database.initialize()`) — but neither is encrypted at
  rest. If you're deploying this somewhere other than a single operator's own machine, add
  disk encryption and don't skip the `.gitignore` entries that keep both out of version
  control.
- Alert titles/messages and CSV exports pass through `sanitize_log_field()` /
  `safe_csv()` (`aep_monitor/utils.py`) specifically to prevent log-line forgery and
  spreadsheet formula injection from values that ultimately originate in Adobe API
  responses (flow names, connection names, ...) — free text you don't fully control.
- Adobe credentials are read-only by design across every client in `aep_monitor/clients/`
  — this app only ever issues `GET` (and one documented `POST /metrics` for Observability
  Insights, itself a read-only query) requests. It cannot modify anything in your Adobe
  org. This isn't just a claim: `tests/test_no_write_operations.py` statically scans every
  client file's HTTP-method calls against a whitelist and fails the suite if a
  PUT/PATCH/DELETE (or an unreviewed extra POST) is ever introduced.

If you're unsure whether something is a genuine vulnerability or one of the above,
report it anyway — worst case we point you at this file.
