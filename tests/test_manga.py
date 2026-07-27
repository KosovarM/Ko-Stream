"""Manga library scanner + page serving."""

from pathlib import Path
import zipfile

from kostream.manga import (
    chapter_display_title,
    filter_library_format,
    find_manga_in_library,
    get_manga,
    list_page_refs,
    load_manga_library,
    read_page_bytes,
    scan_manga_library,
    MangaTitle,
)
from kostream.manga_catalog import (
    MangaCatalogEntry,
    MangaCatalogState,
    match_local_folder,
    save_manga_catalog,
)
from kostream.manga_progress import load_manga_completed


def _write_png(path: Path, n: int = 1) -> None:
    # Minimal valid 1x1 PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415408d763f8ffff3f0005fe02fea5725f160000000049454e44ae426082"
    )
    path.write_bytes(png * n)


def test_scan_folder_images(tmp_path: Path):
    root = tmp_path / "manga"
    title = root / "Demo Title"
    ch = title / "Chapter 01"
    ch.mkdir(parents=True)
    _write_png(ch / "01.png")
    _write_png(ch / "02.png")
    titles = scan_manga_library(root)
    assert len(titles) == 1
    assert titles[0].title == "Demo Title"
    assert titles[0].chapter_count == 1
    assert titles[0].chapters[0].page_count == 2


def test_chapter_order_half_chapters(tmp_path: Path):
    """Half chapters (.5) must sort after the integer chapter (7 < 7.5)."""
    from kostream.manga import _natural_key

    names = [
        "Chapter 08.cbz",
        "Chapter 07.5.cbz",
        "Chapter 06.cbz",
        "Chapter 07.cbz",
        "Chapter 00.5.cbz",
    ]
    assert sorted(names, key=_natural_key) == [
        "Chapter 00.5.cbz",
        "Chapter 06.cbz",
        "Chapter 07.cbz",
        "Chapter 07.5.cbz",
        "Chapter 08.cbz",
    ]

    root = tmp_path / "manga"
    title = root / "Fate Extra CCC Fox Tail"
    title.mkdir(parents=True)
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415408d763f8ffff3f0005fe02fea5725f160000000049454e44ae426082"
    )
    for name in names:
        with zipfile.ZipFile(title / name, "w") as zf:
            zf.writestr("page1.png", png)

    titles = scan_manga_library(root)
    assert len(titles) == 1
    assert [c.relative for c in titles[0].chapters] == [
        "Chapter 00.5.cbz",
        "Chapter 06.cbz",
        "Chapter 07.cbz",
        "Chapter 07.5.cbz",
        "Chapter 08.cbz",
    ]


def test_chapter_order_half_chapters_dirs(tmp_path: Path):
    root = tmp_path / "manga"
    title = root / "Half Chapters"
    for name in ("Chapter 06", "Chapter 07.5", "Chapter 07", "Chapter 08", "Chapter 00.5"):
        ch = title / name
        ch.mkdir(parents=True)
        _write_png(ch / "01.png")
    titles = scan_manga_library(root)
    assert [c.title for c in titles[0].chapters] == [
        "Chapter 00.5",
        "Chapter 06",
        "Chapter 07",
        "Chapter 07.5",
        "Chapter 08",
    ]


def test_scan_cbz(tmp_path: Path):
    root = tmp_path / "manga"
    root.mkdir()
    cbz = root / "One Shot.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr(
            "page1.png",
            bytes.fromhex(
                "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
                "de0000000c4944415408d763f8ffff3f0005fe02fea5725f160000000049454e44ae426082"
            ),
        )
    titles = scan_manga_library(root)
    assert len(titles) == 1
    assert titles[0].chapters[0].kind == "cbz"
    manga = get_manga(titles[0].id, root)
    pages = list_page_refs(root, manga, manga.chapters[0])
    assert len(pages) == 1
    data, mime = read_page_bytes(root, manga, manga.chapters[0], 0)
    assert mime == "image/png"
    assert data.startswith(b"\x89PNG")


def test_match_local_folder(tmp_path: Path):
    root = tmp_path / "manga"
    (root / "Fate Extra CCC Fox Tail").mkdir(parents=True)
    (root / "Other").mkdir()
    assert match_local_folder(root, "Fate/Extra CCC: Fox Tail") == "Fate Extra CCC Fox Tail"
    assert match_local_folder(root, "Missing") is None


