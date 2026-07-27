"""Sync skip index — completion detection and skip filtering."""

from __future__ import annotations

import json
from pathlib import Path

from kostream.catalog import CatalogEntry, CatalogState, save_catalog
from kostream.mal import sync_catalog_episode_titles, write_cached_anime, MalAnimeEntry
from kostream.models import Episode, Show
from kostream.sync_index import (
    anime_sync_status,
    episode_titles_status,
    load_anime_index,
    refresh_anime_index,
    save_anime_index,
    set_skip,
    should_skip,
    skipped_mal_ids,
)


def _show(*, mal_id: int = 1, airing: bool = False, episodes: int = 2) -> Show:
    eps = [
        Episode(
            id=f"ep-{i}",
            show_id="mal-1",
            season=1,
            number=i,
            title=f"Ep {i}",
            filename=f"ep{i}.mkv",
        )
        for i in range(1, episodes + 1)
    ]
    return Show(
        id=f"mal-{mal_id}",
        title="Test Anime",
        description="",
        mal_id=mal_id,
        anime_status="currently_airing" if airing else "finished_airing",
        episodes=eps,
    )


def _cache(mal_id: int, *, airing: bool = False, genres: list[str] | None = None) -> None:
    from kostream.mal import CACHE_DIR

    write_cached_anime(
        MalAnimeEntry(
            mal_id=mal_id,
            title="Test",
            synopsis="",
            poster_url=None,
            genres=genres or ["Action"],
            num_episodes=2,
            list_status="watching",
            num_episodes_watched=0,
            anime_status="currently_airing" if airing else "finished_airing",
            score=0,
            mean_score=None,
        )
    )
    path = CACHE_DIR / f"{mal_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data["details_enriched"] = True
        data["related_anime"] = []
        path.write_text(json.dumps(data), encoding="utf-8")


def test_should_skip_false_when_index_missing(tmp_path):
    assert should_skip(99, "anime_sync", index_path=tmp_path / "missing.json") is False


def test_set_skip_and_skipped_mal_ids(tmp_path):
    index_path = tmp_path / "animes.json"
    set_skip(42, "anime_sync", True, index_path=index_path)
    set_skip(43, "episode_titles", True, index_path=index_path)
    assert should_skip(42, "anime_sync", index_path=index_path)
    assert 42 in skipped_mal_ids("anime_sync", index_path=index_path)
    assert 43 in skipped_mal_ids("episode_titles", index_path=index_path)


def test_anime_sync_status_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "kostream.mal.CACHE_DIR",
        tmp_path / "cache",
    )
    (tmp_path / "cache").mkdir()
    _cache(7, genres=["Drama"])
    show = _show(mal_id=7, airing=False, episodes=2)
    complete, hint = anime_sync_status(show, 7)
    assert complete is True
    assert hint == "Complete"


def test_anime_sync_status_airing_not_complete(tmp_path, monkeypatch):
    monkeypatch.setattr("kostream.mal.CACHE_DIR", tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    _cache(8, airing=True)
    show = _show(mal_id=8, airing=True, episodes=2)
    complete, hint = anime_sync_status(show, 8)
    assert complete is False
    assert "airing" in hint.casefold()


def test_refresh_anime_index_auto_checks_complete(tmp_path, monkeypatch):
    monkeypatch.setattr("kostream.mal.CACHE_DIR", tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-10",
                    enabled=True,
                    source="mal",
                    mal_id=10,
                    title="Done Show",
                )
            ]
        ),
        catalog_path,
    )
    _cache(10)
    show = _show(mal_id=10, airing=False, episodes=2)
    monkeypatch.setattr(
        "kostream.library.scan_library",
        lambda *a, **k: [show],
    )
    index_path = tmp_path / "animes.json"
    count = refresh_anime_index(
        catalog_path=catalog_path,
        media_root=tmp_path / "media",
        index_path=index_path,
    )
    assert count == 1
    entries = load_anime_index(index_path)
    assert entries["10"]["skip_anime_sync"] is True
    assert entries["10"]["skip_episode_titles"] is False


def test_episode_titles_status_complete(tmp_path, monkeypatch):
    monkeypatch.setattr("kostream.mal.CACHE_DIR", tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    _cache(11)
    path = tmp_path / "cache" / "11.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["episode_titles"] = {"1": "One", "2": "Two"}
    data["episode_titles_fetched_at"] = "2026-01-01T00:00:00Z"
    path.write_text(json.dumps(data), encoding="utf-8")
    complete, hint = episode_titles_status(11)
    assert complete is True
    assert hint == "Complete"


def test_sync_episode_titles_respects_skip(tmp_path, monkeypatch):
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(id="mal-1", enabled=True, source="mal", mal_id=1, title="A"),
                CatalogEntry(id="mal-2", enabled=True, source="mal", mal_id=2, title="B"),
            ]
        ),
        catalog_path,
    )
    calls: list[int] = []

    def fake_need_fetch(mal_id: int) -> bool:
        return True

    def fake_ensure(mal_id: int, **k):
        calls.append(mal_id)
        return True

    monkeypatch.setattr("kostream.mal.episode_titles_need_fetch", fake_need_fetch)
    monkeypatch.setattr("kostream.mal.ensure_episode_titles", fake_ensure)
    monkeypatch.setattr("kostream.mal.time.sleep", lambda *_: None)

    updated = sync_catalog_episode_titles(
        catalog_path,
        limit=10,
        skip_mal_ids={1},
    )
    assert updated == 1
    assert calls == [2]


def test_api_sync_index_list_and_update(tmp_path):
    from kostream.app import create_app

    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(id="mal-5", enabled=True, source="mal", mal_id=5, title="API Show"),
            ]
        ),
        catalog_path,
    )
    anime_index = tmp_path / "animes.json"
    save_anime_index({"5": {"skip_anime_sync": False, "title": "API Show"}}, anime_index)

    app = create_app(
        catalog_path=catalog_path,
        media_root=tmp_path / "anime",
        manga_root=tmp_path / "manga",
        manga_catalog_path=tmp_path / "manga.json",
        requests_path=tmp_path / "requests.json",
    )
    app.config["ANIME_SYNC_INDEX_PATH"] = anime_index
    app.config["MANGA_SYNC_INDEX_PATH"] = tmp_path / "mangas.json"
    client = app.test_client()

    resp = client.get("/api/sync-index?section=anime_sync")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert any(e["mal_id"] == 5 for e in data["entries"])

    resp2 = client.post(
        "/api/sync-index",
        json={"section": "anime_sync", "mal_id": 5, "skip": True},
    )
    assert resp2.status_code == 200
    assert resp2.get_json()["skip"] is True
    assert load_anime_index(anime_index)["5"]["skip_anime_sync"] is True
