from __future__ import annotations

"""State, navigation, and small widgets shared across every page in
aep_monitor/ui/*. Page-specific rendering stays in that page's own module.
"""

import copy
from datetime import datetime, timezone

import streamlit as st

from ..config import settings
from ..errors import friendly_error

PAGE_NAMES = ["Overview", "AEP Ingestion", "Datasets", "Data Collection", "CJA", "Compare", "SDR", "Audit Log", "Alerts", "Diagnostics", "Settings"]

# Status colors follow a fixed, reserved palette (never reused for anything
# else) and are always paired with an icon + label — never color alone.
_GOOD = "🟢"
_WARNING = "🟡"
_CRITICAL = "🔴"
_NEUTRAL = "⚪"

_GOOD_STATES = {"success", "succeeded", "enabled", "published", "approved", "active", "healthy"}
_WARNING_STATES = {"pending", "submitted", "development", "disabled"}
_BAD_STATES = {"failed", "error", "rejected", "inactive", "deleted"}

CUSTOM_CSS = """<style>
.block-container{max-width:1450px;padding-top:1.35rem}
.hero{padding:1.1rem 1.35rem;border:1px solid #ddd;border-radius:16px;margin-bottom:1rem}
[data-testid=stMetric]{border:1px solid #ddd;padding:1rem;border-radius:14px}
.badge{padding:.25rem .55rem;border:1px solid #ccc;border-radius:999px;font-size:.8rem}
</style>"""

DEFAULT_STATE = {
    "aep_rows": None,
    "dc_rows": None,
    "cja_connections": None,
    "cja_dataviews": None,
    "audit_events": None,
    "quota_rows": None,
    "observability_metrics": None,
    "compare_rows": None,
    "sdr_dataviews": None,
    "sdr_schemas": None,
    "sdr_components_cache": {},
    "sdr_schema_fields_cache": {},
    "dataset_rows": None,
    "dataset_schema_titles": {},
}


def init_session_state() -> None:
    # deepcopy, not a bare reference: Streamlit runs one process for every
    # session, so a mutable default (a dict/list) assigned by reference
    # here would be the exact same object across every session — one
    # user's page mutating it (e.g. sdr_page.py's per-dataview cache) would
    # leak into every other session's state, live Adobe data included. A
    # scalar default (None/str/int) doesn't have this problem, but
    # deepcopy-ing unconditionally means nobody has to remember which is
    # which when adding a new default here.
    for key, value in DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = copy.deepcopy(value)


def get_active_sandbox() -> str:
    """The AEP sandbox every sandbox-scoped page (AEP Ingestion, Audit Log,
    SDR's AEP section, Overview's AEP card) should use — the sidebar
    switcher's current value, defaulting to the configured ADOBE_SANDBOX
    before the switcher has been touched. Session-only: never writes back
    to .env. Data Collection, CJA, and Quota are org-wide and never read
    this (see data.fetch_sandbox_comparison's docstring); Compare
    Sandboxes ignores it too — it's inherently multi-sandbox already, via
    ADOBE_SANDBOXES."""
    return st.session_state.get("active_sandbox") or settings.adobe_sandbox


def sandbox_changed_since_cache(cache_key: str, active_sandbox: str) -> bool:
    """True if `cache_key`'s cached value (if any) was fetched for a
    different sandbox than the one currently active — a page's
    `_ensure_loaded()` uses this instead of just `is None` so switching
    sandboxes triggers a refetch instead of silently showing stale data
    from the sandbox you just switched away from."""
    return st.session_state.get(f"{cache_key}_sandbox") != active_sandbox


def mark_cache_sandbox(cache_key: str, active_sandbox: str) -> None:
    st.session_state[f"{cache_key}_sandbox"] = active_sandbox


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown("## 📡 AEP · DC · CJA Monitor")
        page = st.radio("Navigation", PAGE_NAMES, label_visibility="collapsed", key="navigation")
        st.divider()
        mode = "Mock / demo data" if settings.mock_mode else "Live"
        st.markdown(f"<span class='badge'>{mode}</span>", unsafe_allow_html=True)
        if settings.mock_mode:
            st.caption("Set MOCK_MODE=false in .env once Adobe credentials are filled in.")
        st.divider()
        sandbox_options = settings.sandbox_list or ([settings.adobe_sandbox] if settings.adobe_sandbox else [])
        if sandbox_options:
            st.session_state.setdefault("active_sandbox", sandbox_options[0])
            # A previously-active sandbox that's since fallen out of
            # ADOBE_SANDBOXES (or ADOBE_SANDBOX changed) still needs to be
            # a selectable option, or the widget errors on an invalid value.
            if st.session_state["active_sandbox"] not in sandbox_options:
                sandbox_options = [st.session_state["active_sandbox"], *sandbox_options]
            st.selectbox(
                "AEP sandbox", sandbox_options, key="active_sandbox",
                help="Affects AEP Ingestion, Audit Log, SDR's AEP section, and Overview's AEP card. "
                     "Data Collection, CJA, and Quota are org-wide, not sandbox-scoped.",
            )
    return page


def render_hero() -> None:
    st.markdown(
        "<div class='hero'><h1>Adobe Experience Cloud Monitor</h1>"
        "<p>One dashboard for AEP ingestion health, Data Collection publish status, "
        "and CJA connections — with history, alerts, and an audit trail.</p></div>",
        unsafe_allow_html=True,
    )


def status_pill(state: str) -> str:
    """Icon + label — never color alone, per the reserved status palette."""
    normalized = str(state or "").strip().lower()
    if normalized in _GOOD_STATES:
        icon = _GOOD
    elif normalized in _WARNING_STATES:
        icon = _WARNING
    elif normalized in _BAD_STATES:
        icon = _CRITICAL
    else:
        icon = _NEUTRAL
    return f"{icon} {state or 'unknown'}"


def format_timestamp(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def render_friendly_error(exc: Exception, *, key: str, context: str = "") -> bool:
    """Plain-language error box instead of a raw traceback. Returns True if
    the user clicked Retry, so the caller can re-run the action inline."""
    info = friendly_error(exc)
    with st.container(border=True):
        st.error(f"**{info.title}**")
        if context:
            st.caption(context)
        if info.reasons:
            st.markdown("Possible reasons:\n\n" + "\n".join(f"- {reason}" for reason in info.reasons))
        with st.expander("Technical details"):
            st.code(str(exc) or "(no message)")
        if info.retryable:
            return st.button("Retry", key=key)
    return False


def refresh_button(label: str, key: str) -> bool:
    return st.button(f"🔄 {label}", key=key, type="primary")