def test_load_manga_library_merges_mal(tmp_path: Path, monkeypatch):
    from kostream import mal as mal_mod
    from kostream.mal import MalMangaEntry

    media = tmp_path / "manga"
    local = media / "Berserk"
    local.mkdir(parents=True)
    _write_png(local / "01.png")

    catalog = tmp_path / "selected.json"
    save_manga_catalog(
        MangaCatalogState(
            titles=[
                MangaCatalogEntry(
                    id="mal-manga-2",
                    enabled=True,
                    source="mal",
                    folder="Berserk",
                    mal_id=2,
                    title="Berserk",
                ),
                MangaCatalogEntry(
                    id="mal-manga-99",
                    enabled=True,
                    source="mal",
                    mal_id=99,
                    title="Plan Only",
                ),
            ]
        ),
        catalog,
    )

    cache = tmp_path / "manga_cache"
    monkeypatch.setattr(mal_mod, "MANGA_CACHE_DIR", cache)
    mal_mod.write_cached_manga(
        MalMangaEntry(
            mal_id=2,
            title="Berserk",
            synopsis="Dark fantasy.",
            poster_url="https://example.com/b.jpg",
            genres=["Action"],
            num_volumes=40,
            num_chapters=364,
            list_status="reading",
            num_volumes_read=1,
            num_chapters_read=10,
            manga_status="currently_publishing",
            score=10,
            mean_score=9.4,
        )
    )
    mal_mod.write_cached_manga(
        MalMangaEntry(
            mal_id=99,
            title="Plan Only",
            synopsis="",
            poster_url="https://example.com/p.jpg",
            genres=[],
            num_volumes=0,
            num_chapters=12,
            list_status="plan_to_read",
            num_volumes_read=0,
            num_chapters_read=0,
            manga_status=None,
            score=0,
            mean_score=None,
        )
    )

    titles = load_manga_library(media, catalog)
    by_id = {t.id: t for t in titles}
    assert "mal-manga-2" in by_id
    assert by_id["mal-manga-2"].has_local
    assert by_id["mal-manga-2"].page_count == 1
    assert by_id["mal-manga-2"].poster_url.endswith("b.jpg")
    assert by_id["mal-manga-2"].genres == ["Action"]
    assert "mal-manga-99" in by_id
    assert not by_id["mal-manga-99"].has_local
    assert by_id["mal-manga-99"].num_chapters_mal == 12


def test_collect_manga_genres_and_match():
    from kostream.manga import collect_manga_genres, title_matches_genre

    titles = [
        MangaTitle(id="a", title="A", folder="", genres=["Action", "Fantasy"]),
        MangaTitle(id="b", title="B", folder="", genres=["Action", "Comedy"]),
        MangaTitle(id="c", title="C", folder="", genres=[]),
    ]
    assert collect_manga_genres(titles) == ["Action", "Comedy", "Fantasy"]
    assert title_matches_genre(titles[0], "Fantasy")
    assert not title_matches_genre(titles[1], "Fantasy")
    assert title_matches_genre(titles[2], "")
    assert not title_matches_genre(titles[2], "Action")


def test_manga_routes(tmp_path: Path):
    from kostream.app import create_app

    from conftest import bootstrap_test_users, login_client

    media = tmp_path / "shows"
    media.mkdir()
    manga_root = tmp_path / "manga"
    title = manga_root / "Sample"
    title.mkdir(parents=True)
    _write_png(title / "a.png")
    _write_png(title / "b.png")
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    manga_catalog = tmp_path / "manga_selected.json"
    manga_catalog.write_text('{"titles": []}', encoding="utf-8")
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)
    resp = client.get("/manga")
    assert resp.status_code == 200
    assert b"Manga" in resp.data
    titles = scan_manga_library(manga_root)
    mid = titles[0].id
    pages = client.get(f"/api/manga/{mid}/pages").get_json()
    assert pages["ok"] is True
    assert len(pages["pages"]) == 2
    img = client.get(f"/manga-page/{mid}/{titles[0].chapters[0].id}/0")
    assert img.status_code == 200
    assert img.content_type.startswith("image/")


