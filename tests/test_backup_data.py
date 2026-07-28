"""Tests for scripts/backup_data.py."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path


def _load_backup_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "backup_data.py"
    spec = importlib.util.spec_from_file_location("backup_data", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backup_data_skips_cache_by_default(tmp_path: Path):
    build_zip = _load_backup_module().build_zip
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "users.json").write_text("{}", encoding="utf-8")
    (data / "cache" / "x.json").parent.mkdir(parents=True)
    (data / "cache" / "x.json").write_text("{}", encoding="utf-8")
    (data / "mal" / "cache" / "1.json").parent.mkdir(parents=True)
    (data / "mal" / "cache" / "1.json").write_text("{}", encoding="utf-8")
    (data / "mal" / "users" / "u1" / "tokens.json").parent.mkdir(parents=True)
    (data / "mal" / "users" / "u1" / "tokens.json").write_text("{}", encoding="utf-8")

    out = tmp_path / "out.zip"
    path, count = build_zip(data, out, include_cache=False)
    assert path.exists()
    assert count == 2
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
    assert "data/users.json" in names
    assert "data/mal/users/u1/tokens.json" in names
    assert "data/cache/x.json" not in names
    assert "data/mal/cache/1.json" not in names
