"""Four-way MAL / MangaDex sync jobs."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import kostream.sync_jobs as sync_jobs
from kostream.app import create_app
from kostream.mal import MalConfig, MalTokens

_MAL_ID = "a" * 32
_MAL_SECRET = "b" * 32


def _cfg() -> MalConfig:
    return MalConfig(
        client_id=_MAL_ID,
        client_secret=_MAL_SECRET,
        redirect_uri="http://127.0.0.1:5000/auth/mal/callback",
    )


def _reset_job(monkeypatch):
    monkeypatch.setattr(sync_jobs, "_job", None)


def _wait_done(timeout: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = sync_jobs.get_sync_job()
        if job.status != "running":
            return job
        time.sleep(0.02)
    return sync_jobs.get_sync_job()


def test_anime_sync_skips_manga_and_titles(tmp_path, monkeypatch):
    _reset_job(monkeypatch)
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")

    calls: list[str] = []

    monkeypatch.setattr(
        sync_jobs,
        "sync_animelist_to_catalog",
        lambda *a, **k: calls.append("anime") or 3,
    )
    monkeypatch.setattr(
        sync_jobs,
        "sync_mangalist_to_catalog",
        lambda *a, **k: calls.append("manga") or 2,
    )
    monkeypatch.setattr(
        sync_jobs,
        "enrich_catalog_mal_details",
        lambda *a, **k: calls.append("enrich") or 1,
    )
    monkeypatch.setattr(
        sync_jobs,
        "sync_catalog_episode_titles",
        lambda *a, **k: calls.append("episode_titles") or 9,
    )
    monkeypatch.setattr(
        sync_jobs,
        "sync_catalog_chapter_titles",
        lambda *a, **k: calls.append("chapter_titles")
        or sync_jobs.ChapterTitleSyncResult(updated=9),
    )
    monkeypatch.setattr("kostream.library.scan_library", lambda *a, **k: [])
    monkeypatch.setattr(
        "kostream.requests_store.clear_fulfilled_requests",
        lambda **k: 0,
    )

    job = sync_jobs.start_anime_sync(
        _cfg(),
        catalog,
        user_id="u_test",
        media_root=tmp_path / "anime",
        requests_path=tmp_path / "requests.json",
    )
    assert job.kind == "animes"

    done = _wait_done()
    assert done.status == "done"
    assert done.kind == "animes"
    assert done.synced == 3
    assert done.manga_synced == 0
    assert done.enriched == 1
    assert done.episode_titles == 0
    assert done.chapter_titles == 0
    assert calls == ["anime", "enrich"]
    assert "Animes synced" in (done.message or "")


def test_manga_sync_skips_anime_and_titles(tmp_path, monkeypatch):
    _reset_job(monkeypatch)
    calls: list[str] = []

    monkeypatch.setattr(
        sync_jobs,
        "sync_animelist_to_catalog",
        lambda *a, **k: calls.append("anime") or 1,
    )
    monkeypatch.setattr(
        sync_jobs,
        "sync_mangalist_to_catalog",
        lambda *a, **k: calls.append("manga") or 5,
    )
    monkeypatch.setattr(
        sync_jobs,
        "enrich_catalog_mal_details",
        lambda *a, **k: calls.append("enrich") or 1,
    )
    monkeypatch.setattr(
        sync_jobs,
        "sync_catalog_chapter_titles",
        lambda *a, **k: calls.append("chapter_titles")
        or sync_jobs.ChapterTitleSyncResult(updated=9),
    )
    monkeypatch.setattr(
        "kostream.requests_store.clear_fulfilled_requests",
        lambda **k: 0,
    )

    job = sync_jobs.start_manga_sync(
        _cfg(),
        user_id="u_test",
        manga_catalog_path=tmp_path / "manga.json",
        manga_media_root=tmp_path / "manga",
        requests_path=tmp_path / "requests.json",
    )
    assert job.kind == "mangas"
    done = _wait_done()
    assert done.status == "done"
    assert done.manga_synced == 5
    assert done.synced == 0
    assert done.enriched == 0
    assert calls == ["manga"]
    assert "Mangas synced" in (done.message or "")


def test_anime_title_sync_only(tmp_path, monkeypatch):
    _reset_job(monkeypatch)
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        sync_jobs,
        "sync_animelist_to_catalog",
        lambda *a, **k: calls.append("anime") or 1,
    )
    monkeypatch.setattr(
        sync_jobs,
        "sync_catalog_episode_titles",
        lambda *a, **k: calls.append("episode_titles") or 4,
    )
    monkeypatch.setattr(
        sync_jobs,
        "sync_catalog_chapter_titles",
        lambda *a, **k: calls.append("chapter_titles")
        or sync_jobs.ChapterTitleSyncResult(updated=5),
    )

    job = sync_jobs.start_anime_title_sync(catalog)
    assert job.kind == "anime_titles"
    done = _wait_done()
    assert done.status == "done"
    assert done.episode_titles == 4
    assert done.chapter_titles == 0
    assert calls == ["episode_titles"]
    assert "Anime titles synced" in (done.message or "")


def test_chapter_title_sync_only(tmp_path, monkeypatch):
    _reset_job(monkeypatch)
    calls: list[str] = []

    monkeypatch.setattr(
        sync_jobs,
        "sync_catalog_episode_titles",
        lambda *a, **k: calls.append("episode_titles") or 4,
    )
    monkeypatch.setattr(
        sync_jobs,
        "sync_catalog_chapter_titles",
        lambda *a, **k: (
            calls.append("chapter_titles")
            or sync_jobs.ChapterTitleSyncResult(updated=5, attempted=5)
        ),
    )

    job = sync_jobs.start_chapter_title_sync(
        manga_catalog_path=tmp_path / "manga.json",
        manga_media_root=tmp_path / "manga",
    )
    assert job.kind == "chapter_titles"
    done = _wait_done()
    assert done.status == "done"
    assert done.chapter_titles == 5
    assert done.episode_titles == 0
    assert calls == ["chapter_titles"]
    assert "Chapter titles synced" in (done.message or "")


def test_global_lock_blocks_second_job(tmp_path, monkeypatch):
    _reset_job(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def slow_anime(*a, **k):
        started.set()
        release.wait(timeout=2.0)
        return 1

    monkeypatch.setattr(sync_jobs, "sync_animelist_to_catalog", slow_anime)
    monkeypatch.setattr(sync_jobs, "enrich_catalog_mal_details", lambda *a, **k: 0)
    monkeypatch.setattr("kostream.library.scan_library", lambda *a, **k: [])
    monkeypatch.setattr(
        "kostream.requests_store.clear_fulfilled_requests",
        lambda **k: 0,
    )
    monkeypatch.setattr(sync_jobs, "sync_catalog_episode_titles", lambda *a, **k: 99)

    catalog = tmp_path / "c.json"
    catalog.write_text('{"shows":[]}', encoding="utf-8")

    first = sync_jobs.start_anime_sync(_cfg(), catalog, user_id="u_test")
    assert started.wait(timeout=1.0)
    second = sync_jobs.start_anime_title_sync(catalog)
    assert second.kind == "animes"
    assert second.status == "running"
    release.set()
    done = _wait_done()
    assert done.kind == "animes"
    assert done.episode_titles == 0


def test_api_mal_sync_endpoints_require_connection(tmp_path, monkeypatch):
    _reset_job(monkeypatch)
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    from conftest import bootstrap_test_users, login_client

    bootstrap_test_users(users)
    monkeypatch.setenv("MAL_CLIENT_ID", _MAL_ID)
    monkeypatch.setenv("MAL_CLIENT_SECRET", _MAL_SECRET)
    monkeypatch.setattr("kostream.app.mal_is_connected", lambda *_a, **_k: False)
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)

    for path in (
        "/api/mal/sync/animes",
        "/api/mal/sync/mangas",
        "/api/mal/sync/anime-titles",
        "/api/mal/sync/chapter-titles",
    ):
        resp = client.post(path)
        assert resp.status_code == 401, path

    status = client.get("/api/mal/sync/status")
    assert status.status_code == 200
    body = status.get_json()
    assert "running" in body
    assert "kind" in body


def test_catalog_shows_four_sync_buttons_when_connected(tmp_path, monkeypatch):
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    from conftest import bootstrap_test_users, login_client

    bootstrap_test_users(users)
    monkeypatch.setenv("MAL_CLIENT_ID", _MAL_ID)
    monkeypatch.setenv("MAL_CLIENT_SECRET", _MAL_SECRET)
    monkeypatch.setattr("kostream.app.mal_is_connected", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "kostream.app.mal_load_tokens",
        lambda *_a, **_k: MalTokens(
            access_token="t",
            refresh_token="r",
            expires_at=time.time() + 3600,
            username="tester",
        ),
    )
    monkeypatch.setattr("kostream.app.format_last_sync_label", lambda *_a, **_k: None)

    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)
    resp = client.get("/catalog")
    assert resp.status_code == 200
    assert b"Sync animes" in resp.data
    assert b"Sync mangas" in resp.data
    assert b"Sync anime titles" in resp.data
    assert b"Sync chapter titles" in resp.data
    assert b'id="mal-sync-animes"' in resp.data
    assert b'id="mal-sync-mangas"' in resp.data
    assert b'id="mal-sync-anime-titles"' in resp.data
    assert b'id="mal-sync-chapter-titles"' in resp.data
    assert b"Sync lists" not in resp.data
    assert b"Sync titles" not in resp.data