def test_manga_complete_range_api(tmp_path: Path):
    from kostream.app import create_app
    from kostream.user_paths import user_data_paths

    from conftest import bootstrap_test_users, login_client

    media = tmp_path / "shows"
    media.mkdir()
    manga_root = tmp_path / "manga"
    title = manga_root / "Range Demo"
    ch1 = title / "Chapter 01"
    ch2 = title / "Chapter 02"
    ch3 = title / "Chapter 03"
    for ch in (ch1, ch2, ch3):
        ch.mkdir(parents=True)
        _write_png(ch / "01.png")
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    manga_catalog = tmp_path / "manga_selected.json"
    manga_catalog.write_text('{"titles": []}', encoding="utf-8")

    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    completed = user_data_paths("u_testuser", user_data)["manga_completed"]
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)
    titles = scan_manga_library(manga_root)
    mid = titles[0].id
    chapters = titles[0].chapters
    assert len(chapters) == 3

    resp = client.post(
        "/api/manga/complete-range",
        json={
            "manga_id": mid,
            "from_chapter_id": chapters[0].id,
            "to_chapter_id": chapters[1].id,
        },
    )
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["chapters_read"] == 2
    assert data["from_pos"] == 1
    assert data["to_pos"] == 2
    assert load_manga_completed(completed)[mid] == 2

    # Position-based + already-read chapters still ok
    resp2 = client.post(
        "/api/manga/complete-range",
        json={"manga_id": mid, "from_pos": 1, "to_pos": 3},
    )
    data2 = resp2.get_json()
    assert resp2.status_code == 200
    assert data2["chapters_read"] == 3


def test_manga_complete_range_meta_only(tmp_path: Path, monkeypatch):
    from kostream.app import create_app
    from kostream import mal as mal_mod
    from kostream.mal import MalMangaEntry
    from kostream.manga_catalog import (
        MangaCatalogEntry,
        MangaCatalogState,
        save_manga_catalog,
    )
    from kostream.user_paths import user_data_paths

    from conftest import bootstrap_test_users, login_client

    media = tmp_path / "shows"
    media.mkdir()
    manga_root = tmp_path / "manga"
    manga_root.mkdir()
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    manga_catalog = tmp_path / "manga_selected.json"
    save_manga_catalog(
        MangaCatalogState(
            titles=[
                MangaCatalogEntry(
                    id="mal-manga-88",
                    enabled=True,
                    source="mal",
                    mal_id=88,
                    title="Meta Range",
                )
            ]
        ),
        manga_catalog,
    )
    cache = tmp_path / "manga_cache"
    monkeypatch.setattr(mal_mod, "MANGA_CACHE_DIR", cache)
    mal_mod.write_cached_manga(
        MalMangaEntry(
            mal_id=88,
            title="Meta Range",
            synopsis="",
            poster_url="",
            genres=[],
            num_volumes=0,
            num_chapters=10,
            list_status="reading",
            num_volumes_read=0,
            num_chapters_read=0,
            manga_status="currently_publishing",
            score=0,
            mean_score=None,
        )
    )
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    completed = user_data_paths("u_testuser", user_data)["manga_completed"]
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)
    resp = client.post(
        "/api/manga/complete-range",
        json={"manga_id": "mal-manga-88", "from_pos": 2, "to_pos": 4},
    )
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["chapters_read"] == 4
    assert load_manga_completed(completed)["mal-manga-88"] == 4

def test_filter_library_format_splits_manhwa():
    manga = MangaTitle(id="m1", title="Manga", folder="a", media_type="manga")
    manhwa = MangaTitle(id="m2", title="Solo", folder="b", media_type="manhwa")
    novel = MangaTitle(id="m3", title="Novel", folder="c", media_type="novel")
    titles = [manga, manhwa, novel]
    assert [t.id for t in filter_library_format(titles, kind="manhwa")] == ["m2"]
    assert [t.id for t in filter_library_format(titles, kind="manga")] == ["m1", "m3"]


