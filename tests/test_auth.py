"""Login gate and session auth."""

from __future__ import annotations

from pathlib import Path

import pytest

from kostream.app import create_app
from kostream.users import load_users, set_restricted

from conftest import bootstrap_test_users, login_client


def _app(tmp_path: Path, *, bootstrapped: bool = True):
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    if bootstrapped:
        bootstrap_test_users(users, "testuser", "testpass")
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    return (
        create_app(
            media_root=media,
            catalog_path=catalog,
            users_path=users,
            user_data_base=user_data,
        ),
        users,
    )


def test_login_ok(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    resp = login_client(client)
    assert resp.status_code == 302
    assert resp.location.endswith("/")
    with client.session_transaction() as sess:
        assert sess.get("user_id") == "u_testuser"


def test_login_honors_relative_next(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    resp = client.post(
        "/login?next=/catalog",
        data={"username": "testuser", "password": "testpass"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.location.endswith("/catalog")


@pytest.mark.parametrize(
    "evil_next",
    [
        "https://evil.example/phish",
        "http://evil.example/",
        "//evil.example/phish",
        "\\\\evil.example",
        "https://evil.example",
    ],
)
def test_login_rejects_external_next(tmp_path: Path, evil_next: str):
    app, _users = _app(tmp_path)
    client = app.test_client()
    resp = client.post(
        f"/login?next={evil_next}",
        data={"username": "testuser", "password": "testpass"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = resp.location or ""
    assert "evil.example" not in loc
    assert loc.endswith("/")


def test_login_fail(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    resp = client.post(
        "/login",
        data={"username": "testuser", "password": "wrong"},
    )
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


def test_restricted_user_cannot_login(tmp_path: Path):
    app, users_path = _app(tmp_path)
    users = load_users(users_path)
    set_restricted(users_path, users[0].id, restricted=True)
    client = app.test_client()
    resp = login_client(client)
    assert resp.status_code == 200
    assert b"This account is restricted" in resp.data


def test_lockout_after_three_failed_attempts(tmp_path: Path):
    app, users_path = _app(tmp_path)
    client = app.test_client()
    for _ in range(2):
        resp = client.post(
            "/login",
            data={"username": "testuser", "password": "wrong"},
        )
        assert resp.status_code == 200
        assert b"Invalid username or password" in resp.data
    resp = client.post(
        "/login",
        data={"username": "testuser", "password": "wrong"},
    )
    assert resp.status_code == 200
    assert b"too many failed login attempts" in resp.data
    assert load_users(users_path)[0].restricted is True
    resp = login_client(client)
    assert resp.status_code == 200
    assert b"This account is restricted" in resp.data


def test_logout(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.location
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_gate_redirects_unauthenticated(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_unbootstrapped_only_login_works(tmp_path: Path):
    app, _users = _app(tmp_path, bootstrapped=False)
    client = app.test_client()
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 302
    assert "/login" in home.location

    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert b"ko-stream accounts bootstrap" in login_page.data


def test_unbootstrapped_post_login_rejected(tmp_path: Path):
    app, users_path = _app(tmp_path, bootstrapped=False)
    client = app.test_client()
    resp = client.post(
        "/login",
        data={"username": "nobody", "password": "x"},
    )
    assert resp.status_code == 200
    assert b"No accounts configured" in resp.data
    assert not users_path.exists()


def test_static_allowed_without_login(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    resp = client.get("/static/style.css", follow_redirects=False)
    assert resp.status_code == 200


def test_favicon_allowed_without_login(tmp_path: Path):
    app, _users = _app(tmp_path)
    client = app.test_client()
    resp = client.get("/favicon.ico", follow_redirects=False)
    assert resp.status_code == 200
