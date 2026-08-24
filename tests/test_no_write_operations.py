from __future__ import annotations

"""Enforces, as a regression-tested guarantee (not just a claim in
SECURITY.md/README), that this app never issues a mutating request to any
Adobe API — every Adobe-facing call is a GET, with exactly one documented
exception (Observability Insights' /metrics query, which is a read-only
metrics query despite using POST — see clients/observability.py).

This is a static source scan, not a live HTTP check: it greps every
clients/*.py file's literal HTTP-method string constants and asserts
nothing outside the whitelist below appears. A future PUT/PATCH/DELETE (or
an additional POST) added anywhere in clients/ fails this test immediately
and requires a deliberate, explicit edit to this whitelist to pass —
exactly the trip-wire this exists to provide. Client files are the right
scope: every actual `httpx` call in this app funnels through
BaseAdobeClient._request()/get() in clients/base.py, called only from
clients/*.py — ui/*.py and data.py never construct requests directly.
"""

import re
from pathlib import Path

CLIENTS_DIR = Path(__file__).resolve().parent.parent / "aep_monitor" / "clients"

# Files intentionally excluded: base.py (the request plumbing itself, whose
# own get()/_request() signatures are checked separately below, not by this
# whitelist scan), mock.py (sample data, never makes a real request),
# __init__.py (just wiring, no request calls).
_SCANNED_FILES = [
    "aep.py", "audit.py", "cja.py", "observability.py", "quota.py",
    "reactor.py", "schema_registry.py",
]

# (filename, method) -> exact number of literal occurrences allowed. Any
# non-GET method not listed here, or a listed one appearing more times than
# allowed, fails the test.
_ALLOWED_NON_GET: dict[tuple[str, str], int] = {
    ("observability.py", "POST"): 1,  # /metrics query — see module docstring above.
}

_METHOD_LITERAL_RE = re.compile(r'''["'](GET|POST|PUT|PATCH|DELETE)["']''')


def test_no_client_file_issues_a_disallowed_http_method():
    for filename in _SCANNED_FILES:
        path = CLIENTS_DIR / filename
        source = path.read_text()
        counts: dict[str, int] = {}
        for match in _METHOD_LITERAL_RE.finditer(source):
            method = match.group(1)
            counts[method] = counts.get(method, 0) + 1

        for method, count in counts.items():
            if method == "GET":
                continue
            allowed = _ALLOWED_NON_GET.get((filename, method), 0)
            assert count == allowed, (
                f"{filename} contains {count} literal {method!r} method reference(s), "
                f"but only {allowed} are whitelisted for this app's no-write-operations "
                f"guarantee. If this is a deliberate, reviewed new read-only endpoint that "
                f"happens to use {method} (like Observability Insights' /metrics query), add "
                f"it to _ALLOWED_NON_GET above explicitly. If it's a mutating call, it "
                f"shouldn't be here at all — this app is read-only by design."
            )


def test_base_client_get_helper_is_hardcoded_to_get_and_cannot_be_overridden():
    """The one place a method string could sneak past the per-file scan
    above: if self.get()'s hardcoded "GET" were ever parameterized (e.g.
    accepting a method= kwarg). Pin its signature directly."""
    from aep_monitor.clients.base import BaseAdobeClient
    import inspect

    source = inspect.getsource(BaseAdobeClient.get)
    assert '"GET"' in source
    assert "method" not in inspect.signature(BaseAdobeClient.get).parameters
