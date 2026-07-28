from pathlib import Path
from unittest.mock import patch

from kostream.anilist import AniListMedia
from kostream.catalog import CatalogEntry, CatalogState, load_catalog, save_catalog
from kostream.media_import import (
    import_media_to_catalog,
    list_folders_with_videos,
    preview_media_import,
    summarize_import,
)
from kostream.app import create_app

from conftest import bootstrap_test_users, login_client


def _media_tree(tmp_path: Path) -> Path:
    root = tmp_path / "anime"
    (root / "Akame ga Kill!").mkdir(parents=True)
    (root / "Akame ga Kill!" / "S01E01.mp4").write_bytes(b"video")
    (root / "Mystery Show").mkdir()
    (root / "Mystery Show" / "S01E01.mp4").write_bytes(b"video")
    (root / "Empty Folder").mkdir()
    return root


def test_list_folders_with_videos_skips_empty(tmp_path: Path):
    root = _media_tree(tmp_path)
    names = list_folders_with_videos(root)
    assert names == ["Akame ga Kill!", "Mystery Show"]


def test_import_links_folder_map_mal_id(tmp_path: Path):
    root = _media_tree(tmp_path)
    catalog_path = tmp_path / "selected.json"
    save_catalog(CatalogState(shows=[]), catalog_path)

    with patch(
        "kostream.media_import._load_folder_mal_map",
        return_value={"Akame ga Kill!": 22199},
    ):
        with patch("kostream.media_import.ensure_episode_titles_async"):
            result = import_media_to_catalog(
                media_root=root,
                catalog_path=catalog_path,
                sync_mal=False,
            )

    assert any(row["mal_id"] == 22199 for row in result.added)
    state = load_catalog(catalog_path)
    entry = state.get("mal-22199")
    assert entry is not None
    assert entry.folder == "Akame ga Kill!"
    assert entry.source == "mal"


def test_import_links_existing_catalog_entry_without_folder(tmp_path: Path):
    root = _media_tree(tmp_path)
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-22199",
                    enabled=True,
                    source="mal",
                    mal_id=22199,
                    title="Akame ga Kill!",
                )
            ]
        ),
        catalog_path,
    )

    with patch(
        "kostream.media_import._load_folder_mal_map",
        return_value={"Akame ga Kill!": 22199},
    ):
        with patch("kostream.media_import.ensure_episode_titles_async"):
            result = import_media_to_catalog(
                media_root=root,
                catalog_path=catalog_path,
                sync_mal=False,
            )

    assert len(result.linked) == 1
    assert result.linked[0]["folder"] == "Akame ga Kill!"
    state = load_catalog(catalog_path)
    assert state.get("mal-22199").folder == "Akame ga Kill!"


def test_import_skips_already_linked_folder(tmp_path: Path):
    root = _media_tree(tmp_path)
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-22199",
                    enabled=True,
                    source="mal",
                    folder="Akame ga Kill!",
                    mal_id=22199,
                    title="Akame ga Kill!",
                )
            ]
        ),
        catalog_path,
    )

    with patch("kostream.media_import._load_folder_mal_map", return_value={}):
        result = import_media_to_catalog(
            media_root=root,
            catalog_path=catalog_path,
            sync_mal=False,
        )

    assert any(row["folder"] == "Akame ga Kill!" for row in result.skipped)


def test_import_upgrades_local_folder_with_folder_map_mal_id(tmp_path: Path):
    root = tmp_path / "anime"
    (root / "Overlord Movie 1 The Undead King").mkdir(parents=True)
    (root / "Overlord Movie 1 The Undead King" / "S01E01.mp4").write_bytes(b"video")
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="overlord-movie-1-the-undead-king",
                    enabled=True,
                    source="local",
                    folder="Overlord Movie 1 The Undead King",
                    title="Overlord Movie 1 The Undead King",
                )
            ]
        ),
        catalog_path,
    )

    with patch(
        "kostream.media_import._load_folder_mal_map",
        return_value={"Overlord Movie 1 The Undead King": 34161},
    ):
        with patch("kostream.media_import.ensure_episode_titles_async"):
            result = import_media_to_catalog(
                media_root=root,
                catalog_path=catalog_path,
                sync_mal=False,
            )

    state = load_catalog(catalog_path)
    assert state.get("overlord-movie-1-the-undead-king") is None
    entry = state.get("mal-34161")
    assert entry is not None
    assert entry.folder == "Overlord Movie 1 The Undead King"
    assert entry.mal_id == 34161
    assert entry.source == "mal"
    assert len(result.skipped) == 1


def test_import_links_jojo_english_folder_to_japanese_mal_entry(tmp_path: Path):
    root = tmp_path / "anime"
    (root / "JoJos Bizarre Adventure Golden Wind").mkdir(parents=True)
    (root / "JoJos Bizarre Adventure Golden Wind" / "S01E01.mp4").write_bytes(b"video")
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="jojos-bizarre-adventure-golden-wind",
                    enabled=True,
                    source="local",
                    folder="JoJos Bizarre Adventure Golden Wind",
                    title="JoJos Bizarre Adventure Golden Wind",
                ),
                CatalogEntry(
                    id="mal-37991",
                    enabled=True,
                    source="mal",
                    mal_id=37991,
                    title="JoJo no Kimyou na Bouken Part 5: Ougon no Kaze",
                ),
            ]
        ),
        catalog_path,
    )

    with patch("kostream.media_import.ensure_episode_titles_async"):
        import_media_to_catalog(
            media_root=root,
            catalog_path=catalog_path,
            sync_mal=False,
        )

    state = load_catalog(catalog_path)
    assert state.get("jojos-bizarre-adventure-golden-wind") is None
    entry = state.get("mal-37991")
    assert entry is not None
    assert entry.folder == "JoJos Bizarre Adventure Golden Wind"
    assert entry.mal_id == 37991


