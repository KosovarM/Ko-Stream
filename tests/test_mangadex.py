"""MangaDex chapter-title helpers + sync mapping."""

from __future__ import annotations

from pathlib import Path

from kostream import mangadex as mdx
from kostream.manga import (
    MangaChapter,
    apply_mangadex_chapter_titles,
    local_chapter_title_is_meaningful,
)
from kostream.manga_catalog import MangaCatalogEntry, MangaCatalogState, save_manga_catalog


def test_normalize_chapter_key():
    assert mdx.normalize_chapter_key("01") == "1"
    assert mdx.normalize_chapter_key("7.5") == "7.5"
    assert mdx.normalize_chapter_key(7.50) == "7.5"
    assert mdx.normalize_chapter_key("0") == "0"
    assert mdx.normalize_chapter_key("") is None
    assert mdx.normalize_chapter_key(None) is None


def test_chapter_titles_from_feed_rows_english_only():
    rows = [
        {
            "attributes": {
                "chapter": "1",
                "title": "日本語",
                "translatedLanguage": "ja",
            }
        },
        {
            "attributes": {
                "chapter": "1",
                "title": "Romance Dawn",
                "translatedLanguage": "en",
            }
        },
        {
            "attributes": {
                "chapter": "7.5",
                "title": "Extra",
                "translatedLanguage": "ja",
            }
        },
        {
            "attributes": {
                "chapter": "2",
                "title": "",
                "translatedLanguage": "en",
            }
        },
        {
            "attributes": {
                "chapter": "2",
                "title": "Capítulo Dos",
                "translatedLanguage": "es-la",
            }
        },
        {
            "attributes": {
                "chapter": "98",
                "title": "Ave e Guerra",
                "translatedLanguage": "pt-br",
            }
        },
        {
            "attributes": {
                "chapter": None,
                "title": "Oneshot",
                "translatedLanguage": "en",
            }
        },
    ]
    titles = mdx.chapter_titles_from_feed_rows(rows)
    assert titles == {"1": "Romance Dawn"}


def test_chapter_titles_does_not_fill_gaps_from_other_langs():
    """EN-untitled chapters stay empty; pt-br / es-la must not fill in."""
    rows = [
        {
            "attributes": {
                "chapter": "97",
                "title": "In a Dream",
                "translatedLanguage": "en",
            }
        },
        {
            "attributes": {
                "chapter": "98",
                "title": "",
                "translatedLanguage": "en",
            }
        },
        {
            "attributes": {
                "chapter": "98",
                "title": "Bird and War",
                "translatedLanguage": "pt-br",
            }
        },
    ]
    titles = mdx.chapter_titles_from_feed_rows(rows)
    assert titles["97"] == "In a Dream"
    assert "98" not in titles


def test_pick_mangadex_id_for_mal_matches_links():
    rows = [
        {
            "id": "aaa",
            "attributes": {"year": 1997, "links": {"mal": "999"}},
        },
        {
            "id": "bbb",
            "attributes": {"year": 1997, "links": {"mal": "21"}},
        },
    ]
    assert mdx.pick_mangadex_id_for_mal(rows, 21) == "bbb"
    assert mdx.pick_mangadex_id_for_mal(rows, 21, year=1997) == "bbb"
    assert mdx.pick_mangadex_id_for_mal(rows, 42) is None


def test_title_search_queries_variants():
    queries = mdx.title_search_queries("Fate/Extra CCC: Fox Tail")
    assert "Fate/Extra CCC: Fox Tail" in queries
    assert "Fate Extra CCC Fox Tail" in queries
    assert "Fate Extra" in queries


def test_search_manga_paginated_dedupes(monkeypatch):
    pages = {
        0: [{"id": "a"}, {"id": "b"}],
        2: [{"id": "b"}, {"id": "c"}],
    }

    def fake_search(title, *, limit=25, offset=0):
        return pages.get(offset, [])

    monkeypatch.setattr(mdx, "search_manga_by_title", fake_search)
    rows = mdx.search_manga_paginated("One Piece", limit=2, max_pages=3)
    assert [r["id"] for r in rows] == ["a", "b", "c"]


