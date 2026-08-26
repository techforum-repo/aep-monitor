from __future__ import annotations

"""SQLite storage: point-in-time snapshots (for history/trend charts) and the
open/resolved alert log. Everything the UI shows "live" comes straight from
an Adobe API call; everything charted "over time" comes from here, written
by each page's Refresh action.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import harden_file_permissions

DB_PATH = Path(__file__).resolve().parent.parent / "aep_monitor.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize() -> None:
    with _connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS aep_flow_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          checked_at TEXT NOT NULL,
          flow_id TEXT NOT NULL,
          flow_name TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT '',
          records_in INTEGER,
          records_out INTEGER,
          records_failed INTEGER
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS dc_property_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          checked_at TEXT NOT NULL,
          property_id TEXT NOT NULL,
          property_name TEXT NOT NULL DEFAULT '',
          extension_count INTEGER,
          extension_issue_count INTEGER,
          rule_count INTEGER,
          library_count INTEGER,
          library_issue_count INTEGER
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS cja_connection_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          checked_at TEXT NOT NULL,
          connection_id TEXT NOT NULL,
          connection_name TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT ''
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS quota_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          checked_at TEXT NOT NULL,
          quota_name TEXT NOT NULL,
          consumed REAL,
          quota REAL,
          pct_used REAL
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quota_snapshots_lookup ON quota_snapshots(quota_name, id DESC)"
        )
        conn.execute("""
        CREATE TABLE IF NOT EXISTS segment_job_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          checked_at TEXT NOT NULL,
          job_id TEXT NOT NULL,
          segment_id TEXT NOT NULL DEFAULT '',
          segment_name TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT ''
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS query_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          checked_at TEXT NOT NULL,
          query_id TEXT NOT NULL,
          name TEXT NOT NULL DEFAULT '',
          state TEXT NOT NULL DEFAULT ''
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS entity_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          entity_type TEXT NOT NULL,
          entity_key TEXT NOT NULL,
          entity_label TEXT NOT NULL,
          checked_at TEXT NOT NULL,
          payload_json TEXT NOT NULL
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_snapshots_lookup ON entity_snapshots(entity_type, entity_key, id DESC)"
        )
        conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          source TEXT NOT NULL,
          severity TEXT NOT NULL,
          title TEXT NOT NULL,
          message TEXT NOT NULL DEFAULT '',
          fingerprint TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0,
          resolved_at TEXT
        )""")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_open_fingerprint ON alerts(fingerprint) WHERE resolved=0"
        )
        conn.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS connection_checks (
          source TEXT PRIMARY KEY,
          checked_at TEXT NOT NULL,
          success INTEGER NOT NULL,
          mode TEXT NOT NULL,
          detail TEXT NOT NULL DEFAULT ''
        )""")
        conn.commit()
    # Holds Adobe org data (flow/property/connection names) — restrict to the
    # owning user (POSIX; no-op on Windows).
    harden_file_permissions(DB_PATH)


# --- Snapshots (history) ------------------------------------------------------

def record_aep_snapshots(rows: list[dict[str, Any]]) -> None:
    checked_at = _now()
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO aep_flow_snapshots(checked_at,flow_id,flow_name,status,records_in,records_out,records_failed)
               VALUES(?,?,?,?,?,?,?)""",
            [
                (checked_at, r["flow_id"], r["flow_name"], r["status"], r.get("records_in"), r.get("records_out"), r.get("records_failed"))
                for r in rows
            ],
        )
        conn.commit()


def record_dc_snapshots(rows: list[dict[str, Any]]) -> None:
    checked_at = _now()
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO dc_property_snapshots(checked_at,property_id,property_name,extension_count,extension_issue_count,rule_count,library_count,library_issue_count)
               VALUES(?,?,?,?,?,?,?,?)""",
            [
                (
                    checked_at, r["property_id"], r["property_name"], r.get("extension_count", 0),
                    r.get("extension_issue_count", 0), r.get("rule_count", 0), r.get("library_count", 0),
                    r.get("library_issue_count", 0),
                )
                for r in rows
            ],
        )
        conn.commit()


def record_cja_snapshots(rows: list[dict[str, Any]]) -> None:
    checked_at = _now()
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO cja_connection_snapshots(checked_at,connection_id,connection_name,status) VALUES(?,?,?,?)",
            [(checked_at, r["connection_id"], r["name"], r["status"]) for r in rows],
        )
        conn.commit()


def record_quota_snapshots(rows: list[dict[str, Any]]) -> None:
    checked_at = _now()
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO quota_snapshots(checked_at,quota_name,consumed,quota,pct_used) VALUES(?,?,?,?,?)",
            [(checked_at, r["name"], r.get("consumed"), r.get("quota"), r.get("pct_used")) for r in rows],
        )
        conn.commit()


