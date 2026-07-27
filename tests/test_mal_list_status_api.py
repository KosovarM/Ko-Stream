"""MAL anime list-status update from show overview."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from kostream.app import create_app
from kostream.catalog import CatalogEntry, CatalogState, save_catalog
from kostream.mal import (
    MalTokens,
    get_anime_list_row,
    save_tokens,
    update_anime_list_status,
)
from kostream.users import find_user_by_username, load_users

from conftest import bootstrap_test_users, login_client


def _app_with_mal_show(tmp_path: Path, monkeypatch, *, with_mal_id: bool = True):
    from kostream import mal as mal_mod

    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="demo-show",
                    enabled=True,
                    source="mal",
                    title="Demo Show",
                    mal_id=21 if with_mal_id else None,
                )
            ]
        ),
        catalog,
    )
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)

    mal_dir = tmp_path / "mal"
    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", mal_dir)
    monkeypatch.setenv("MAL_CLIENT_ID", "a" * 32)
    monkeypatch.setenv("MAL_CLIENT_SECRET", "b" * 32)

    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )
    return app, users, mal_mod


def _connect_mal(users_path: Path, username: str = "testuser") -> str:
    user = find_user_by_username(load_users(users_path), username)
    assert user is not None
    save_tokens(
        user.id,
        MalTokens("tok", "ref", expires_at=9_999_999_999, username="TestMAL"),
    )
    return user.id


def test_update_anime_list_status_patches_and_updates_overlay(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path / "mal")
    save_tokens(
        "u_test",
        MalTokens("tok", "ref", expires_at=9_999_999_999, username="TestMAL"),
    )
    sent: list[tuple[str, dict[str, str], str]] = []

    def fake_api(token, path, form, method="POST"):
        sent.append((path, dict(form), method))
        return None

    monkeypatch.setattr(mal_mod, "get_valid_access_token", lambda cfg, user_id: "tok")
    monkeypatch.setattr(mal_mod, "_api_form_raw", fake_api)

    cfg = MagicMock()
    row = update_anime_list_status(cfg, 21, "on_hold", user_id="u_test")
    assert row["list_status"] == "on_hold"
    assert get_anime_list_row("u_test", 21)["list_status"] == "on_hold"
    assert sent == [("/anime/21/my_list_status", {"status": "on_hold"}, "PATCH")]


def test_update_anime_list_status_rejects_invalid(monkeypatch, tmp_path):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path / "mal")
    monkeypatch.setattr(mal_mod, "get_valid_access_token", lambda cfg, user_id: "tok")
    called = []
    monkeypatch.setattr(
        mal_mod, "_api_form_raw", lambda *a, **k: called.append(True)
    )
    cfg = MagicMock()
    try:
        update_anime_list_status(cfg, 21, "rewatching", user_id="u_test")
        assert False, "expected MalError"
    except mal_mod.MalError as exc:
        assert "Invalid" in str(exc)
    assert not called


def test_api_show_mal_status_updates_overlay(tmp_path, monkeypatch):
    app, users, mal_mod = _app_with_mal_show(tmp_path, monkeypatch)
    uid = _connect_mal(users)
    sent: list[dict[str, str]] = []

    monkeypatch.setattr(mal_mod, "get_valid_access_token", lambda cfg, user_id: "tok")

    def fake_api(token, path, form, method="POST"):
        sent.append(dict(form))
        return None

    monkeypatch.setattr(mal_mod, "_api_form_raw", fake_api)

    client = app.test_client()
    login_client(client)
    resp = client.post(
        "/api/show/mal-status",
        json={"show_id": "demo-show", "status": "watching"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["status"] == "watching"
    assert data["mal_id"] == 21
    assert sent == [{"status": "watching"}]
    assert get_anime_list_row(uid, 21)["list_status"] == "watching"


def test_api_show_mal_status_requires_mal_connection(tmp_path, monkeypatch):
    app, _users, _mal_mod = _app_with_mal_show(tmp_path, monkeypatch)
    client = app.test_client()
    login_client(client)
    resp = client.post(
        "/api/show/mal-status",
        json={"show_id": "demo-show", "status": "completed"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert "MAL" in resp.get_json()["error"]


def test_api_show_mal_status_requires_login(tmp_path, monkeypatch):
    app, users, _mal_mod = _app_with_mal_show(tmp_path, monkeypatch)
    _connect_mal(users)
    client = app.test_client()
    resp = client.post(
        "/api/show/mal-status",
        json={"show_id": "demo-show", "status": "dropped"},
        follow_redirects=False,
    )
    # Global login gate redirects unauthenticated requests.
    assert resp.status_code in (302, 401)


def test_api_show_mal_status_rejects_invalid_status(tmp_path, monkeypatch):
    app, users, mal_mod = _app_with_mal_show(tmp_path, monkeypatch)
    _connect_mal(users)
    monkeypatch.setattr(mal_mod, "get_valid_access_token", lambda cfg, user_id: "tok")
    monkeypatch.setattr(mal_mod, "_api_form_raw", lambda *a, **k: None)

    client = app.test_client()
    login_client(client)
    resp = client.post(
        "/api/show/mal-status",
        json={"show_id": "demo-show", "status": "rewatching"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_show_page_includes_status_control_when_connected(tmp_path, monkeypatch):
    app, users, mal_mod = _app_with_mal_show(tmp_path, monkeypatch)
    uid = _connect_mal(users)
    mal_mod.upsert_anime_list_row(uid, 21, list_status="plan_to_watch")

    client = app.test_client()
    login_client(client)
    resp = client.get("/show/demo-show")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert 'id="mal-list-status-select"' in html
    assert "MAL list status" in html
    assert "Planned to Watch" in html
    assert 'value="plan_to_watch"' in html


def test_show_page_hides_control_without_mal_id(tmp_path, monkeypatch):
    app, users, _mal_mod = _app_with_mal_show(tmp_path, monkeypatch, with_mal_id=False)
    _connect_mal(users)
    client = app.test_client()
    login_client(client)
    resp = client.get("/show/demo-show")
    assert resp.status_code == 200
    assert b'id="mal-list-status-select"' not in resp.data
    assert b"MAL list status" not in resp.data


def test_show_page_hint_when_mal_not_connected(tmp_path, monkeypatch):
    app, _users, _mal_mod = _app_with_mal_show(tmp_path, monkeypatch)
    client = app.test_client()
    login_client(client)
    resp = client.get("/show/demo-show")
    assert resp.status_code == 200
    assert b'id="mal-list-status-select"' not in resp.data
    assert b"Connect MAL" in resp.data
