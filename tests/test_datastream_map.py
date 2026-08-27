from __future__ import annotations

"""load_datastream_map()/datastream_map_source() — the git-ignored,
human-maintained file that closes the one hop no public Adobe API exposes
(which dataset a Web SDK datastream forwards to). Same ".env vs
.env.example" convention as the rest of this app: a missing real file
falls back to the committed sample rather than an error."""

import json

from aep_monitor import datastream_map


def test_falls_back_to_the_sample_file_when_the_real_one_is_absent(tmp_path, monkeypatch):
    real = tmp_path / "datastream_map.json"
    sample = tmp_path / "datastream_map.sample.json"
    sample.write_text(json.dumps({"ds-1": {"name": "Sample Stream", "dataset_id": "abc"}}))
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_PATH", real)
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_SAMPLE_PATH", sample)

    result = datastream_map.load_datastream_map()

    assert result == {"ds-1": {"name": "Sample Stream", "dataset_id": "abc"}}
    assert "sample" in datastream_map.datastream_map_source()


def test_prefers_the_real_file_over_the_sample_when_both_exist(tmp_path, monkeypatch):
    real = tmp_path / "datastream_map.json"
    sample = tmp_path / "datastream_map.sample.json"
    real.write_text(json.dumps({"ds-real": {"name": "Real Stream", "dataset_id": "xyz"}}))
    sample.write_text(json.dumps({"ds-sample": {"name": "Sample Stream", "dataset_id": "abc"}}))
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_PATH", real)
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_SAMPLE_PATH", sample)

    result = datastream_map.load_datastream_map()

    assert result == {"ds-real": {"name": "Real Stream", "dataset_id": "xyz"}}
    assert datastream_map.datastream_map_source() == "datastream_map.json"


def test_returns_empty_when_neither_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_SAMPLE_PATH", tmp_path / "also-missing.json")

    assert datastream_map.load_datastream_map() == {}
    assert datastream_map.datastream_map_source() == "(none found)"


def test_a_malformed_file_degrades_to_empty_instead_of_raising(tmp_path, monkeypatch):
    real = tmp_path / "datastream_map.json"
    real.write_text("not valid json{{{")
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_PATH", real)
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_SAMPLE_PATH", tmp_path / "missing.json")

    assert datastream_map.load_datastream_map() == {}


def test_a_non_object_json_file_degrades_to_empty(tmp_path, monkeypatch):
    real = tmp_path / "datastream_map.json"
    real.write_text(json.dumps(["not", "an", "object"]))
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_PATH", real)
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_SAMPLE_PATH", tmp_path / "missing.json")

    assert datastream_map.load_datastream_map() == {}


def test_ignores_entries_that_are_not_objects(tmp_path, monkeypatch):
    real = tmp_path / "datastream_map.json"
    real.write_text(json.dumps({"ds-1": {"name": "Good", "dataset_id": "abc"}, "ds-2": "not-an-object"}))
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_PATH", real)
    monkeypatch.setattr(datastream_map, "DATASTREAM_MAP_SAMPLE_PATH", tmp_path / "missing.json")

    result = datastream_map.load_datastream_map()

    assert result == {"ds-1": {"name": "Good", "dataset_id": "abc"}}