def test_find_mangadex_id_for_mal_tries_queries(monkeypatch):
    calls: list[str] = []

    def fake_paginated(title, **kwargs):
        calls.append(title)
        if title == "Fate Extra":
            return [
                {
                    "id": "uuid-fox",
                    "attributes": {"links": {"mal": "61147"}},
                }
            ]
        return []

    monkeypatch.setattr(mdx, "search_manga_paginated", fake_paginated)
    found, query = mdx.find_mangadex_id_for_mal(61147, "Fate/Extra CCC: Fox Tail")
    assert found == "uuid-fox"
    assert query == "Fate Extra"
    assert "Fate Extra" in calls


def test_unresolved_resolution_due_retries_old_negative_cache(tmp_path: Path):
    id_map = tmp_path / "id_map.json"
    mdx.save_id_map(
        {
            "61147": {
                "mangadex_id": False,
                "source": "search",
                "resolved_at": "2026-07-27T00:00:00Z",
            }
        },
        id_map,
    )
    assert mdx.unresolved_resolution_due(61147, id_map_path=id_map) is True

    mdx.save_id_map(
        {
            "61147": {
                "mangadex_id": False,
                "source": "search",
                "resolution_version": mdx.RESOLUTION_VERSION,
                "resolved_at": "2026-07-27T00:00:00Z",
            }
        },
        id_map,
    )
    assert mdx.unresolved_resolution_due(61147, id_map_path=id_map) is False


def test_resolve_retries_stale_negative_cache(tmp_path: Path, monkeypatch):
    id_map = tmp_path / "id_map.json"
    mdx.save_id_map(
        {
            "61147": {
                "mangadex_id": False,
                "source": "search",
                "resolved_at": "2026-07-27T00:00:00Z",
            }
        },
        id_map,
    )
    monkeypatch.setattr(
        mdx,
        "find_mangadex_id_for_mal",
        lambda mal_id, title, year=None: ("uuid-fox", "Fate Extra"),
    )
    uuid = mdx.resolve_mangadex_id(
        61147,
        "Fate/Extra CCC: Fox Tail",
        id_map_path=id_map,
        force=True,
    )
    assert uuid == "uuid-fox"


def test_local_chapter_title_is_meaningful():
    assert local_chapter_title_is_meaningful("Chapter 01") is False
    assert local_chapter_title_is_meaningful("Chapter 7.5") is False
    assert local_chapter_title_is_meaningful("Chapter 01: Romance Dawn") is True
    assert local_chapter_title_is_meaningful("Light Yagami") is True


def test_apply_mangadex_chapter_titles_overlays_generic_only():
    chapters = [
        MangaChapter(
            id="a",
            title="Chapter 1",
            page_count=10,
            kind="dir",
            relative="Chapter 01",
        ),
        MangaChapter(
            id="b",
            title="Chapter 2: Local Name",
            page_count=10,
            kind="dir",
            relative="Chapter 02 - Local Name",
        ),
        MangaChapter(
            id="c",
            title="Chapter 7.5",
            page_count=5,
            kind="cbz",
            relative="Chapter 07.5.cbz",
        ),
    ]
    out = apply_mangadex_chapter_titles(
        chapters,
        {"1": "Romance Dawn", "2": "Should Not Win", "7.5": "Extra"},
    )
    assert out[0].title == "Chapter 1: Romance Dawn"
    assert out[1].title == "Chapter 2: Local Name"
    assert out[2].title == "Chapter 7.5: Extra"


def test_store_and_load_chapter_titles(tmp_path: Path):
    root = tmp_path / "chapters"
    mdx._store_chapter_titles(
        21,
        {"01": "Romance Dawn", "7.50": "Extra"},
        mangadex_id="uuid-21",
        known_chapters=["1", "2", "7.5"],
        root=root,
    )
    assert mdx.chapter_titles_need_fetch(21, root=root) is False
    assert mdx.load_cached_chapter_titles(21, root=root) == {
        "1": "Romance Dawn",
        "7.5": "Extra",
    }


