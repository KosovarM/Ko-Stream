"""MAL shared cache vs per-user list-state overlay."""

from __future__ import annotations

import json

from kostream.mal import (
    MalAnimeEntry,
    MalMangaEntry,
    apply_list_row_to_anime,
    load_anime_list_state,
    load_cached_anime,
    load_cached_anime_for_user,
    load_cached_manga,
    load_cached_manga_for_user,
    write_anime_list_state_from_entries,
    write_cached_anime,
    write_cached_manga,
    write_manga_list_state_from_entries,
)
from kostream.models import Show
from kostream.watch_progress import apply_mal_metadata


def test_write_cached_anime_strips_list_fields(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    write_cached_anime(
        MalAnimeEntry(
            mal_id=21,
            title="One Piece",
            synopsis="Pirates",
            poster_url=None,
            genres=["Action"],
            num_episodes=1000,
            list_status="watching",
            num_episodes_watched=500,
            anime_status="currently_airing",
            score=10,
            mean_score=8.7,
        )
    )
    raw = json.loads((tmp_path / "21.json").read_text(encoding="utf-8"))
    assert "list_status" not in raw
    assert "num_episodes_watched" not in raw
    assert "score" not in raw
    assert raw["title"] == "One Piece"
    assert raw["num_episodes"] == 1000

    loaded = load_cached_anime(21)
    assert loaded is not None
    assert loaded.num_episodes_watched == 0
    assert loaded.list_status == "plan_to_watch"
    assert loaded.score == 0


def test_list_state_round_trip_and_merge(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path / "mal")
    write_cached_anime(
        MalAnimeEntry(
            mal_id=21,
            title="One Piece",
            synopsis="",
            poster_url=None,
            genres=[],
            num_episodes=10,
            list_status="watching",
            num_episodes_watched=3,
            anime_status="currently_airing",
            score=9,
            mean_score=8.5,
        )
    )
    write_anime_list_state_from_entries(
        "u_master",
        [
            MalAnimeEntry(
                mal_id=21,
                title="One Piece",
                synopsis="",
                poster_url=None,
                genres=[],
                num_episodes=10,
                list_status="watching",
                num_episodes_watched=3,
                anime_status="currently_airing",
                score=9,
                mean_score=8.5,
            )
        ],
    )
    state = load_anime_list_state("u_master")
    assert state["21"]["num_episodes_watched"] == 3
    assert state["21"]["score"] == 9

    merged = load_cached_anime_for_user(21, "u_master")
    assert merged is not None
    assert merged.title == "One Piece"
    assert merged.num_episodes_watched == 3
    assert merged.list_status == "watching"
    assert merged.score == 9

    other = load_cached_anime_for_user(21, "u_other")
    assert other is not None
    assert other.num_episodes_watched == 0


def test_apply_mal_metadata_uses_overlay(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    write_cached_anime(
        MalAnimeEntry(
            mal_id=1,
            title="Test",
            synopsis="",
            poster_url=None,
            genres=[],
            num_episodes=12,
            list_status="watching",
            num_episodes_watched=99,
            anime_status="finished_airing",
            score=1,
            mean_score=7.0,
        )
    )
    cached = load_cached_anime(1)
    assert cached is not None
    assert cached.num_episodes_watched == 0

    show = Show(id="s", title="T", description="", episodes_watched=2, episodes=[])
    list_row = {"list_status": "completed", "num_episodes_watched": 12, "score": 8}
    apply_mal_metadata(show, cached, list_row)
    assert show.episodes_watched == 12
    assert show.list_status == "completed"
    assert show.user_score == 8
    assert show.mean_score == 7.0


def test_apply_mal_metadata_without_list_row_is_not_watched(tmp_path, monkeypatch):
    """Catalog/local titles not on the user's MAL list must not show Plan to Watch."""
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    write_cached_anime(
        MalAnimeEntry(
            mal_id=99,
            title="Site Only",
            synopsis="",
            poster_url=None,
            genres=[],
            num_episodes=12,
            list_status="plan_to_watch",
            num_episodes_watched=0,
            anime_status="finished_airing",
            score=0,
            mean_score=7.0,
        )
    )
    cached = load_cached_anime(99)
    assert cached is not None
    assert cached.list_status == "plan_to_watch"

    show = Show(id="mal-99", title="Site Only", description="", episodes=[])
    apply_mal_metadata(show, cached, list_row=None)
    assert show.list_status is None
    assert show.episodes_watched == 0
    assert show.user_score is None

    for_user = load_cached_anime_for_user(99, "u_nobody")
    assert for_user is not None
    assert for_user.list_status == ""
    assert for_user.num_episodes_watched == 0


def test_manga_cache_strips_list_fields(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "MANGA_CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path / "mal")
    entry = MalMangaEntry(
        mal_id=2,
        title="Berserk",
        synopsis="",
        poster_url=None,
        genres=[],
        num_volumes=40,
        num_chapters=364,
        list_status="reading",
        num_volumes_read=1,
        num_chapters_read=10,
        manga_status="currently_publishing",
        score=10,
        mean_score=9.4,
    )
    write_cached_manga(entry)
    write_manga_list_state_from_entries("u_master", [entry])
    raw = json.loads((tmp_path / "2.json").read_text(encoding="utf-8"))
    assert "list_status" not in raw
    assert "num_chapters_read" not in raw
    meta = load_cached_manga(2)
    assert meta is not None
    assert meta.num_chapters_read == 0
    merged = load_cached_manga_for_user(2, "u_master")
    assert merged is not None
    assert merged.num_chapters_read == 10
    assert merged.list_status == "reading"


def test_apply_list_row_helper():
    entry = MalAnimeEntry(
        mal_id=1,
        title="T",
        synopsis="",
        poster_url=None,
        genres=[],
        num_episodes=1,
        list_status="plan_to_watch",
        num_episodes_watched=0,
        anime_status=None,
        score=0,
        mean_score=None,
    )
    apply_list_row_to_anime(
        entry, {"list_status": "watching", "num_episodes_watched": 4, "score": 7}
    )
    assert entry.list_status == "watching"
    assert entry.num_episodes_watched == 4
    assert entry.score == 7
