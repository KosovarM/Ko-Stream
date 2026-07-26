from unittest.mock import patch

from kostream.catalog import CatalogEntry, CatalogState, load_catalog, save_catalog
from kostream.mal import MalAnimeEntry, sync_animelist_to_catalog


def test_sync_animelist_replaces_mal_entries(tmp_path):
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(id="local-1", enabled=True, source="local", folder="Anime"),
                CatalogEntry(
                    id="mal-21",
                    enabled=False,
                    source="mal",
                    folder="One Piece Local",
                    anilist_id=21,
                    mal_id=21,
                    title="Old MAL",
                    added_at="2026-01-15T10:00:00Z",
                ),
                CatalogEntry(id="mal-99", enabled=True, source="mal", mal_id=99, title="Removed"),
            ]
        ),
        catalog_path,
    )

    fake_entries = [
        MalAnimeEntry(
            mal_id=21,
            title="One Piece",
            synopsis="Pirates.",
            poster_url="https://example.com/op.jpg",
            genres=["Action"],
            num_episodes=1000,
            list_status="watching",
            num_episodes_watched=500,
            anime_status="currently_airing",
            score=10,
            mean_score=8.7,
        )
    ]

    class FakeCfg:
        client_id = "x"
        client_secret = "y"
        redirect_uri = "http://127.0.0.1:5001/auth/mal/callback"

    with patch("kostream.mal.get_valid_access_token", return_value="token"):
        with patch("kostream.mal.fetch_animelist", return_value=fake_entries):
            count = sync_animelist_to_catalog(FakeCfg(), catalog_path)

    assert count == 1
    state = load_catalog(catalog_path)
    ids = {s.id for s in state.shows}
    assert "local-1" in ids
    assert "mal-21" in ids
    assert "mal-99" not in ids
    mal21 = state.get("mal-21")
    assert mal21 is not None
    assert mal21.added_at == "2026-01-15T10:00:00Z"
    assert mal21.folder == "One Piece Local"
    assert mal21.anilist_id == 21
    assert mal21.enabled is False
    assert mal21.title == "One Piece"


def test_load_cached_anime(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "21.json").write_text(
        '{"mal_id":21,"title":"One Piece","synopsis":"Pirates","poster_url":"https://x/y.jpg","genres":["Action"],"num_episodes":10,"list_status":"watching","num_episodes_watched":3,"anime_status":"currently_airing","score":9,"mean_score":8.5}',
        encoding="utf-8",
    )
    item = mal_mod.load_cached_anime(21)
    assert item is not None
    assert item.title == "One Piece"
    assert item.num_episodes_watched == 3
    assert item.anime_status == "currently_airing"
