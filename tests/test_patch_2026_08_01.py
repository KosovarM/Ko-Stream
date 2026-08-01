"""Focused tests for 01.08.2026 patch (skip chrome, sync queue, roles, weekly)."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import kostream.sync_jobs as sync_jobs
from kostream.app import create_app
from kostream.catalog import CatalogEntry, CatalogState, save_catalog
from kostream.models import Episode, Show
from kostream.sync_index import aniskip_status
from kostream.weekly_sync import _next_sunday_0800

from conftest import add_test_user, bootstrap_test_users, login_client


def _app(tmp_path: Path):
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    add_test_user(users, "sister", "sispass", role="user")
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )
    return app, users, user_data


def test_skip_buttons_idle_css_and_position():
    css = Path("src/kostream/static/style.css").read_text(encoding="utf-8")
    assert "bottom: 25%" in css
    assert ".player-wrap.has-native-chrome.is-idle .player-skip-stack" in css
    # Idle hides skip chrome (opacity 0), not keeps it visible.
    idle_block = css.split(".player-wrap.has-native-chrome.is-idle .player-skip-stack")[1][:200]
    assert "opacity: 0" in idle_block


def test_enqueue_sync_runs_after_current(monkeypatch):
    monkeypatch.setattr(sync_jobs, "_job", None)
    monkeypatch.setattr(sync_jobs, "_queue", [])
    order: list[str] = []
    gate = threading.Event()

    def slow_anime():
        job = sync_jobs._begin_job("animes", "list", "slow")
        assert job is not None

        def runner():
            order.append("a-start")
            gate.wait(timeout=2)
            order.append("a-end")
            sync_jobs._finish_ok(job, "anime done")

        threading.Thread(target=runner, daemon=True).start()
        return job

    def fast_titles():
        job = sync_jobs._begin_job("anime_titles", "episode_titles", "titles")
        assert job is not None

        def runner():
            order.append("t-start")
            sync_jobs._finish_ok(job, "titles done")

        threading.Thread(target=runner, daemon=True).start()
        return job

    job1, queued1 = sync_jobs.enqueue_sync(slow_anime)
    assert queued1 is False
    assert job1.status == "running"
    job2, queued2 = sync_jobs.enqueue_sync(fast_titles)
    assert queued2 is True
    assert job2.kind == "animes"
    gate.set()
    deadline = time.time() + 2
    while time.time() < deadline and "t-start" not in order:
        time.sleep(0.02)
    assert order == ["a-start", "a-end", "t-start"]


def test_sync_api_forbidden_for_normal_user(tmp_path: Path):
    app, _, _ = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    resp = client.post("/api/mal/sync/animes")
    assert resp.status_code == 403


def test_catalog_hides_sync_for_normal_user(tmp_path: Path, monkeypatch):
    app, _, _ = _app(tmp_path)
    monkeypatch.setenv("MAL_CLIENT_ID", "a" * 32)
    monkeypatch.setenv("MAL_CLIENT_SECRET", "b" * 32)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    resp = client.get("/catalog")
    assert resp.status_code == 200
    assert b'id="mal-sync-animes"' not in resp.data
    assert b'id="sync-index-open"' not in resp.data
    # Connect CTA still present when not connected
    assert b"Connect MyAnimeList" in resp.data or b"mal-disconnect" in resp.data


def test_aniskip_status_complete_when_cached(tmp_path: Path, monkeypatch):
    from kostream import aniskip

    root = tmp_path / "aniskip"
    monkeypatch.setattr(aniskip, "ANISKIP_DIR", root)
    aniskip._store_episode(1, 1, {"op": {"start": 0, "end": 90}}, root=root)
    aniskip._store_episode(1, 2, {}, root=root)
    show = Show(
        id="mal-1",
        title="T",
        description="",
        mal_id=1,
        episodes=[
            Episode(id="e1", show_id="mal-1", season=1, number=1, title="1", filename="1.mkv"),
            Episode(id="e2", show_id="mal-1", season=1, number=2, title="2", filename="2.mkv"),
        ],
    )
    ok, hint = aniskip_status(show, 1)
    assert ok is True
    assert hint == "Complete"


def test_next_sunday_0800_from_saturday():
    sat = datetime(2026, 8, 1, 15, 0, 0)  # Saturday
    nxt = _next_sunday_0800(sat)
    assert nxt == datetime(2026, 8, 2, 8, 0, 0)


def test_next_sunday_0800_after_window_rolls_week():
    sun_late = datetime(2026, 8, 2, 9, 0, 0)
    nxt = _next_sunday_0800(sun_late)
    assert nxt == datetime(2026, 8, 9, 8, 0, 0)
    assert nxt - sun_late >= timedelta(days=6)


def test_sync_index_aniskip_section(tmp_path: Path):
    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[CatalogEntry(id="mal-9", enabled=True, source="mal", mal_id=9, title="Nine")]
        ),
        catalog_path,
    )
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    app = create_app(
        catalog_path=catalog_path,
        media_root=tmp_path / "anime",
        manga_root=tmp_path / "manga",
        manga_catalog_path=tmp_path / "manga.json",
        requests_path=tmp_path / "requests.json",
        users_path=users,
        user_data_base=user_data,
    )
    app.config["ANIME_SYNC_INDEX_PATH"] = tmp_path / "animes.json"
    client = app.test_client()
    login_client(client)
    resp = client.get("/api/sync-index?section=aniskip")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["section"] == "aniskip"