def test_manhwa_route(tmp_path: Path, monkeypatch):
    from kostream.app import create_app
    from kostream import mal as mal_mod
    from kostream.mal import MalMangaEntry

    from conftest import bootstrap_test_users, login_client

    media = tmp_path / "shows"
    media.mkdir()
    manga_root = tmp_path / "manga"
    manga_root.mkdir()
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    manga_catalog = tmp_path / "manga_selected.json"
    save_manga_catalog(
        MangaCatalogState(
            titles=[
                MangaCatalogEntry(
                    id="mal-manga-1",
                    enabled=True,
                    source="mal",
                    mal_id=1,
                    title="Solo Leveling",
                    media_type="manhwa",
                ),
                MangaCatalogEntry(
                    id="mal-manga-2",
                    enabled=True,
                    source="mal",
                    mal_id=2,
                    title="Berserk",
                    media_type="manga",
                ),
            ]
        ),
        manga_catalog,
    )
    cache = tmp_path / "manga_cache"
    monkeypatch.setattr(mal_mod, "MANGA_CACHE_DIR", cache)
    mal_mod.write_cached_manga(
        MalMangaEntry(
            mal_id=1,
            title="Solo Leveling",
            synopsis="",
            poster_url=None,
            genres=[],
            num_volumes=0,
            num_chapters=10,
            list_status="reading",
            num_volumes_read=0,
            num_chapters_read=1,
            manga_status="currently_publishing",
            score=0,
            mean_score=None,
            media_type="manhwa",
        )
    )
    mal_mod.write_cached_manga(
        MalMangaEntry(
            mal_id=2,
            title="Berserk",
            synopsis="",
            poster_url=None,
            genres=[],
            num_volumes=40,
            num_chapters=100,
            list_status="reading",
            num_volumes_read=0,
            num_chapters_read=1,
            manga_status="currently_publishing",
            score=0,
            mean_score=None,
            media_type="manga",
        )
    )
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)
    manhwa = client.get("/manhwa")
    assert manhwa.status_code == 200
    assert b"Solo Leveling" in manhwa.data
    assert b"Berserk" not in manhwa.data
    manga = client.get("/manga")
    assert manga.status_code == 200
    assert b"Berserk" in manga.data
    assert b"Solo Leveling" not in manga.data


def test_manga_genre_filter_ui(tmp_path: Path, monkeypatch):
    from kostream.app import create_app
    from kostream import mal as mal_mod
    from kostream.mal import MalMangaEntry

    from conftest import bootstrap_test_users, login_client

    media = tmp_path / "shows"
    media.mkdir()
    manga_root = tmp_path / "manga"
    manga_root.mkdir()
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    manga_catalog = tmp_path / "manga_selected.json"
    save_manga_catalog(
        MangaCatalogState(
            titles=[
                MangaCatalogEntry(
                    id="mal-manga-1",
                    enabled=True,
                    source="mal",
                    mal_id=1,
                    title="Action Title",
                    media_type="manga",
                ),
                MangaCatalogEntry(
                    id="mal-manga-2",
                    enabled=True,
                    source="mal",
                    mal_id=2,
                    title="Romance Title",
                    media_type="manga",
                ),
            ]
        ),
        manga_catalog,
    )
    cache = tmp_path / "manga_cache"
    monkeypatch.setattr(mal_mod, "MANGA_CACHE_DIR", cache)
    mal_mod.write_cached_manga(
        MalMangaEntry(
            mal_id=1,
            title="Action Title",
            synopsis="",
            poster_url=None,
            genres=["Action", "Adventure"],
            num_volumes=1,
            num_chapters=10,
            list_status="reading",
            num_volumes_read=0,
            num_chapters_read=1,
            manga_status="currently_publishing",
            score=0,
            mean_score=None,
            media_type="manga",
        )
    )
    mal_mod.write_cached_manga(
        MalMangaEntry(
            mal_id=2,
            title="Romance Title",
            synopsis="",
            poster_url=None,
            genres=["Romance"],
            num_volumes=1,
            num_chapters=5,
            list_status="reading",
            num_volumes_read=0,
            num_chapters_read=1,
            manga_status="currently_publishing",
            score=0,
            mean_score=None,
            media_type="manga",
        )
    )
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)

    page = client.get("/manga")
    assert page.status_code == 200
    assert b'data-manga-genre' in page.data or b'id="manga-genre"' in page.data
    assert b"Mark title completed" in page.data
    assert b"Mark chapter range" in page.data
    assert b"Action" in page.data
    assert b"Romance" in page.data
    assert b'data-genres="Action|Adventure"' in page.data
    assert b'data-genres="Romance"' in page.data

    filtered = client.get("/manga?genre=Romance")
    assert filtered.status_code == 200
    assert b'value="Romance" selected' in filtered.data or b'selected' in filtered.data
    # Romance title visible; Action title card hidden via SSR
    assert b"Romance Title" in filtered.data
    html = filtered.data.decode("utf-8")
    # Action Title article should carry hidden when genre filter excludes it
    assert 'data-genres="Action|Adventure"' in html
    action_idx = html.index('data-genres="Action|Adventure"')
    article_start = html.rfind("<article", 0, action_idx)
    article_snip = html[article_start : action_idx + 80]
    assert "hidden" in article_snip