def read_quota_history(quota_name: str | None = None, limit: int = 500) -> pd.DataFrame:
    query = "SELECT checked_at,quota_name,consumed,quota,pct_used FROM quota_snapshots"
    params: tuple[Any, ...] = ()
    if quota_name:
        query += " WHERE quota_name=?"
        params = (quota_name,)
    query += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    with _connect() as conn:
        return pd.read_sql_query(query, conn, params=params)


def record_segment_job_snapshots(rows: list[dict[str, Any]]) -> None:
    checked_at = _now()
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO segment_job_snapshots(checked_at,job_id,segment_id,segment_name,status) VALUES(?,?,?,?,?)",
            [(checked_at, r["job_id"], r.get("segment_id", ""), r.get("segment_name", ""), r["status"]) for r in rows],
        )
        conn.commit()


def record_query_snapshots(rows: list[dict[str, Any]]) -> None:
    checked_at = _now()
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO query_snapshots(checked_at,query_id,name,state) VALUES(?,?,?,?)",
            [(checked_at, r["query_id"], r.get("name", ""), r["state"]) for r in rows],
        )
        conn.commit()


def read_aep_history(flow_id: str | None = None, limit: int = 500) -> pd.DataFrame:
    query = "SELECT checked_at,flow_id,flow_name,status,records_in,records_out,records_failed FROM aep_flow_snapshots"
    params: tuple[Any, ...] = ()
    if flow_id:
        query += " WHERE flow_id=?"
        params = (flow_id,)
    query += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    with _connect() as conn:
        return pd.read_sql_query(query, conn, params=params)


def read_dc_history(property_id: str | None = None, limit: int = 500) -> pd.DataFrame:
    query = "SELECT checked_at,property_id,property_name,extension_count,extension_issue_count,rule_count,library_count,library_issue_count FROM dc_property_snapshots"
    params: tuple[Any, ...] = ()
    if property_id:
        query += " WHERE property_id=?"
        params = (property_id,)
    query += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    with _connect() as conn:
        return pd.read_sql_query(query, conn, params=params)


def read_cja_history(connection_id: str | None = None, limit: int = 500) -> pd.DataFrame:
    query = "SELECT checked_at,connection_id,connection_name,status FROM cja_connection_snapshots"
    params: tuple[Any, ...] = ()
    if connection_id:
        query += " WHERE connection_id=?"
        params = (connection_id,)
    query += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    with _connect() as conn:
        return pd.read_sql_query(query, conn, params=params)


def latest_checked_at(source: str) -> str | None:
    table = {
        "AEP": "aep_flow_snapshots",
        "Data Collection": "dc_property_snapshots",
        "CJA": "cja_connection_snapshots",
        "Quota": "quota_snapshots",
        "Segments": "segment_job_snapshots",
        "Query Service": "query_snapshots",
    }.get(source)
    if not table:
        return None
    with _connect() as conn:
        row = conn.execute(f"SELECT MAX(checked_at) FROM {table}").fetchone()  # noqa: S608 (fixed allowlist above)
    return row[0] if row else None


# --- Entity snapshots (drift detection for Compare's "vs. last snapshot" mode) ---
# One generic table for every entity type Compare can track drift on
# (schema, dataset, dc_property, cja_dataview) rather than four bespoke
# tables — the payload itself is an opaque JSON blob whose shape data.py's
# fetch_*_drift() functions know how to interpret per entity_type; this
# layer only stores and retrieves it. Unlike aep_flow_snapshots/
# dc_property_snapshots above (written on every "Refresh" click), a row
# here is only written when something explicitly opts in — see
# data.py's module docstring for why recording stays an opt-in side effect
# rather than happening inside every ordinary fetch call.

def record_entity_snapshot(entity_type: str, entity_key: str, entity_label: str, payload: Any) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO entity_snapshots(entity_type,entity_key,entity_label,checked_at,payload_json) VALUES(?,?,?,?,?)",
            (entity_type, entity_key, entity_label, _now(), json.dumps(payload)),
        )
        conn.commit()


