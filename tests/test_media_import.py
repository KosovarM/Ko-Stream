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
        MediaImportResult(added=[{"folder": "A"}], linked=[{"folder": "B"}])
    )
    assert "added" in msg
    assert "linked" in msg
    assert "Import done" in msg
    assert "Plan to Watch" not in msg


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


def test_import_media_api_allows_manager_rejects_user(tmp_path: Path):
    from conftest import add_test_user

    catalog_path = tmp_path / "selected.json"
    save_catalog(CatalogState(shows=[]), catalog_path)
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    add_test_user(users, "manager1", "mgrpass", role="manager")
    add_test_user(users, "sister", "sispass", role="user")
    app = create_app(
        media_root=media,
        catalog_path=catalog_path,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()

    login_client(client, "sister", "sispass")
    denied = client.get("/api/catalog/import-media/preview")
    assert denied.status_code == 403
    client.post("/logout")

    login_client(client, "manager1", "mgrpass")
    ok = client.get("/api/catalog/import-media/preview")
    assert ok.status_code == 200
    body = ok.get_json()
    assert body["ok"] is True
    assert "count" in body

    page = client.get("/catalog")
    assert page.status_code == 200
    assert b"can_import_media" not in page.data  # template var, not HTML
    assert b'id="catalog-import-media"' in page.data
    assert b'id="catalog-resync-folders"' in page.data
    assert b"Admin or Manager account required" not in page.data


def test_folder_plausibly_matches_title():
    from kostream.media_title_aliases import folder_plausibly_matches_title

    assert folder_plausibly_matches_title(
        "Fate strange Fake", "Fate/strange Fake", mal_id=55830
    )
    assert not folder_plausibly_matches_title(
        "Fate strange Fake",
        "Fate/kaleid liner Prisma Illya",
        mal_id=14829,
    )
    assert not folder_plausibly_matches_title(
        "Fate kaleid liner Prisma Illya Vow in the Snow",
        "Fate/strange Fake",
        mal_id=55830,
    )
    assert folder_plausibly_matches_title(
        "Fate kaleid liner Prisma Illya Vow in the Snow",
        "Fate/kaleid liner Prisma Illya Movie: Sekka no Chikai",
        mal_id=34100,
    )
    assert not folder_plausibly_matches_title(
        "Fate kaleid liner Prisma Illya Vow in the Snow",
        "Fate/kaleid liner Prisma Illya",
        mal_id=14829,
    )
    assert not folder_plausibly_matches_title(
        "Gintama 3-Z Ginpachi-sensei",
        "Kun Tun Tianxia Zhi Zhang Men Guilai",
    )
    assert not folder_plausibly_matches_title(
        "Jujutsu Kaisen 0 Movie",
        "Fate/kaleid liner Prisma Illya Movie: Sekka no Chikai",
    )
    assert folder_plausibly_matches_title(
        "Jujutsu Kaisen 0 Movie",
        "Jujutsu Kaisen 0 Movie",
    )
    assert folder_plausibly_matches_title(
        "KonoSuba Season 1",
        "Kono Subarashii Sekai ni Shukufuku wo!",
        mal_id=30831,
    )
    assert folder_plausibly_matches_title(
        "Demon Slayer Swordsmith Village Arc",
        "Kimetsu no Yaiba: Katanakaji no Sato-hen",
        mal_id=51019,
    )


def test_match_score_does_not_treat_single_token_as_perfect():
    from kostream.media_title_aliases import entry_match_keys, folder_match_keys, match_score

    score = match_score(
        folder_match_keys("Fate strange Fake"),
        entry_match_keys("Fate/kaleid liner Prisma Illya", mal_id=14829),
    )
    assert score < 0.5


def test_resync_clears_crosswired_and_relinks(tmp_path: Path):
    from kostream.media_import import resync_catalog_folders

    root = tmp_path / "anime"
    (root / "Gintama 3-Z Ginpachi-sensei").mkdir(parents=True)
    (root / "Gintama 3-Z Ginpachi-sensei" / "S01E01.mp4").write_bytes(b"v")
    (root / "Jujutsu Kaisen 0 Movie").mkdir()
    (root / "Jujutsu Kaisen 0 Movie" / "S01E01.mp4").write_bytes(b"v")
    (root / "Fate strange Fake").mkdir()
    (root / "Fate strange Fake" / "S01E01.mp4").write_bytes(b"v")

    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-60572",
                    enabled=True,
                    source="mal",
                    folder="Gintama 3-Z Ginpachi-sensei",
                    mal_id=60572,
                    title="Kun Tun Tianxia Zhi Zhang Men Guilai",
                ),
                CatalogEntry(
                    id="mal-48561",
                    enabled=True,
                    source="mal",
                    folder="Black Clover Sword of the Wizard King",
                    mal_id=48561,
                    title="Jujutsu Kaisen 0 Movie",
                ),
                CatalogEntry(
                    id="mal-34100",
                    enabled=True,
                    source="mal",
                    folder="Jujutsu Kaisen 0 Movie",
                    mal_id=34100,
                    title="Fate/kaleid liner Prisma Illya Movie: Sekka no Chikai",
                ),
                CatalogEntry(
                    id="mal-55830",
                    enabled=True,
                    source="mal",
                    folder="Fate strange Fake",
                    mal_id=55830,
                    title="Fate/strange Fake",
                ),
            ]
        ),
        catalog_path,
    )

    with patch("kostream.media_import._load_folder_mal_map", return_value={}):
        result = resync_catalog_folders(media_root=root, catalog_path=catalog_path)

    state = load_catalog(catalog_path)
    # Cross-wired Ginpachi folder cleared off Whale; no Ginpachi title on site.
    assert state.get("mal-60572").folder is None
    # JJK 0 folder moves to the JJK 0 catalog row.
    assert state.get("mal-48561").folder == "Jujutsu Kaisen 0 Movie"
    assert state.get("mal-34100").folder is None
    # Correct binding kept.
    assert state.get("mal-55830").folder == "Fate strange Fake"
    assert result.cleared >= 1
    assert result.refreshed + result.remapped >= 1


