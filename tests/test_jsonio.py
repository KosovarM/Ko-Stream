"""Tests for atomic JSON writes."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kostream.jsonio import atomic_write_json


def test_atomic_write_json_creates_file(tmp_path: Path):
    path = tmp_path / "state.json"
    atomic_write_json(path, {"ok": True, "n": 1})
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True, "n": 1}
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_atomic_write_json_replaces_existing(tmp_path: Path):
    path = tmp_path / "nested" / "data.json"
    atomic_write_json(path, {"v": 1})
    atomic_write_json(path, {"v": 2}, ensure_ascii=False)
    assert json.loads(path.read_text(encoding="utf-8"))["v"] == 2


def test_atomic_write_json_concurrent_last_writer_wins(tmp_path: Path):
    path = tmp_path / "counter.json"

    def write_one(i: int) -> None:
        atomic_write_json(path, {"i": i})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write_one, range(40)))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "i" in data
    assert isinstance(data["i"], int)
    assert 0 <= data["i"] < 40
    # File must remain valid JSON after concurrent writers.
    assert path.read_text(encoding="utf-8").strip().startswith("{")
