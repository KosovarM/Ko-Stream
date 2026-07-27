"""Basic CSRF protection (S2)."""

from __future__ import annotations

from pathlib import Path

from kostream.app import create_app

from conftest import add_test_user, bootstrap_test_users


def _app(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOSTREAM_CSRF", "1")
    monkeypatch.setenv("KOSTREAM_SECRET_KEY", "test-secret-key-for-csrf")
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    add_test_user(users, "second", "secondpass", role="user")
    return create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )


def _csrf_login(client, username: str = "testuser", password: str = "testpass"):
    client.get("/login")
    with client.session_transaction() as sess:
        token = sess["csrf_token"]
    return client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": token,
        },
        follow_redirects=False,
    )


def _logged_in_client(app):
    client = app.test_client()
    _csrf_login(client)
    return client


def test_csrf_meta_present(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = _logged_in_client(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'name="csrf-token"' in resp.data


def test_post_without_csrf_rejected(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = _logged_in_client(app)
    client.get("/")  # establish session + token
    resp = client.post("/api/catalog/toggle", json={"id": "x", "enabled": True})
    assert resp.status_code == 403
    assert resp.get_json()["ok"] is False


def test_post_with_csrf_header_ok(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = _logged_in_client(app)
    with client.session_transaction() as sess:
        sess["csrf_token"] = "fixed-csrf-token"
    resp = client.post(
        "/api/catalog/toggle",
        json={"id": "missing", "enabled": True},
        headers={"X-CSRF-Token": "fixed-csrf-token"},
    )
    # Toggle of unknown id still returns 200 with ok (toggle_entry no-ops / keeps state)
    assert resp.status_code != 403


def test_login_get_sets_csrf_cookie_and_form_token(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "session=" in (resp.headers.get("Set-Cookie") or "")
    assert "SameSite=Lax" in (resp.headers.get("Set-Cookie") or "")
    assert b'name="csrf_token"' in resp.data
    assert b"no-store" in resp.headers.get("Cache-Control", "").encode()
    with client.session_transaction() as sess:
        assert sess.get("csrf_token")


def test_login_post_without_csrf_rejected(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = app.test_client()
    client.get("/login")
    resp = client.post(
        "/login",
        data={"username": "second", "password": "secondpass"},
    )
    # Soft-fail: do not authenticate; re-establish CSRF for retry (no bare 403).
    assert resp.status_code == 200
    assert b"Session expired" in resp.data
    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert sess.get("csrf_token")


def test_login_post_with_csrf_succeeds(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = app.test_client()
    resp = _csrf_login(client, "second", "secondpass")
    assert resp.status_code == 302
    assert resp.location.endswith("/")
    with client.session_transaction() as sess:
        assert sess.get("user_id") == "u_second"
