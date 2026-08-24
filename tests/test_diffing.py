from __future__ import annotations

from aep_monitor.diffing import diff_by_key


def test_diff_by_key_splits_only_a_only_b_and_common():
    items_a = [{"name": "shared"}, {"name": "only-a"}]
    items_b = [{"name": "shared"}, {"name": "only-b"}]
    result = diff_by_key(items_a, items_b, key="name")
    assert [i["name"] for i in result["only_a"]] == ["only-a"]
    assert [i["name"] for i in result["only_b"]] == ["only-b"]
    assert [c["key"] for c in result["common"]] == ["shared"]


def test_diff_by_key_flags_changed_fields_on_common_items():
    items_a = [{"name": "field1", "type": "string", "description": "old"}]
    items_b = [{"name": "field1", "type": "integer", "description": "old"}]
    result = diff_by_key(items_a, items_b, key="name", compare_fields=["type", "description"])
    common = result["common"][0]
    assert common["changed_fields"] == ["type"]


def test_diff_by_key_common_item_with_no_changes_has_empty_changed_fields():
    items_a = [{"name": "field1", "type": "string"}]
    items_b = [{"name": "field1", "type": "string"}]
    result = diff_by_key(items_a, items_b, key="name", compare_fields=["type"])
    assert result["common"][0]["changed_fields"] == []


def test_diff_by_key_results_are_sorted_by_key():
    items_a = [{"name": "zebra"}, {"name": "apple"}]
    items_b = [{"name": "zebra"}, {"name": "apple"}]
    result = diff_by_key(items_a, items_b, key="name")
    assert [c["key"] for c in result["common"]] == ["apple", "zebra"]


def test_diff_by_key_handles_empty_lists_on_either_side():
    result = diff_by_key([], [{"name": "x"}], key="name")
    assert result["only_a"] == []
    assert [i["name"] for i in result["only_b"]] == ["x"]
    assert result["common"] == []

    result = diff_by_key([{"name": "x"}], [], key="name")
    assert [i["name"] for i in result["only_a"]] == ["x"]
    assert result["only_b"] == []


def test_diff_by_key_without_compare_fields_still_populates_common():
    items_a = [{"name": "x", "type": "string"}]
    items_b = [{"name": "x", "type": "integer"}]
    result = diff_by_key(items_a, items_b, key="name")  # no compare_fields
    assert result["common"][0]["changed_fields"] == []
    assert result["common"][0]["a"]["type"] == "string"
    assert result["common"][0]["b"]["type"] == "integer"
