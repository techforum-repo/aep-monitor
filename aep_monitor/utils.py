from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Coroutine, TypeVar

import pandas as pd

T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Bridge an async client call into Streamlit's sync page code."""
    return asyncio.run(coro)


def safe_dict(value: Any) -> dict[str, Any]:
    """Coerce a value a parser assumed would be a nested object into an
    empty dict when it isn't one, instead of leaving a landmine for the
    next `.get()` call. Real-world case this exists for: a live
    Observability Insights response put a metric's name directly as a
    *string* under `entry["metric"]`, where the parser had assumed a
    nested `{"name": ...}` object (`entry.get("metric").get("name")`) —
    crashing with `'str' object has no attribute 'get'` the first time it
    ran against a live tenant instead of Adobe's own example response.
    `.get("key") or {}` alone doesn't protect against this: `or` only
    falls back on a falsy value, and a non-empty string is truthy. Every
    `clients/*.py` parse_*() function that reaches one level into a field
    assumed-but-not-guaranteed to be a nested object should wrap that
    access in this, not just `or {}`."""
    return value if isinstance(value, dict) else {}

# Leading characters that make Excel/Sheets/Numbers interpret a CSV cell as a
# formula instead of literal text (CSV/formula injection, OWASP-recognized).
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> Any:
    """Neutralize CSV/formula injection: a cell starting with =, +, -, @, or a
    tab is prefixed with a single quote so spreadsheet apps treat it as
    literal text instead of executing it as a formula when a downstream user
    opens the export (flow/property/connection names come from Adobe, but a
    tag or dataset name is still free text someone typed)."""
    if not isinstance(value, str) or not value:
        return value
    return f"'{value}" if value[0] in _FORMULA_TRIGGER_CHARS else value


def safe_csv(df: pd.DataFrame, *, index: bool = False) -> bytes:
    """CSV export with formula-injection protection applied to every text
    column, encoded as UTF-8 with a BOM (`utf-8-sig`) rather than plain
    UTF-8. Reported live: the "—" this app uses everywhere as a "no value"
    placeholder (and the emoji status pills some tables also export — see
    ui/shared.py's status_pill()) rendered as mojibake after downloading —
    Excel, without a BOM, doesn't reliably auto-detect a CSV as UTF-8 and
    falls back to a system codepage, mangling any non-ASCII byte sequence.
    Returns bytes (not str) so st.download_button() passes them through
    unchanged instead of re-encoding losing the BOM."""
    sanitized = df.copy()
    for column in sanitized.columns:
        if sanitized[column].dtype == object:
            sanitized[column] = sanitized[column].map(sanitize_csv_cell)
    return sanitized.to_csv(index=index).encode("utf-8-sig")


def sanitize_log_field(value: Any) -> str:
    """Replace control characters (CR/LF/tab/...) with spaces before writing
    free-text values to the flat-file log — otherwise a crafted value could
    forge additional fake-looking log lines."""
    return "".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in str(value))


def harden_file_permissions(path: Path, *, mode: int = 0o600) -> None:
    """Restrict a local data file (SQLite DB, log file, .env) to the owning
    user only. Defaults to 0o600; pass mode=0o700 for a directory.

    POSIX only — chmod doesn't provide equivalent access control on Windows,
    so this is a no-op there. Best-effort: never raises, so it can't block
    app startup or logging."""
    if os.name == "nt":
        return
    try:
        path.chmod(mode)
    except OSError:
        pass
