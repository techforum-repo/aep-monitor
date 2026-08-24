from __future__ import annotations

import asyncio

import pandas as pd

from aep_monitor.utils import run_async, safe_csv, safe_dict, sanitize_csv_cell, sanitize_log_field


def test_safe_dict_passes_through_a_real_dict():
    assert safe_dict({"a": 1}) == {"a": 1}


def test_safe_dict_coerces_non_dict_values_to_empty():
    # The exact live-bug case: a parser assumed a nested object
    # (entry["metric"].get("name")) but the real API sent a plain string
    # in that slot — 'str' object has no attribute 'get'.
    assert safe_dict("a plain string") == {}
    assert safe_dict(None) == {}
    assert safe_dict([1, 2, 3]) == {}
    assert safe_dict(42) == {}


def test_sanitize_csv_cell_neutralizes_formula_trigger_characters():
    assert sanitize_csv_cell("=cmd|'/c calc'!A0") == "'=cmd|'/c calc'!A0"
    assert sanitize_csv_cell("+1+1") == "'+1+1"
    assert sanitize_csv_cell("-2+3") == "'-2+3"
    assert sanitize_csv_cell("@SUM(A1:A9)") == "'@SUM(A1:A9)"


def test_sanitize_csv_cell_leaves_ordinary_text_and_non_strings_alone():
    assert sanitize_csv_cell("Web SDK — Prod Events") == "Web SDK — Prod Events"
    assert sanitize_csv_cell("") == ""
    assert sanitize_csv_cell(None) is None
    assert sanitize_csv_cell(42) == 42
    assert sanitize_csv_cell(True) is True


def test_safe_csv_sanitizes_every_text_column_but_not_numeric_columns():
    df = pd.DataFrame([
        {"flow": "=HYPERLINK(\"http://evil\")", "records": 3, "status": "a@example.com"},
        {"flow": "Normal Flow", "records": 5, "status": "=cmd"},
    ])
    output = safe_csv(df).decode("utf-8-sig")
    assert "'=HYPERLINK" in output
    assert "'=cmd" in output
    assert "Normal Flow" in output
    assert ",3," in output or ",3\n" in output or ",3\r\n" in output  # numeric untouched


def test_safe_csv_matches_plain_to_csv_when_nothing_dangerous():
    df = pd.DataFrame([{"a": "hello", "b": 1}])
    assert safe_csv(df) == df.to_csv(index=False).encode("utf-8-sig")


def test_safe_csv_returns_bytes_with_a_utf8_bom():
    """download_button() needs bytes, not str, for the BOM to survive
    unchanged (Streamlit re-encodes a str as plain UTF-8, dropping it)."""
    df = pd.DataFrame([{"a": "hello"}])
    output = safe_csv(df)
    assert isinstance(output, bytes)
    assert output.startswith(b"\xef\xbb\xbf")


def test_safe_csv_round_trips_non_ascii_placeholder_characters():
    """Regression: reported live — the "—" this app uses everywhere as a
    "no value" placeholder, and the emoji status pills some tables also
    export, rendered as mojibake in Excel after downloading (no BOM ->
    Excel guesses a system codepage instead of UTF-8 for a plain-UTF-8
    CSV). Decoding with utf-8-sig (BOM-aware) must recover the exact
    original text, not a mangled substitute."""
    df = pd.DataFrame([{"labels": "—", "status": "🟢 active"}])
    output = safe_csv(df)
    decoded = output.decode("utf-8-sig")
    assert "—" in decoded
    assert "🟢 active" in decoded


def test_sanitize_log_field_replaces_control_characters_to_prevent_log_injection():
    # A crafted value containing CR/LF could otherwise forge additional
    # fake-looking log lines when written to the flat-file log.
    assert sanitize_log_field("normal text") == "normal text"
    assert sanitize_log_field("line1\nFAKE ERROR: breach\r\nline2") == "line1 FAKE ERROR: breach  line2"
    assert "\n" not in sanitize_log_field("a\nb")
    assert "\r" not in sanitize_log_field("a\rb")


def test_run_async_bridges_a_coroutine_to_a_plain_return_value():
    async def _coro():
        await asyncio.sleep(0)
        return "done"

    assert run_async(_coro()) == "done"