def test_chapter_titles_need_fetch_retries_incomplete_and_lang_change(tmp_path: Path):
    root = tmp_path / "chapters"
    mdx._store_chapter_titles(
        21,
        {"1": "Only"},
        mangadex_id="uuid",
        complete=False,
        known_chapters=["1"],
        languages=("en", "ja"),
        root=root,
    )
    assert mdx.chapter_titles_need_fetch(21, root=root) is True

    mdx._store_chapter_titles(
        21,
        {"1": "Only"},
        mangadex_id="uuid",
        complete=True,
        known_chapters=["1"],
        languages=("en", "ja"),
        root=root,
    )
    # Language fingerprint differs from current FEED_LANGUAGES → retry.
    assert mdx.chapter_titles_need_fetch(21, root=root) is True

    mdx._store_chapter_titles(
        21,
        {"1": "Only"},
        mangadex_id="uuid",
        complete=True,
        known_chapters=["1", "2"],
        languages=mdx.FEED_LANGUAGES,
        root=root,
    )
    assert mdx.chapter_titles_need_fetch(21, root=root) is False
    # Local chapter MDX has never seen → retry.
    assert mdx.chapter_titles_need_fetch(21, root=root, local_keys={"1", "99"}) is True
    # Local chapter known but untitled on MDX → do not hammer.
    assert mdx.chapter_titles_need_fetch(21, root=root, local_keys={"1", "2"}) is False


def test_resolve_mangadex_id_override_and_cache(tmp_path: Path, monkeypatch):
    id_map = tmp_path / "id_map.json"
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("should not search when override set")

    monkeypatch.setattr(mdx, "search_manga_by_title", boom)
    uuid = mdx.resolve_mangadex_id(
        21,
        "One Piece",
        mangadex_id="override-uuid",
        id_map_path=id_map,
    )
    assert uuid == "override-uuid"
    assert calls["n"] == 0
    # Second call uses map without override
    uuid2 = mdx.resolve_mangadex_id(21, "One Piece", id_map_path=id_map)
    assert uuid2 == "override-uuid"


def test_ensure_chapter_titles_mocks_http(tmp_path: Path, monkeypatch):
    chapters_root = tmp_path / "chapters"
    id_map = tmp_path / "id_map.json"

    monkeypatch.setattr(
        mdx,
        "resolve_mangadex_id",
        lambda *a, **k: "mdx-uuid",
    )

    def fake_feed(_uuid, **_k):
        return mdx.ChapterFeedResult(
            rows=[
                {
                    "attributes": {
                        "chapter": "1",
                        "title": "Romance Dawn",
                        "translatedLanguage": "en",
                    }
                }
            ],
            complete=True,
        )

    monkeypatch.setattr(mdx, "fetch_chapter_feed", fake_feed)
    assert (
        mdx.ensure_chapter_titles(
            21,
            "One Piece",
            chapters_root=chapters_root,
            id_map_path=id_map,
        )
        is True
    )
    assert mdx.load_cached_chapter_titles(21, root=chapters_root)["1"] == "Romance Dawn"
    # Fresh cache → no-op
    assert (
        mdx.ensure_chapter_titles(
            21,
            "One Piece",
            chapters_root=chapters_root,
            id_map_path=id_map,
        )
        is False
    )


