"""Per-user progress isolation."""

from __future__ import annotations

import json
import time
from pathlib import Path

from kostream.app import create_app
from kostream.catalog import CatalogEntry, CatalogState, save_catalog
from kostream.models import Episode, Show
from kostream.user_paths import user_data_paths
from kostream.watch_progress import load_completed

from conftest import add_test_user, bootstrap_test_users, login_client


def _two_user_app(tmp_path: Path):
    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="demo-show",
                    enabled=True,
                    source="local",
                    folder="Demo Show",
                    title="Demo Show",
                )
            ]
        ),
        catalog,
    )
    media = tmp_path / "media" / "shows"
    show_dir = media / "Demo Show"
    show_dir.mkdir(parents=True)
    (show_dir / "S01E01.mp4").write_bytes(b"x")
    (show_dir / "S01E02.mp4").write_bytes(b"x")

    users_path = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users_path, "usera", "passa")
    add_test_user(users_path, "userb", "passb")

    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users_path,
        user_data_base=user_data,
    )
    return app, user_data


def test_episode_complete_isolated_between_users(tmp_path: Path):
    app, user_data = _two_user_app(tmp_path)
    client = app.test_client()

    login_client(client, "usera", "passa")
    resp = client.post(
        "/api/episodes/complete",
        json={"show_id": "demo-show", "episode_id": "demo-show-s01e01"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    paths_a = user_data_paths("u_usera", user_data)
    paths_b = user_data_paths("u_userb", user_data)
    assert load_completed(paths_a["completed"]).get("demo-show") == 1
    assert not paths_b["completed"].exists() or load_completed(paths_b["completed"]) == {}

    login_client(client, "userb", "passb")
    resp_b = client.post(
        "/api/episodes/complete",
        json={"show_id": "demo-show", "episode_id": "demo-show-s01e02"},
    )
    assert resp_b.status_code == 200

    assert load_completed(paths_a["completed"]).get("demo-show") == 1
    assert load_completed(paths_b["completed"]).get("demo-show") == 2


def test_anime_sync_does_not_touch_other_users_completed(tmp_path: Path, monkeypatch):
    app, user_data = _two_user_app(tmp_path)
    paths_a = user_data_paths("u_usera", user_data)
    paths_b = user_data_paths("u_userb", user_data)
    paths_a["completed"].parent.mkdir(parents=True, exist_ok=True)
    paths_a["completed"].write_text(
        json.dumps({"demo-show": 1}),
        encoding="utf-8",
    )

    show = Show(
        id="demo-show",
        title="Demo Show",
        description="",
        mal_id=42,
        episodes=[
            Episode("demo-show-s01e01", "demo-show", 1, 1, "Ep 1", "S01E01.mp4"),
            Episode("demo-show-s01e02", "demo-show", 1, 2, "Ep 2", "S01E02.mp4"),
        ],
    )

    def fake_reconcile(show, *, completed_path=None, mal_cfg=None, user_id=None):
        from kostream.watch_progress import load_completed, save_completed

        assert completed_path is not None
        assert user_id == "u_userb"
        data = load_completed(completed_path)
        data[show.id] = 2
        save_completed(completed_path, data)
        return 2

    monkeypatch.setattr("kostream.watch_progress.reconcile_anime_progress", fake_reconcile)
    monkeypatch.setattr("kostream.library.scan_library", lambda *a, **k: [show])
    monkeypatch.setattr("kostream.sync_jobs.sync_animelist_to_catalog", lambda *a, **k: 1)
    monkeypatch.setattr("kostream.sync_jobs.enrich_catalog_mal_details", lambda *a, **k: 0)
    monkeypatch.setattr("kostream.requests_store.clear_fulfilled_requests", lambda **k: 0)
    monkeypatch.setattr("kostream.sync_index.refresh_anime_index", lambda **k: None)
    monkeypatch.setattr("kostream.app.mal_is_connected", lambda *_a, **_k: True)
    monkeypatch.setenv("MAL_CLIENT_ID", "a" * 32)
    monkeypatch.setenv("MAL_CLIENT_SECRET", "b" * 32)

    client = app.test_client()
    login_client(client, "userb", "passb")
    resp = client.post("/api/mal/sync/animes")
    assert resp.status_code == 200

    deadline = time.time() + 2.0
    while time.time() < deadline:
        status = client.get("/api/mal/sync/status").get_json()
        if status.get("status") != "running":
            break
        time.sleep(0.02)

    # User B sync should only update B's completed file
    assert load_completed(paths_b["completed"]).get("demo-show") == 2
    assert load_completed(paths_a["completed"]).get("demo-show") == 1


def test_mal_connect_isolated_between_users(tmp_path: Path, monkeypatch):
    """User A tokens do not make user B connected; disconnect A leaves B intact."""
    from kostream import mal as mal_mod
    from kostream.mal import MalTokens, is_connected, save_tokens, token_path

    app, _user_data = _two_user_app(tmp_path)
    mal_dir = tmp_path / "mal"
    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", mal_dir)
    monkeypatch.setenv("MAL_CLIENT_ID", "a" * 32)
    monkeypatch.setenv("MAL_CLIENT_SECRET", "b" * 32)

    save_tokens(
        "u_usera",
        MalTokens("a-tok", "a-ref", expires_at=9_999_999_999, username="AliceMAL"),
    )
    save_tokens(
        "u_userb",
        MalTokens("b-tok", "b-ref", expires_at=9_999_999_999, username="BobMAL"),
    )
    assert token_path("u_usera") != token_path("u_userb")
    assert is_connected("u_usera")
    assert is_connected("u_userb")

    client = app.test_client()
    login_client(client, "usera", "passa")
    home_a = client.get("/")
    assert home_a.status_code == 200
    assert b"AliceMAL" in home_a.data
    assert b"BobMAL" not in home_a.data

    login_client(client, "userb", "passb")
    home_b = client.get("/")
    assert home_b.status_code == 200
    assert b"BobMAL" in home_b.data
    assert b"AliceMAL" not in home_b.data

    login_client(client, "usera", "passa")
    disc = client.post("/api/mal/disconnect")
    assert disc.status_code == 200
    assert disc.get_json()["ok"] is True
    assert not is_connected("u_usera")
    assert is_connected("u_userb")

    login_client(client, "userb", "passb")
    home_b2 = client.get("/")
    assert b"BobMAL" in home_b2.data