def latest_entity_snapshot(entity_type: str, entity_key: str) -> dict[str, Any] | None:
    """The most recent snapshot for this entity — the baseline a new
    "vs. last snapshot" diff compares against. Call this *before*
    record_entity_snapshot() writes the new one, or it'll just return what
    you're about to write."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT entity_label, checked_at, payload_json FROM entity_snapshots "
            "WHERE entity_type=? AND entity_key=? ORDER BY id DESC LIMIT 1",
            (entity_type, entity_key),
        ).fetchone()
    if not row:
        return None
    return {"entity_label": row["entity_label"], "checked_at": row["checked_at"], "payload": json.loads(row["payload_json"])}


def list_known_entity_keys(entity_type: str) -> list[dict[str, str]]:
    """Every entity of this type that's ever had a snapshot recorded — one
    row per distinct entity_key, with its most recent label (via a
    max-id subquery, not a bare GROUP BY — SQLite's non-aggregated-column
    behavior under GROUP BY is undefined, which could silently surface a
    stale label from an older row instead of the current one). Used by
    poller_cli.py to keep known entities' snapshots fresh on a schedule
    without needing a UI visit; an entity nobody has ever compared "vs.
    last snapshot" for isn't swept, since there's no prior baseline to
    build drift history from yet."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT entity_key, entity_label FROM entity_snapshots
               WHERE entity_type=? AND id IN (
                   SELECT MAX(id) FROM entity_snapshots WHERE entity_type=? GROUP BY entity_key
               )
               ORDER BY entity_key""",
            (entity_type, entity_type),
        ).fetchall()
    return [{"entity_key": row["entity_key"], "entity_label": row["entity_label"]} for row in rows]


# --- Alerts --------------------------------------------------------------------

def upsert_alert(source: str, severity: str, title: str, message: str, fingerprint: str) -> bool:
    """Insert a new open alert unless one with the same fingerprint is
    already open — returns True only when a new row was actually created,
    so callers (alerts.py) know whether this is worth a Slack notification
    instead of re-notifying on every poll."""
    with _connect() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO alerts(created_at,source,severity,title,message,fingerprint,resolved) VALUES(?,?,?,?,?,?,0)",
                (_now(), source, severity, title, message, fingerprint),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            return False


def auto_resolve_missing(source: str, active_fingerprints: set[str]) -> int:
    """Resolve open alerts for `source` whose fingerprint is no longer in the
    latest poll's active set — i.e. the underlying condition cleared."""
    with _connect() as conn:
        rows = conn.execute("SELECT id, fingerprint FROM alerts WHERE source=? AND resolved=0", (source,)).fetchall()
        to_resolve = [row["id"] for row in rows if row["fingerprint"] not in active_fingerprints]
        if to_resolve:
            now = _now()
            conn.executemany(
                "UPDATE alerts SET resolved=1, resolved_at=? WHERE id=?",
                [(now, alert_id) for alert_id in to_resolve],
            )
            conn.commit()
    return len(to_resolve)


def resolve_alert(alert_id: int) -> None:
    with _connect() as conn:
        conn.execute("UPDATE alerts SET resolved=1, resolved_at=? WHERE id=?", (_now(), alert_id))
        conn.commit()


def list_alerts(resolved: bool | None = None, limit: int = 200) -> pd.DataFrame:
    query = "SELECT id,created_at,source,severity,title,message,resolved,resolved_at FROM alerts"
    params: tuple[Any, ...] = ()
    if resolved is not None:
        query += " WHERE resolved=?"
        params = (1 if resolved else 0,)
    query += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    with _connect() as conn:
        df = pd.read_sql_query(query, conn, params=params)
    if "resolved" in df.columns:
        df["resolved"] = df["resolved"].astype(bool)
    return df


def open_alert_counts() -> dict[str, int]:
    with _connect() as conn:
        rows = conn.execute("SELECT severity, COUNT(*) c FROM alerts WHERE resolved=0 GROUP BY severity").fetchall()
    return {row["severity"]: int(row["c"]) for row in rows}


# --- Settings overrides (non-secret) --------------------------------------------

def get_setting(key: str, default: str = "") -> str:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, _now()),
        )
        conn.commit()


# --- Diagnostics -----------------------------------------------------------------

def record_connection_check(source: str, success: bool, mode: str, detail: str = "") -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO connection_checks(source,checked_at,success,mode,detail) VALUES(?,?,?,?,?)
               ON CONFLICT(source) DO UPDATE SET checked_at=excluded.checked_at, success=excluded.success,
                   mode=excluded.mode, detail=excluded.detail""",
            (source, _now(), 1 if success else 0, mode, detail),
        )
        conn.commit()


def last_connection_checks() -> dict[str, dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT source, checked_at, success, mode, detail FROM connection_checks").fetchall()
    return {
        row["source"]: {"checked_at": row["checked_at"], "success": bool(row["success"]), "mode": row["mode"], "detail": row["detail"]}
        for row in rows
    }


def sqlite_health() -> dict[str, Any]:
    with _connect() as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    return {"integrity": str(integrity), "ok": str(integrity).lower() == "ok", "size_bytes": page_count * page_size, "path": str(DB_PATH)}


def table_counts() -> dict[str, int]:
    tables = [
        "aep_flow_snapshots", "dc_property_snapshots", "cja_connection_snapshots", "quota_snapshots",
        "segment_job_snapshots", "query_snapshots", "entity_snapshots", "alerts", "app_settings",
    ]
    with _connect() as conn:
        existing = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        return {t: int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in tables if t in existing}  # noqa: S608
