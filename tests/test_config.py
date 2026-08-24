from __future__ import annotations

"""Settings is constructed directly with explicit kwargs in every test here
(never via the module-level `settings` singleton). `_env_file=None` is
required, not cosmetic: without it, pydantic-settings still reads a real
`.env` in the current directory for any field not passed explicitly — a
developer's own `.env` (created by start-unix.sh, holding real values once
they've gone live) would otherwise leak into "isolated" test instances and
make these tests pass or fail depending on whose machine runs them."""

from aep_monitor.config import Settings


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_sandbox_list_defaults_to_the_single_configured_sandbox():
    settings = _settings(adobe_sandbox="prod", adobe_sandboxes="")
    assert settings.sandbox_list == ["prod"]


def test_sandbox_list_parses_comma_separated_names_and_trims_whitespace():
    settings = _settings(adobe_sandboxes="prod, dev , stage")
    assert settings.sandbox_list == ["prod", "dev", "stage"]


def test_sandbox_list_ignores_empty_entries():
    settings = _settings(adobe_sandboxes="prod,,dev,")
    assert settings.sandbox_list == ["prod", "dev"]


def test_sandbox_list_is_empty_when_nothing_is_configured_at_all():
    settings = _settings(adobe_sandbox="", adobe_sandboxes="")
    assert settings.sandbox_list == []


def test_adobe_configured_requires_all_four_primary_fields():
    incomplete = _settings(adobe_org_id="org", adobe_client_id="id")
    complete = _settings(adobe_org_id="org", adobe_client_id="id", adobe_client_secret="secret", adobe_scopes="scope")
    assert incomplete.adobe_configured is False
    assert complete.adobe_configured is True


def test_adobe_configured_is_false_when_org_id_is_missing_even_with_credentials_set():
    settings = _settings(adobe_client_id="id", adobe_client_secret="secret", adobe_scopes="scope", adobe_org_id="")
    assert settings.adobe_configured is False