def test_ensure_retries_when_incomplete_flag(tmp_path: Path, monkeypatch):
    chapters_root = tmp_path / "chapters"
    mdx._store_chapter_titles(
        21,
        {"1": "Partial"},
        mangadex_id="mdx-uuid",
        complete=False,
        known_chapters=["1"],
        languages=mdx.FEED_LANGUAGES,
        root=chapters_root,
    )
    calls = {"n": 0}

    def fake_feed(_uuid, **_k):
        calls["n"] += 1
        return mdx.ChapterFeedResult(
            rows=[
                {
                    "attributes": {
                        "chapter": "1",
                        "title": "Romance Dawn",
                        "translatedLanguage": "en",
                    }
                },
                {
                    "attributes": {
                        "chapter": "2",
                        "title": "They Call Him Straw Hat Luffy",
                        "translatedLanguage": "en",
                    }
                },
            ],
            complete=True,
        )

    monkeypatch.setattr(mdx, "resolve_mangadex_id", lambda *a, **k: "mdx-uuid")
    monkeypatch.setattr(mdx, "fetch_chapter_feed", fake_feed)
    assert mdx.ensure_chapter_titles(21, "One Piece", chapters_root=chapters_root) is True
    assert calls["n"] == 1
    cached = mdx.load_cached_chapter_titles(21, root=chapters_root)
    assert cached["1"] == "Romance Dawn"
    assert cached["2"] == "They Call Him Straw Hat Luffy"
    assert mdx.chapter_titles_need_fetch(21, root=chapters_root) is False


def test_fetch_chapter_feed_paginates_all_pages(monkeypatch):
    """Walk every page until exhausted (no early stop at first 100)."""
    seen_offsets: list[int] = []

    def fake_get(url: str, *, sleep: float = 0):
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(url).query)
        offset = int(qs.get("offset", ["0"])[0])
        seen_offsets.append(offset)
        if offset == 0:
            batch = [
                {
                    "attributes": {
                        "chapter": str(i + 1),
                        "title": f"T{i + 1}",
                        "translatedLanguage": "en",
                    }
                }
                for i in range(100)
            ]
            return {"data": batch, "total": 107}
        batch = [
            {
                "attributes": {
                    "chapter": str(101 + i),
                    "title": f"T{101 + i}",
                    "translatedLanguage": "en",
                }
            }
            for i in range(7)
        ]
        return {"data": batch, "total": 107}

    monkeypatch.setattr(mdx, "_http_get_json", fake_get)
    result = mdx.fetch_chapter_feed("uuid-test")
    assert seen_offsets == [0, 100]
    assert result.complete is True
    assert len(result.rows) == 107
    titles = mdx.chapter_titles_from_feed_rows(result.rows)
    assert titles["1"] == "T1"
    assert titles["107"] == "T107"
    # Non-en rows in a mixed feed must not become titles.
    mixed = result.rows + [
        {
            "attributes": {
                "chapter": "108",
                "title": "Capítulo",
                "translatedLanguage": "es-la",
            }
        }
    ]
    assert "108" not in mdx.chapter_titles_from_feed_rows(mixed)


def test_sync_catalog_chapter_titles_only_local_and_limit(
    tmp_path: Path, monkeypatch
):
    media = tmp_path / "manga"
    series = media / "Local Series"
    ch = series / "Chapter 01"
    ch.mkdir(parents=True)
    (ch / "01.png").write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
            "de0000000c4944415408d763f8ffff3f0005fe02fea5725f160000000049454e44ae426082"
        )
    )
    catalog_path = tmp_path / "selected.json"
    state = MangaCatalogState(
        titles=[
            MangaCatalogEntry(
                id="mal-manga-1",
                source="mal",
                folder="Local Series",
                mal_id=1,
                title="Local Series",
            ),
            MangaCatalogEntry(
                id="mal-manga-2",
                source="mal",
                folder=None,
                mal_id=2,
                title="Remote Only",
            ),
            MangaCatalogEntry(
                id="mal-manga-3",
                source="mal",
                folder="Local Series",
                mal_id=3,
                title="Also Local",
            ),
        ]
    )
    save_manga_catalog(state, catalog_path)

    seen: list[int] = []

    def fake_ensure(mal_id, title, **kwargs):
        seen.append(mal_id)
        return True

    monkeypatch.setattr(mdx, "ensure_chapter_titles", fake_ensure)
    monkeypatch.setattr(mdx, "chapter_titles_need_fetch", lambda mal_id, **k: True)

    updated = mdx.sync_catalog_chapter_titles(
        catalog_path,
        manga_media_root=media,
        limit=1,
    )
    assert updated.updated == 1
    assert updated.attempted == 1
    assert seen == [1]  # remote-only skipped; batch limit 1