def test_resolve_mal_from_search_normalizes_jojos_apostrophe():
    from kostream.media_import import _resolve_mal_from_search

    with patch("kostream.media_import.search_anime") as mock_search:
        from kostream.anilist import AniListMedia

        mock_search.return_value = [
            AniListMedia(
                anilist_id=1,
                title="JoJo's Bizarre Adventure: Golden Wind",
                description="",
                genres=[],
                poster_url=None,
                banner_url=None,
                mal_id=37991,
            )
        ]
        mal_id, title = _resolve_mal_from_search("JoJos Bizarre Adventure Golden Wind")
    assert mal_id == 37991
    assert "Golden Wind" in (title or "")
    assert "JoJo" in mock_search.call_args[0][0]


def test_folder_mal_id_from_title_aliases():
    from kostream.media_title_aliases import folder_mal_id

    assert folder_mal_id("JoJos Bizarre Adventure Stone Ocean Part 3") == 53273
    assert folder_mal_id("JoJos Bizarre Adventure Golden Wind") == 37991


def test_import_links_local_folder_to_existing_mal_entry(tmp_path: Path):
    root = tmp_path / "anime"
    (root / "Kabaneri of the Iron Fortress").mkdir(parents=True)
    (root / "Kabaneri of the Iron Fortress" / "S01E01.mp4").write_bytes(b"video")
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="kabaneri-of-the-iron-fortress",
                    enabled=True,
                    source="local",
                    folder="Kabaneri of the Iron Fortress",
                    title="Kabaneri of the Iron Fortress",
                ),
                CatalogEntry(
                    id="mal-28623",
                    enabled=True,
                    source="mal",
                    mal_id=28623,
                    title="Koutetsujou no Kabaneri",
                ),
            ]
        ),
        catalog_path,
    )

    with patch(
        "kostream.media_import._load_folder_mal_map",
        return_value={"Kabaneri of the Iron Fortress": 28623},
    ):
        with patch("kostream.media_import.ensure_episode_titles_async"):
            result = import_media_to_catalog(
                media_root=root,
                catalog_path=catalog_path,
                sync_mal=False,
            )

    state = load_catalog(catalog_path)
    assert state.get("kabaneri-of-the-iron-fortress") is None
    entry = state.get("mal-28623")
    assert entry.folder == "Kabaneri of the Iron Fortress"
    assert len(result.skipped) == 1


def test_import_anilist_search_for_unknown_folder(tmp_path: Path):
    root = _media_tree(tmp_path)
    catalog_path = tmp_path / "selected.json"
    save_catalog(CatalogState(shows=[]), catalog_path)

    fake = AniListMedia(
        anilist_id=1,
        title="Mystery Show",
        description="",
        genres=[],
        poster_url=None,
        banner_url=None,
        mal_id=999,
    )

    with patch("kostream.media_import._load_folder_mal_map", return_value={}):
        with patch("kostream.media_import.search_anime", return_value=[fake]):
            with patch("kostream.media_import.ensure_episode_titles_async"):
                result = import_media_to_catalog(
                    media_root=root,
                    catalog_path=catalog_path,
                    sync_mal=False,
                )

    assert any(row.get("mal_id") == 999 for row in result.added)
    assert load_catalog(catalog_path).get("mal-999") is not None


def test_preview_lists_pending_only(tmp_path: Path):
    root = _media_tree(tmp_path)
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-22199",
                    enabled=True,
                    source="mal",
                    folder="Akame ga Kill!",
                    mal_id=22199,
                    title="Akame ga Kill!",
                )
            ]
        ),
        catalog_path,
    )

    with patch("kostream.media_import._load_folder_mal_map", return_value={}):
        rows = preview_media_import(media_root=root, catalog_path=catalog_path)

    folders = {row["folder"] for row in rows}
    assert "Akame ga Kill!" not in folders
    assert "Mystery Show" in folders


def test_summarize_import_message():
    from kostream.media_import import MediaImportResult

    msg = summarize_import(
        MediaImportResult(added=[{"folder": "A"}], mal_synced=[{"folder": "A"}])
    )
    assert "added" in msg
    assert "Plan to Watch" in msg


def _test_app(tmp_path: Path):
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    return create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )


def test_catalog_add_new_stays_on_catalog_json(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.post(
        "/api/catalog/add",
        json={
            "source": "anilist",
            "id": "anilist-1",
            "anilist_id": 1,
            "title": "Test Anime",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["existing"] is False
    assert "redirect" not in data
    assert data["id"] == "anilist-1"


def test_catalog_add_existing_redirects(tmp_path: Path):
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-42",
                    enabled=True,
                    source="mal",
                    mal_id=42,
                    title="Existing",
                )
            ]
        ),
        catalog_path,
    )
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    app = create_app(
        media_root=media,
        catalog_path=catalog_path,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)
    resp = client.post(
        "/api/catalog/add",
        json={"source": "mal", "id": "mal-42", "mal_id": 42, "title": "Existing"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["existing"] is True
    assert data["redirect"].endswith("/show/mal-42")
