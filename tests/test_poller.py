from __future__ import annotations

"""refresh_all()'s per-leg error isolation — a real live bug pinned down as
a regression test: one leg raising (Segments, on a malformed request) used
to abort the whole dict literal, silently losing every *other* leg's
already-fetched data too (Quota's own fetch had already succeeded). Each
leg is now independent; see poller.py's refresh_all() docstring."""

from aep_monitor import poller


def test_refresh_all_returns_results_for_every_leg_when_nothing_fails(temp_db):
    results = poller.refresh_all()
    assert set(results.keys()) == {"aep", "dc", "cja", "quota", "segments", "query_service", "errors"}
    assert results["errors"] == {}
    assert results["aep"]  # mock data is non-empty
    assert results["quota"]


def test_a_failing_leg_does_not_lose_the_other_legs_results(temp_db, monkeypatch):
    """Pins the actual bug: Segments raising must not cost Quota (or
    anything else) its own already-successful fetch."""
    def _boom(sandbox=None):
        raise RuntimeError("Adobe returned HTTP 400: The expression used is invalid")

    monkeypatch.setattr(poller, "refresh_segments", _boom)

    results = poller.refresh_all()

    assert results["segments"] == []
    assert "segments" in results["errors"]
    assert results["aep"]  # untouched by the segments failure
    assert results["quota"]  # untouched by the segments failure


def test_a_failing_leg_is_logged_but_does_not_raise(temp_db, monkeypatch):
    monkeypatch.setattr(poller, "refresh_query_service", lambda sandbox=None: (_ for _ in ()).throw(RuntimeError("boom")))
    results = poller.refresh_all()  # must not raise
    assert results["query_service"] == []
    assert "boom" in str(results["errors"]["query_service"])
