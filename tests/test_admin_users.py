"""Admin users UI and master-only access."""

from __future__ import annotations

from pathlib import Path

from kostream.app import create_app
from kostream.users import find_user_by_username, load_users, verify_password

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
    add_test_user(users, "manager1", "mgrpass", role="manager")
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )
    return app, users


def test_master_admin_page(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.get("/admin/users")
    assert resp.status_code == 200
    assert b"Users" in resp.data
    assert b"Create user" in resp.data
    assert b"Admin" in resp.data


def test_non_master_cannot_access_admin(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    resp = client.get("/admin/users", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.location.endswith("/")
    home = client.get("/")
    assert b">Admin<" not in home.data and b"/admin/users" not in home.data


def test_manager_cannot_access_admin(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    login_client(client, "manager1", "mgrpass")
    resp = client.get("/admin/users", follow_redirects=False)
    assert resp.status_code == 302


def test_create_user_via_admin(tmp_path: Path):
    app, users_path = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.post(
        "/admin/users",
        data={"username": "bob", "password": "bobpass", "role": "user"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    bob = find_user_by_username(load_users(users_path), "bob")
    assert bob is not None
    assert bob.role == "user"
    assert verify_password(bob, "bobpass")


def test_cannot_create_second_master_via_admin(tmp_path: Path):
    app, users_path = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.post(
        "/admin/users",
        data={"username": "other", "password": "x", "role": "master"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"master account already exists" in resp.data
    assert find_user_by_username(load_users(users_path), "other") is None


def test_restrict_and_unrestrict(tmp_path: Path):
    app, users_path = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    sister = find_user_by_username(load_users(users_path), "sister")
    assert sister is not None

    from kostream.mal import mal_user_dir, save_tokens, is_connected, MalTokens
    import time

    save_tokens(
        sister.id,
        MalTokens(
            access_token="a",
            refresh_token="r",
            expires_at=time.time() + 3600,
            username="sister_mal",
        ),
    )
    (mal_user_dir(sister.id) / "pending_oauth.json").write_text(
        '{"state":"x"}', encoding="utf-8"
    )
    assert is_connected(sister.id)

    resp = client.post(
        f"/admin/users/{sister.id}/restrict",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    restricted = find_user_by_username(load_users(users_path), "sister")
    assert restricted is not None
    assert restricted.restricted is True
    assert not is_connected(sister.id)
    assert not (mal_user_dir(sister.id) / "pending_oauth.json").exists()

    client.post(f"/admin/users/{sister.id}/unrestrict")
    restored = find_user_by_username(load_users(users_path), "sister")
    assert restored is not None
    assert restored.restricted is False
    assert restored.failed_login_attempts == 0
    # Unrestrict does not restore MAL tokens (user must reconnect).
    assert not is_connected(sister.id)


def test_reset_password(tmp_path: Path):
    app, users_path = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    sister = find_user_by_username(load_users(users_path), "sister")
    assert sister is not None
    resp = client.post(
        f"/admin/users/{sister.id}/reset-password",
        data={"password": "newpass99"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    updated = find_user_by_username(load_users(users_path), "sister")
    assert updated is not None
    assert verify_password(updated, "newpass99")
    assert not verify_password(updated, "sispass")


def test_non_master_catalog_toggle_forbidden(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    resp = client.post("/api/catalog/toggle", json={"id": "x", "enabled": True})
    assert resp.status_code == 403
    assert resp.get_json()["ok"] is False


def test_users_reset_password_unit(tmp_path: Path):
    from kostream.users import create_user, reset_password

    path = tmp_path / "users.json"
    user = create_user(path, username="bob", password="old")
    reset_password(path, user.id, "fresh")
    loaded = load_users(path)[0]
    assert verify_password(loaded, "fresh")
