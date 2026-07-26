"""Manga library scanner + page serving."""

from pathlib import Path
import zipfile

from kostream.manga import (
    filter_library_format,
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
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
    )
    client = app.test_client()
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


def test_manga_complete_range_api(tmp_path: Path, monkeypatch):
    from kostream import app as app_mod
    from kostream.app import create_app
    from kostream import manga_progress as mp

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
    completed = tmp_path / "manga_completed.json"
    monkeypatch.setattr(mp, "MANGA_COMPLETED_FILE", completed)
    monkeypatch.setattr(app_mod, "MANGA_COMPLETED_FILE", completed)

    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
    )
    client = app.test_client()
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
    from kostream import app as app_mod
    from kostream.app import create_app
    from kostream import manga_progress as mp
    from kostream import mal as mal_mod
    from kostream.mal import MalMangaEntry
    from kostream.manga_catalog import (
        MangaCatalogEntry,
        MangaCatalogState,
        save_manga_catalog,
    )

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
    completed = tmp_path / "manga_completed.json"
    monkeypatch.setattr(mp, "MANGA_COMPLETED_FILE", completed)
    monkeypatch.setattr(app_mod, "MANGA_COMPLETED_FILE", completed)

    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
    )
    client = app.test_client()
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
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
    )
    client = app.test_client()
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
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
    )
    client = app.test_client()

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
