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
    assert show.mal_id == 21
    assert show.episodes_watched == 12
    assert show.anime_status == "currently_airing"
    assert show.list_status == "watching"
    assert show.user_score == 10
    assert len(show.episodes) == 100
    assert show.poster_url in {
        "https://example.com/op.jpg",
        "/media/thumbnail/anime/21",
    }
    assert not show.description.startswith("MAL +")
    assert "Grand Line adventure" in show.description


def test_description_omits_mal_plus_local_prefix(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from kostream.catalog import CatalogEntry, CatalogState, save_catalog
    from kostream.library import get_show

    cache_dir = tmp_path / "mal-cache"
    cache_dir.mkdir()
    monkeypatch.setattr(mal_mod, "CACHE_DIR", cache_dir)
    (cache_dir / "7.json").write_text(
        '{"mal_id":7,"title":"Local Mix","synopsis":"Real synopsis here.",'
        '"poster_url":null,"genres":["Action"],"num_episodes":3,'
        '"anime_status":"finished_airing","mean_score":7.5}',
        encoding="utf-8",
    )
    media = tmp_path / "shows" / "Local Mix"
    media.mkdir(parents=True)
    (media / "Episode 1.mp4").write_bytes(b"x")
    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-7",
                    enabled=True,
                    source="mal",
                    folder="Local Mix",
                    mal_id=7,
                    title="Local Mix",
                )
            ]
        ),
        catalog,
    )
    show = get_show("mal-7", tmp_path / "shows", catalog)
    assert show is not None
    assert not show.description.startswith("MAL +")
    assert "Real synopsis here" in show.description
