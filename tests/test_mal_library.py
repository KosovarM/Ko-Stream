from kostream.catalog import CatalogEntry
from kostream.library import scan_library
from kostream.mal import MalAnimeEntry


def test_mal_catalog_entry_uses_cache(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    cache_dir = tmp_path / "mal-cache"
    cache_dir.mkdir()
    monkeypatch.setattr(mal_mod, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path / "mal")
    (cache_dir / "21.json").write_text(
        '{"mal_id":21,"title":"One Piece","synopsis":"Grand Line adventure.","poster_url":"https://example.com/op.jpg","genres":["Action"],"num_episodes":100,"anime_status":"currently_airing","mean_score":8.5}',
        encoding="utf-8",
    )
    mal_mod.write_anime_list_state_from_entries(
        "u_test",
        [
            MalAnimeEntry(
                mal_id=21,
                title="One Piece",
                synopsis="",
                poster_url=None,
                genres=[],
                num_episodes=100,
                list_status="watching",
                num_episodes_watched=12,
                anime_status="currently_airing",
                score=10,
                mean_score=8.5,
            )
        ],
    )

    catalog_path = tmp_path / "selected.json"
    catalog_path.write_text(
        '{"shows":[{"id":"mal-21","enabled":true,"source":"mal","mal_id":21,"title":"One Piece"}]}',
        encoding="utf-8",
    )

    shows = scan_library(tmp_path / "shows", catalog_path, user_id="u_test")
    assert len(shows) == 1
    show = shows[0]
    assert show.title == "One Piece"
    assert show.poster_url == "https://example.com/op.jpg"
    assert show.mal_id == 21
    assert show.episodes_watched == 12
    assert show.anime_status == "currently_airing"
    assert show.list_status == "watching"
    assert show.user_score == 10
    assert len(show.episodes) == 100
