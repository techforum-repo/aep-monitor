from __future__ import annotations

"""Enforces, as a regression-tested guarantee, that every st.dataframe()/
st.plotly_chart() call across the whole app passes an explicit, unique
`key=`.

Without one, Streamlit derives an element's identity from its call-site
position and argument hash — which isn't stable enough across two different
pages that happen to render a table/chart at a structurally similar spot.
Real, reported symptom this caused: switching from one page to another left
part of the *old* page's table or chart still visible until a hard browser
reload forced a clean remount — happening across every page, because not a
single st.dataframe()/st.plotly_chart() call in the app had a key at all.

This is a static source scan, not a live Streamlit render check (test_app_pages.py's
AppTest suite already covers "does every page render without an exception,"
which happens to also catch a *duplicate* key via Streamlit's own runtime
error, but not a *missing* one — Streamlit doesn't require a key at all, so
a missing one fails silently at the UI level, not at import/render time).
A future `st.dataframe(...)`/`st.plotly_chart(...)` call added anywhere in
`aep_monitor/ui/` without a `key=` argument fails this test immediately.
"""

import re
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent / "aep_monitor" / "ui"


def _calls_missing_key(source: str) -> list[str]:
    missing = []
    for match in re.finditer(r"st\.(dataframe|plotly_chart)\(", source):
        start = match.end() - 1
        depth = 0
        i = start
        while True:
            if source[i] == "(":
                depth += 1
            elif source[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        call = source[match.start() : i + 1]
        if "key=" not in call:
            missing.append(call)
    return missing


def test_every_dataframe_and_plotly_chart_call_has_an_explicit_key():
    offenders: dict[str, list[str]] = {}
    for path in sorted(UI_DIR.glob("*.py")):
        missing = _calls_missing_key(path.read_text())
        if missing:
            offenders[str(path)] = missing
    assert not offenders, f"st.dataframe()/st.plotly_chart() calls missing key=: {offenders}"


def test_static_widget_keys_are_globally_unique():
    """f-string keys (built per-loop-iteration, e.g. per quota name) are
    exempted — their uniqueness depends on runtime data, not the source
    text, and collisions there are covered by test_app_pages.py's AppTest
    suite actually rendering the page. Plain string keys have no such
    excuse: two identical literal `key="..."` calls anywhere in the app
    would collide the moment both render in the same script run."""
    seen: dict[str, str] = {}
    dupes: dict[str, list[str]] = {}
    for path in sorted(UI_DIR.glob("*.py")):
        source = path.read_text()
        for match in re.finditer(r'key=(["\'])((?:(?!\1).)*)\1', source):
            key = match.group(2)
            if key in seen and seen[key] != str(path):
                dupes.setdefault(key, [seen[key]]).append(str(path))
            else:
                seen[key] = str(path)
    assert not dupes, f"Duplicate static widget keys across files: {dupes}"