def test_chapter_display_title_from_filename():
    assert chapter_display_title("Chapter 01") == "Chapter 01"
    assert chapter_display_title("Chapter 01 - The Beginning") == "Chapter 01: The Beginning"
    assert chapter_display_title("Ch.12: Reunion") == "Chapter 12: Reunion"
    assert chapter_display_title("c003 — Extra") == "Chapter 003: Extra"
    assert chapter_display_title("42 - Cliffhanger") == "Chapter 42: Cliffhanger"


def test_chapter_display_title_prefers_comicinfo():
    assert (
        chapter_display_title("Chapter 05.cbz", comic_title="Light Yagami")
        == "Chapter 05: Light Yagami"
    )
    assert (
        chapter_display_title("Chapter 05.cbz", comic_title="Chapter 5 - Named")
        == "Chapter 5: Named"
    )


def test_scan_cbz_uses_comicinfo_and_filename_title(tmp_path: Path):
    """Scan stays filename-fast; ComicInfo titles resolve on chapter enrich."""
    from kostream.manga import enrich_manga_chapter

    root = tmp_path / "manga"
    title = root / "Demo Series"
    title.mkdir(parents=True)
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415408d763f8ffff3f0005fe02fea5725f160000000049454e44ae426082"
    )
    with_info = title / "Chapter 01.cbz"
    with zipfile.ZipFile(with_info, "w") as zf:
        zf.writestr("page1.png", png)
        zf.writestr(
            "ComicInfo.xml",
            '<?xml version="1.0"?><ComicInfo><Title>Bored at Home</Title>'
            "<Number>1</Number></ComicInfo>",
        )
    named = title / "Chapter 02 - School Arc.cbz"
    with zipfile.ZipFile(named, "w") as zf:
        zf.writestr("page1.png", png)

    titles = scan_manga_library(root)
    assert len(titles) == 1
    by_rel = {c.relative: c for c in titles[0].chapters}
    assert by_rel["Chapter 01.cbz"].title == "Chapter 01"
    assert by_rel["Chapter 01.cbz"].page_count == 0
    assert by_rel["Chapter 02 - School Arc.cbz"].title == "Chapter 02: School Arc"

    enriched, pages = enrich_manga_chapter(root, titles[0], by_rel["Chapter 01.cbz"])
    assert enriched.title == "Chapter 01: Bored at Home"
    assert enriched.page_count == 1
    assert len(pages) == 1


def test_manga_scan_cache_invalidates_on_change(tmp_path: Path):
    from kostream.manga import clear_manga_scan_cache

    clear_manga_scan_cache()
    root = tmp_path / "manga"
    title = root / "Series"
    title.mkdir(parents=True)
    first = title / "Chapter 01.cbz"
    with zipfile.ZipFile(first, "w") as zf:
        zf.writestr("page1.png", b"x")

    a = scan_manga_library(root)
    b = scan_manga_library(root)
    assert len(a[0].chapters) == 1
    assert len(b[0].chapters) == 1

    second = title / "Chapter 02.cbz"
    with zipfile.ZipFile(second, "w") as zf:
        zf.writestr("page1.png", b"y")
    c = scan_manga_library(root)
    assert len(c[0].chapters) == 2


def test_scan_folder_chapter_title_from_dirname(tmp_path: Path):
    root = tmp_path / "manga"
    ch = root / "Demo" / "Chapter 03 - Finale"
    ch.mkdir(parents=True)
    _write_png(ch / "01.png")
    titles = scan_manga_library(root)
    assert titles[0].chapters[0].title == "Chapter 03: Finale"


def test_find_manga_in_library_legacy_dir_id():
    remapped = MangaTitle(
        id="mal-manga-61147",
        title="Fate/Extra CCC: Fox Tail",
        folder="Fate Extra CCC Fox Tail",
        poster_url="https://cdn.myanimelist.net/images/manga/2/120387l.jpg",
        mal_id=61147,
        source="mal",
    )
    local_only = MangaTitle(
        id="dir-dice",
        title="Dice",
        folder="Dice",
        cover_chapter_id="ch1",
    )
    titles = [remapped, local_only]

    found = find_manga_in_library(
        titles, manga_id="dir-fate-extra-ccc-fox-tail"
    )
    assert found is remapped
    assert found.poster_url

    by_mal = find_manga_in_library(titles, mal_id=61147)
    assert by_mal is remapped

    by_title = find_manga_in_library(titles, title="Dice")
    assert by_title is local_only
