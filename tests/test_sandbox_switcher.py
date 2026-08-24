from __future__ import annotations

"""get_active_sandbox()/sandbox_changed_since_cache()/mark_cache_sandbox()
— the pure logic behind the global sandbox switcher (sidebar), tested
directly against a plain dict standing in for st.session_state, the same
approach test_app_pages.py's init_session_state regression test uses.
"""

from aep_monitor.config import settings
from aep_monitor.ui import shared


def test_get_active_sandbox_defaults_to_the_configured_sandbox_before_switcher_is_touched(monkeypatch):
    monkeypatch.setattr(shared.st, "session_state", {})
    monkeypatch.setattr(settings, "adobe_sandbox", "prod")
    assert shared.get_active_sandbox() == "prod"


def test_get_active_sandbox_reflects_the_switcher_once_set(monkeypatch):
    monkeypatch.setattr(shared.st, "session_state", {"active_sandbox": "dev"})
    assert shared.get_active_sandbox() == "dev"


def test_sandbox_changed_since_cache_is_true_before_any_fetch_has_happened(monkeypatch):
    monkeypatch.setattr(shared.st, "session_state", {})
    assert shared.sandbox_changed_since_cache("aep_rows", "prod") is True


def test_mark_cache_sandbox_then_sandbox_changed_since_cache_round_trips(monkeypatch):
    session: dict = {}
    monkeypatch.setattr(shared.st, "session_state", session)
    shared.mark_cache_sandbox("aep_rows", "prod")
    assert shared.sandbox_changed_since_cache("aep_rows", "prod") is False
    assert shared.sandbox_changed_since_cache("aep_rows", "dev") is True


def test_different_cache_keys_track_their_sandbox_independently(monkeypatch):
    """Regression-shaped: aep_rows and observability_metrics are refreshed
    by separate buttons on the AEP page and must not share one staleness
    flag — switching sandbox and refreshing only one of the two shouldn't
    make the other look fresh when it's actually stale."""
    session: dict = {}
    monkeypatch.setattr(shared.st, "session_state", session)
    shared.mark_cache_sandbox("aep_rows", "prod")
    assert shared.sandbox_changed_since_cache("aep_rows", "prod") is False
    assert shared.sandbox_changed_since_cache("observability_metrics", "prod") is True
