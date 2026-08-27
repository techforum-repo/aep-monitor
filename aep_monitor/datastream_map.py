from __future__ import annotations

"""Loads the local, git-ignored datastream -> {name, dataset} mapping this
app can't discover via any public Adobe API.

A property's Web SDK extension already carries its own configured
datastream id in Reactor's own, fully public, already-used API (see
clients/reactor.py's _extract_datastream_id()) — what's missing is the
datastream's *name* and which dataset it forwards to, which Adobe doesn't
expose via any documented API at all (confirmed: Adobe staff have
acknowledged an internal API for this at edge.adobe.io, but explicitly
not publicly documented or supported — see README Known Limitations).
This file is the one deliberate manual step in an otherwise
fully-automated lineage chain: a human who configured Datastreams already
knows this mapping, so it's recorded once here instead of guessed at.

DATASTREAM_MAP_PATH (git-ignored, see .gitignore) is the real,
per-tenant file. DATASTREAM_MAP_SAMPLE_PATH (committed) is both the
documented template *and* mock mode's demo content — the same ".env vs
.env.example" convention as every other local, tenant-specific file in
this app.
"""

import json
from pathlib import Path

from .logging_setup import get_logger

DATASTREAM_MAP_PATH = Path(__file__).resolve().parent.parent / "datastream_map.json"
DATASTREAM_MAP_SAMPLE_PATH = Path(__file__).resolve().parent.parent / "datastream_map.sample.json"


def load_datastream_map() -> dict[str, dict[str, str]]:
    """{datastream_id: {"name": ..., "dataset_id": ...}} — the real file if
    it exists, falling back to the committed sample (so this feature is
    explorable before any tenant-specific file has been created, same as
    every other mock-first convention in this app), or an empty dict if
    neither exists or the file is malformed. A bad local file is logged,
    not raised — it must not break the whole lineage view over one typo."""
    path = DATASTREAM_MAP_PATH if DATASTREAM_MAP_PATH.exists() else DATASTREAM_MAP_SAMPLE_PATH
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        get_logger().warning("Failed to read %s: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    entries: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            entries[str(key)] = {"name": str(value.get("name") or ""), "dataset_id": str(value.get("dataset_id") or "")}
    return entries


def datastream_map_source() -> str:
    """Which file is actually in effect right now — used by the UI to say
    plainly whether it's showing your real, maintained mapping or just the
    committed sample, rather than leaving that ambiguous."""
    if DATASTREAM_MAP_PATH.exists():
        return str(DATASTREAM_MAP_PATH.name)
    if DATASTREAM_MAP_SAMPLE_PATH.exists():
        return f"{DATASTREAM_MAP_SAMPLE_PATH.name} (sample — create {DATASTREAM_MAP_PATH.name} with your own mapping)"
    return "(none found)"