def test_resync_keeps_good_english_japanese_bindings(tmp_path: Path):
    from kostream.media_import import resync_catalog_folders

    root = tmp_path / "anime"
    for name in (
        "KonoSuba Season 1",
        "Your Name",
        "Fate strange Fake",
        "Fate kaleid liner Prisma Illya Vow in the Snow",
    ):
        (root / name).mkdir(parents=True)
        (root / name / "S01E01.mp4").write_bytes(b"v")

    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-30831",
                    enabled=True,
                    source="mal",
                    folder="KonoSuba Season 1",
                    mal_id=30831,
                    title="Kono Subarashii Sekai ni Shukufuku wo!",
                ),
                CatalogEntry(
                    id="mal-32281",
                    enabled=True,
                    source="mal",
                    folder="Your Name",
                    mal_id=32281,
                    title="Kimi no Na wa.",
                ),
                CatalogEntry(
                    id="mal-14829",
                    enabled=True,
                    source="mal",
                    folder="Fate kaleid liner Prisma Illya Vow in the Snow",
                    mal_id=14829,
                    title="Fate/kaleid liner Prisma Illya",
                ),
                CatalogEntry(
                    id="mal-34100",
                    enabled=True,
                    source="mal",
                    mal_id=34100,
                    title="Fate/kaleid liner Prisma Illya Movie: Sekka no Chikai",
                ),
                CatalogEntry(
                    id="mal-55830",
                    enabled=True,
                    source="mal",
                    folder="Fate strange Fake",
                    mal_id=55830,
                    title="Fate/strange Fake",
                ),
            ]
        ),
        catalog_path,
    )

    with patch("kostream.media_import._load_folder_mal_map", return_value={}):
        resync_catalog_folders(media_root=root, catalog_path=catalog_path)

    state = load_catalog(catalog_path)
    assert state.get("mal-30831").folder == "KonoSuba Season 1"
    assert state.get("mal-32281").folder == "Your Name"
    assert state.get("mal-55830").folder == "Fate strange Fake"
    # Vow in the Snow belongs to Sekka movie, not the TV series.
    assert state.get("mal-14829").folder is None
    assert state.get("mal-34100").folder == "Fate kaleid liner Prisma Illya Vow in the Snow"


