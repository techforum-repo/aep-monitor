from __future__ import annotations

"""Generic "compare two lists of named items" diff — the shared engine
behind the Compare page's Schemas, DC Properties, and CJA Data Views tabs.
Pure and independently testable, no Streamlit import.
"""

from typing import Any


def diff_by_key(
    items_a: list[dict[str, Any]],
    items_b: list[dict[str, Any]],
    key: str,
    compare_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Match items from two lists by `item[key]` (e.g. a field path, an
    extension name) and classify them:
    - `only_a` / `only_b`: present on one side only.
    - `common`: present on both, each as `{"key", "a", "b", "changed_fields"}`
      — `changed_fields` lists which of `compare_fields` differ between the
      two sides (e.g. a schema field whose `type` changed between
      sandboxes), so a "common" item can still be flagged as drifted
      rather than treated as identical just because it exists on both
      sides.

    All three result lists are sorted by key for stable, diffable output."""
    by_key_a = {str(item.get(key, "")): item for item in items_a}
    by_key_b = {str(item.get(key, "")): item for item in items_b}
    keys_a, keys_b = set(by_key_a), set(by_key_b)

    only_a = [by_key_a[k] for k in sorted(keys_a - keys_b)]
    only_b = [by_key_b[k] for k in sorted(keys_b - keys_a)]

    common: list[dict[str, Any]] = []
    for k in sorted(keys_a & keys_b):
        item_a, item_b = by_key_a[k], by_key_b[k]
        changed = [f for f in (compare_fields or []) if item_a.get(f) != item_b.get(f)]
        common.append({"key": k, "a": item_a, "b": item_b, "changed_fields": changed})

    return {"only_a": only_a, "only_b": only_b, "common": common}
