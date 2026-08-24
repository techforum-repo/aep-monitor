# Contributing

Thanks for considering a contribution. This is a small, focused tool — please keep changes
scoped and in the same spirit as the existing code.

## Getting started

```
git clone <your fork>
cd aep-monitor
python3 -m venv .venv && source .venv/bin/activate   # or start-unix.sh / start-windows.bat
pip install -r requirements-dev.txt   # runtime deps + pytest/pyflakes; use requirements.txt alone for a deploy
cp .env.example .env      # defaults to mock mode — no Adobe credentials needed
python -m pytest
streamlit run app.py
```

Mock mode (`MOCK_MODE=true`, the default) is enough for almost all development — every
page has realistic sample data from `aep_monitor/clients/mock.py`. You won't need real
Adobe credentials unless you're specifically working on a live client
(`aep_monitor/clients/{aep,reactor,cja,audit,observability,quota}.py`).

## Before opening a PR

- `python -m pytest` — the full suite should pass. It's a few seconds for the unit tests;
  `tests/test_app_pages.py` (Streamlit `AppTest`) is the slower part but still runs entirely
  against mock data and a temp SQLite file, no network access needed.
- `python -m pyflakes aep_monitor app.py poller_cli.py tests` should be clean.
- If your change touches a `aep_monitor/ui/*.py` page, prefer adding a Streamlit `AppTest`
  case (see `tests/test_app_pages.py`) over a manual click-through description — this exact
  mechanism has already caught two real bugs during development (a settings field-name typo,
  and a UI section that was unreachable behind an early `return`) that a plain unit test of
  business logic wouldn't have.
- Business logic (`data.py`, `alerts.py`, `poller.py`, `database.py`, `errors.py`, `retry.py`,
  every `clients/*.py` module's `parse_*()` functions) is intentionally Streamlit-free — keep
  it that way so it stays independently testable. UI-only concerns belong in
  `aep_monitor/ui/*.py`.
- If you're changing `aep_monitor/database.py`'s schema, add a migration path the way
  `initialize()` already does (`CREATE TABLE IF NOT EXISTS`, `CREATE UNIQUE INDEX IF NOT
  EXISTS`) — existing users' local `aep_monitor.db` shouldn't break on upgrade.
- A new Adobe API integration should follow the existing shape: a `clients/<name>.py` module
  subclassing `BaseAdobeClient`, matching `parse_*()` functions, mock data in `clients/mock.py`
  shaped like the *raw* API response (not the parsed row — see that file's docstring), and
  wired into `data.py`'s mock/live branch. Be explicit in comments/README about which parts of
  the integration were actually verified against Adobe's docs/Postman collections vs. which are
  best-effort/unverified — several existing clients (Audit Query, Observability Insights) do
  this deliberately rather than presenting guessed field names as confirmed.
- Keep secrets out of it: every Adobe credential is `.env`-only by design (see `.env.example`)
  — don't add a UI path that exposes or edits them.

## Reporting bugs

Include: which mode you were in (mock / live), which page, and steps to reproduce. If it's a
UI state bug (something shows the wrong data after a sequence of clicks/refreshes), that's
usually the most useful class of bug report for this app — please be specific about the
click/refresh order.