def test_resync_does_not_crosswire_fate_siblings(tmp_path: Path):
    from kostream.media_import import resync_catalog_folders

    root = tmp_path / "anime"
    (root / "Fate strange Fake").mkdir(parents=True)
    (root / "Fate strange Fake" / "S01E01.mp4").write_bytes(b"v")
    (root / "Fate kaleid liner Prisma Illya Vow in the Snow").mkdir()
    (root / "Fate kaleid liner Prisma Illya Vow in the Snow" / "S01E01.mp4").write_bytes(
        b"v"
    )

    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-14829",
                    enabled=True,
                    source="mal",
                    folder="Fate strange Fake",
                    mal_id=14829,
                    title="Fate/kaleid liner Prisma Illya",
                ),
                CatalogEntry(
                    id="mal-55830",
                    enabled=True,
                    source="mal",
                    mal_id=55830,
                    title="Fate/strange Fake",
                ),
                CatalogEntry(
                    id="mal-34100",
                    enabled=True,
                    source="mal",
                    mal_id=34100,
                    title="Fate/kaleid liner Prisma Illya Movie: Sekka no Chikai",
                ),
            ]
        ),
        catalog_path,
    )

    with patch("kostream.media_import._load_folder_mal_map", return_value={}):
        resync_catalog_folders(media_root=root, catalog_path=catalog_path)

    state = load_catalog(catalog_path)
    assert state.get("mal-55830").folder == "Fate strange Fake"
    assert state.get("mal-14829").folder is None
    assert state.get("mal-34100").folder == (
        "Fate kaleid liner Prisma Illya Vow in the Snow"
    )


def test_resolve_mal_from_search_rejects_weak_first_hit():
    from kostream.media_import import _resolve_mal_from_search

    with patch("kostream.media_import.search_anime") as mock_search:
        mock_search.return_value = [
            AniListMedia(
                anilist_id=1,
                title="Completely Unrelated Whale Movie",
                description="",
                genres=[],
                poster_url=None,
                banner_url=None,
                mal_id=60572,
            )
        ]
        mal_id, title = _resolve_mal_from_search("Gintama 3-Z Ginpachi-sensei")
    assert mal_id is None
    assert title is None


def test_resync_folders_api_allows_manager(tmp_path: Path):
    from conftest import add_test_user

    catalog_path = tmp_path / "selected.json"
    save_catalog(CatalogState(shows=[]), catalog_path)
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    add_test_user(users, "manager1", "mgrpass", role="manager")
    add_test_user(users, "sister", "sispass", role="user")
    app = create_app(
        media_root=media,
        catalog_path=catalog_path,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()

    login_client(client, "sister", "sispass")
    denied = client.post("/api/catalog/resync-folders")
    assert denied.status_code == 403
    client.post("/logout")

    login_client(client, "manager1", "mgrpass")
    ok = client.post("/api/catalog/resync-folders")
    assert ok.status_code == 200
    body = ok.get_json()
    assert body["ok"] is True
    assert "message" in body
    assert "scanned_folders" in body


def _folder_bindings(catalog_path: Path) -> dict[str, str | None]:
    state = load_catalog(catalog_path)
    return {e.id: e.folder for e in state.shows}


def _disk_episode_sum(media_root: Path, catalog_path: Path) -> int:
    from kostream.library import count_unique_local_episodes

    state = load_catalog(catalog_path)
    total = 0
    for entry in state.shows:
        if not entry.folder:
            continue
        total += count_unique_local_episodes(media_root / entry.folder)
    return total


def test_import_does_not_push_plan_to_watch(tmp_path: Path):
    root = tmp_path / "anime"
    (root / "Akame ga Kill!").mkdir(parents=True)
    (root / "Akame ga Kill!" / "S01E01.mp4").write_bytes(b"v")
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
                user_id="u_master",
                mal_cfg=None,
                sync_mal=True,
            )

    assert result.mal_synced == []
    assert any(row["mal_id"] == 22199 for row in result.added)
    assert "Plan to Watch" not in summarize_import(result)
    # Import must not call into MAL list-status APIs anymore.
    import kostream.media_import as mi

    assert not hasattr(mi, "update_anime_list_status")


