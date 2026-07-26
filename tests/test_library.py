from pathlib import Path

from kostream.catalog import CatalogEntry, CatalogState, save_catalog
from kostream.library import (
    _infer_display_season,
    _merge_mal_and_local_episodes,
    _parse_episode_numbers,
    get_show,
    scan_library,
)
from kostream.mal import MalAnimeEntry
from kostream.models import Episode, is_local_file_episode, is_stream_only_episode, slugify


def test_slugify():
    assert slugify("One Piece") == "one-piece"


def test_scan_empty_uses_demo(tmp_path: Path):
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    shows = scan_library(tmp_path, catalog)
    assert len(shows) >= 1


def test_parse_episode_numbers_variants():
    assert _parse_episode_numbers("S01E01.mp4") == (1, 1)
    assert _parse_episode_numbers("S04E02.mp4") == (4, 2)
    assert _parse_episode_numbers("1x03.mkv") == (1, 3)
    assert _parse_episode_numbers("Episode 2.mp4") == (1, 2)
    assert _parse_episode_numbers("Episode2.mp4") == (1, 2)
    assert _parse_episode_numbers("Ep 12.webm") == (1, 12)
    assert _parse_episode_numbers("Ep.7.mp4") == (1, 7)


def test_infer_display_season_from_folder_and_files():
    local = [Episode("a", "a", 4, 1, "Episode 1", "S04E01.mp4")]
    assert _infer_display_season("Re Zero Season 4", None, local) == 4
    assert _infer_display_season(None, "Something 4th Season", []) == 4
    assert _infer_display_season(None, None, local) == 4


def test_merge_mal_and_local_overlays_by_number_not_filename_season():
    local = [
        Episode("x-s04e01", "x", 4, 1, "S04E01", "S04E01.mp4"),
        Episode("x-s01e02", "x", 1, 2, "Episode 2", "Episode 2.mp4"),
    ]
    merged = _merge_mal_and_local_episodes(
        "mal-1", mal_count=5, local=local, display_season=4
    )
    assert len(merged) == 5
    assert all(ep.season == 4 for ep in merged)
    assert merged[0].filename == "S04E01.mp4"
    assert merged[0].title == "Episode 1"
    assert merged[0].id == "mal-1-s04e01"
    assert is_local_file_episode(merged[0])
    assert merged[1].filename == "Episode 2.mp4"
    assert merged[1].title == "Episode 2"
    assert is_local_file_episode(merged[1])
    assert merged[2].filename == "demo.mp4"
    assert merged[2].title == "Episode 3"
    assert is_stream_only_episode(merged[2])


def test_mal_show_keeps_full_list_with_local_files(tmp_path: Path, monkeypatch):
    from kostream import library as lib

    media = tmp_path / "shows"
    folder = media / "Re Zero Season 4"
    folder.mkdir(parents=True)
    (folder / "S04E01.mp4").write_bytes(b"video")
    (folder / "Episode 2.mp4").write_bytes(b"video")

    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-61316",
                    enabled=True,
                    source="mal",
                    folder="Re Zero Season 4",
                    mal_id=61316,
                    title="Re:Zero S4",
                )
            ]
        ),
        catalog,
    )

    cached = MalAnimeEntry(
        mal_id=61316,
        title="Re:Zero kara Hajimeru Isekai Seikatsu 4th Season",
        synopsis="Test",
        poster_url=None,
        genres=["Drama"],
        num_episodes=12,
        list_status="watching",
        num_episodes_watched=0,
        anime_status="currently_airing",
        score=0,
        mean_score=8.0,
    )
    monkeypatch.setattr(
        lib, "load_cached_anime", lambda mal_id: cached if mal_id == 61316 else None
    )

    show = get_show("mal-61316", media, catalog)
    assert show is not None
    assert len(show.episodes) == 12
    assert show.episodes[0].season == 4
    assert show.episodes[0].filename == "S04E01.mp4"
    assert show.episodes[0].title == "Episode 1"
    assert show.episodes[1].filename == "Episode 2.mp4"
    assert show.episodes[1].title == "Episode 2"
    assert show.episodes[2].filename == "demo.mp4"
    assert show.episodes[2].title == "Episode 3"
    assert show.episodes[2].season == 4
    assert show.is_metadata_only is False
