from __future__ import annotations

"""Shared, autouse test fixtures."""

import pytest

from aep_monitor import database


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point database.py at a throwaway SQLite file for the duration of one
    test — every test that touches alerts/snapshots/settings needs this so
    tests never share state with each other or with a real aep_monitor.db."""
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.initialize()
    return database.DB_PATH
