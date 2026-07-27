"""Accounts migration: progress move + MAL list-state split."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kostream.migrate_accounts import MigrateError, migrate_accounts
from kostream.users import bootstrap_master


def _setup_legacy(tmp_path: Path) -> tuple[Path, Path, Path]:
    data = tmp_path / "data"
    data.mkdir()
    users = data / "users.json"
    bootstrap_master(users, "master", "secret")

    (data / "completed.json").write_text('{"mal-21": 5}', encoding="utf-8")
    (data / "progress.json").write_text('{"ep-1": 12.5}', encoding="utf-8")
    (data / "manga_completed.json").write_text('{"mal-manga-2": 3}', encoding="utf-8")
    (data / "manga_page_progress.json").write_text("{}", encoding="utf-8")

    mal = data / "mal"
    cache = mal / "cache"
    manga_cache = mal / "manga_cache"
    cache.mkdir(parents=True)
    manga_cache.mkdir(parents=True)
    (mal / "tokens.json").write_text(
        json.dumps(
            {
                "access_token": "a",
                "refresh_token": "r",
                "expires_at": 9999999999,
                "username": "maluser",
            }
        ),
        encoding="utf-8",
    )
    (mal / "last_sync.json").write_text(
        json.dumps({"synced_at": "2026-01-01T00:00:00Z", "count": 1}),
        encoding="utf-8",
    )
    (cache / "21.json").write_text(
        json.dumps(
            {
                "mal_id": 21,
                "title": "One Piece",
                "synopsis": "Pirates",
                "num_episodes": 1000,
                "list_status": "watching",
                "num_episodes_watched": 500,
                "score": 10,
                "anime_status": "currently_airing",
                "mean_score": 8.7,
            }
        ),
        encoding="utf-8",
    )
    (manga_cache / "2.json").write_text(
        json.dumps(
            {
                "mal_id": 2,
                "title": "Berserk",
                "num_chapters": 364,
                "list_status": "reading",
                "num_chapters_read": 10,
                "num_volumes_read": 1,
                "score": 10,
            }
        ),
        encoding="utf-8",
    )
    return data, users, mal


def test_migrate_moves_files_and_extracts_list_state(tmp_path):
    data, users, mal = _setup_legacy(tmp_path)
    summary = migrate_accounts(data_dir=data, users_path=users)

    assert summary["ok"] is True
    assert summary["already_migrated"] is False
    assert summary["master_id"] == "u_master"
    assert "completed.json" in summary["moved_progress"]
    assert "tokens.json" in summary["moved_mal"]
    assert summary["anime_list_extracted"] == 1
    assert summary["manga_list_extracted"] == 1

    master_dir = data / "users" / "u_master"
    assert (master_dir / "completed.json").is_file()
    assert not (data / "completed.json").exists()
    assert (mal / "users" / "u_master" / "tokens.json").is_file()
    assert not (mal / "tokens.json").exists()

    anime_state = json.loads(
        (mal / "users" / "u_master" / "anime_list_state.json").read_text(encoding="utf-8")
    )
    assert anime_state["21"]["num_episodes_watched"] == 500
    assert anime_state["21"]["list_status"] == "watching"
    assert anime_state["21"]["score"] == 10

    cache_raw = json.loads((mal / "cache" / "21.json").read_text(encoding="utf-8"))
    assert "list_status" not in cache_raw
    assert "num_episodes_watched" not in cache_raw
    assert "score" not in cache_raw
    assert cache_raw["title"] == "One Piece"

    manga_state = json.loads(
        (mal / "users" / "u_master" / "manga_list_state.json").read_text(encoding="utf-8")
    )
    assert manga_state["2"]["num_chapters_read"] == 10
    manga_raw = json.loads((mal / "manga_cache" / "2.json").read_text(encoding="utf-8"))
    assert "num_chapters_read" not in manga_raw

    assert (data / ".accounts_migrated").is_file()


def test_migrate_idempotent(tmp_path):
    data, users, _mal = _setup_legacy(tmp_path)
    first = migrate_accounts(data_dir=data, users_path=users)
    second = migrate_accounts(data_dir=data, users_path=users)
    assert first["already_migrated"] is False
    assert second["already_migrated"] is True
    assert "already migrated" in second["message"].casefold()


def test_migrate_requires_bootstrap(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with pytest.raises(MigrateError, match="Bootstrap"):
        migrate_accounts(data_dir=data, users_path=data / "users.json")