def test_fetch_chapter_feed_omits_invalid_order(monkeypatch):
    """MangaDex rejects order[translatedLanguage] on /feed (HTTP 400)."""
    seen_urls: list[str] = []

    def fake_get(url: str, *, sleep: float = 0):
        seen_urls.append(url)
        return {"data": [], "total": 0}

    monkeypatch.setattr(mdx, "_http_get_json", fake_get)
    mdx.fetch_chapter_feed("uuid-test")
    assert seen_urls
    assert "order%5BtranslatedLanguage%5D" not in seen_urls[0]
    assert "order[translatedLanguage]" not in seen_urls[0]
    assert "order%5Bchapter%5D=asc" in seen_urls[0] or "order[chapter]=asc" in seen_urls[0]
    # English only — no Spanish / Portuguese / Japanese query params.
    assert "translatedLanguage%5B%5D=en" in seen_urls[0] or "translatedLanguage[]=en" in seen_urls[0]
    assert "es-la" not in seen_urls[0]
    assert "pt-br" not in seen_urls[0]
    assert "translatedLanguage%5B%5D=ja" not in seen_urls[0]
    assert "translatedLanguage[]=ja" not in seen_urls[0]


def test_store_replace_titles_drops_non_english_cache(tmp_path: Path, monkeypatch):
    """Re-fetch with replace_titles must wipe Spanish leftovers from old multi-lang cache."""
    chapters_root = tmp_path / "chapters"
    mdx._store_chapter_titles(
        21,
        {"1": "Romance Dawn", "2": "Capítulo Dos", "98": "Ave e Guerra"},
        mangadex_id="mdx-uuid",
        complete=True,
        known_chapters=["1", "2", "98"],
        languages=("en", "ja", "es-la", "pt-br"),
        root=chapters_root,
    )
    assert mdx.chapter_titles_need_fetch(21, root=chapters_root) is True

    def fake_feed(_uuid, **_k):
        return mdx.ChapterFeedResult(
            rows=[
                {
                    "attributes": {
                        "chapter": "1",
                        "title": "Romance Dawn",
                        "translatedLanguage": "en",
                    }
                },
                {
                    "attributes": {
                        "chapter": "2",
                        "title": "",
                        "translatedLanguage": "en",
                    }
                },
            ],
            complete=True,
        )

    monkeypatch.setattr(mdx, "resolve_mangadex_id", lambda *a, **k: "mdx-uuid")
    monkeypatch.setattr(mdx, "fetch_chapter_feed", fake_feed)
    assert (
        mdx.ensure_chapter_titles(
            21,
            "One Piece",
            chapters_root=chapters_root,
            local_keys={"1", "2", "98"},
        )
        is True
    )
    cached = mdx.load_cached_chapter_titles(21, root=chapters_root)
    assert cached == {"1": "Romance Dawn"}
    assert "2" not in cached
    assert "98" not in cached
    # Local keys marked known so we do not re-queue forever for untitled EN gaps.
    assert mdx.chapter_titles_need_fetch(
        21, root=chapters_root, local_keys={"1", "2", "98"}
    ) is False


def test_chapter_list_parts_splits_number_and_name():
    from kostream.manga import chapter_list_parts

    assert chapter_list_parts("Chapter 1: Romance Dawn", relative="Chapter 01") == (
        "1",
        "Romance Dawn",
    )
    assert chapter_list_parts("Chapter 01", relative="Chapter 01") == ("1", "")
    assert chapter_list_parts("Light Yagami", relative="Chapter 01") == (
        "1",
        "Light Yagami",
    )