def test_resync_keeps_unique_soft_english_japanese_binding(tmp_path: Path, monkeypatch):
    """English folder + Japanese catalog title stays when MAL cache has matching title_en."""
    from kostream.media_import import resync_catalog_folders
    from kostream.mal import MalAnimeEntry, write_cached_anime
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path / "mal_cache")
    write_cached_anime(
        MalAnimeEntry(
            mal_id=99901,
            title="完全に別の日本語タイトル",
            synopsis="",
            poster_url=None,
            genres=[],
            num_episodes=2,
            list_status="plan_to_watch",
            num_episodes_watched=0,
            anime_status="finished_airing",
            score=0,
            mean_score=None,
            title_en="Obscure English Title",
        )
    )

    root = tmp_path / "anime"
    (root / "Obscure English Title").mkdir(parents=True)
    (root / "Obscure English Title" / "S01E01.mp4").write_bytes(b"v")
    (root / "Obscure English Title" / "S01E02.mp4").write_bytes(b"v")

    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-99901",
                    enabled=True,
                    source="mal",
                    folder="Obscure English Title",
                    mal_id=99901,
                    title="完全に別の日本語タイトル",
                )
            ]
        ),
        catalog_path,
    )

    with patch("kostream.media_import._load_folder_mal_map", return_value={}):
        resync_catalog_folders(media_root=root, catalog_path=catalog_path)
        resync_catalog_folders(media_root=root, catalog_path=catalog_path)

    state = load_catalog(catalog_path)
    assert state.get("mal-99901").folder == "Obscure English Title"
    assert _disk_episode_sum(root, catalog_path) == 2


def test_import_resync_idempotent_bindings_and_episode_sum(tmp_path: Path):
    """Import → Resync → Import → Resync must keep stable folders and episode totals."""
    from kostream.media_import import resync_catalog_folders

    root = tmp_path / "anime"
    for name, n in (
        ("KonoSuba Season 1", 3),
        ("Your Name", 1),
        ("Mystery Local Show", 4),
    ):
        (root / name).mkdir(parents=True)
        for i in range(1, n + 1):
            (root / name / f"S01E{i:02d}.mp4").write_bytes(b"v")

    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-30831",
                    enabled=True,
                    source="mal",
                    mal_id=30831,
                    title="Kono Subarashii Sekai ni Shukufuku wo!",
                ),
                CatalogEntry(
                    id="mal-32281",
                    enabled=True,
                    source="mal",
                    mal_id=32281,
                    title="Kimi no Na wa.",
                ),
            ]
        ),
        catalog_path,
    )

    folder_map = {
        "KonoSuba Season 1": 30831,
        "Your Name": 32281,
    }

    with patch("kostream.media_import._load_folder_mal_map", return_value=folder_map):
        with patch("kostream.media_import.ensure_episode_titles_async"):
            with patch("kostream.media_import.search_anime", return_value=[]):
                import_media_to_catalog(
                    media_root=root, catalog_path=catalog_path, sync_mal=False
                )
                resync_catalog_folders(media_root=root, catalog_path=catalog_path)
                bindings_a = _folder_bindings(catalog_path)
                sum_a = _disk_episode_sum(root, catalog_path)

                import_media_to_catalog(
                    media_root=root, catalog_path=catalog_path, sync_mal=False
                )
                resync_catalog_folders(media_root=root, catalog_path=catalog_path)
                bindings_b = _folder_bindings(catalog_path)
                sum_b = _disk_episode_sum(root, catalog_path)

                resync_catalog_folders(media_root=root, catalog_path=catalog_path)
                bindings_c = _folder_bindings(catalog_path)
                sum_c = _disk_episode_sum(root, catalog_path)

    assert bindings_a == bindings_b == bindings_c
    assert sum_a == sum_b == sum_c == 8
    assert bindings_a["mal-30831"] == "KonoSuba Season 1"
    assert bindings_a["mal-32281"] == "Your Name"
    # Local-only mystery folder stays bound to its local catalog row.
    local_ids = [eid for eid, folder in bindings_a.items() if folder == "Mystery Local Show"]
    assert len(local_ids) == 1
