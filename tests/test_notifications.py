"""Notifications store + API: fulfill notifies requester; list/mark; isolation."""

from __future__ import annotations

from pathlib import Path

from kostream.app import create_app
from kostream.notifications import (
    TYPE_REQUEST_FULFILLED,
    add_notification,
    href_for_request,
    list_notifications,
    load_notifications,
    mark_all_read,
    mark_read,
    notifications_path,
    notify_request_fulfilled,
)

from conftest import add_test_user, bootstrap_test_users, login_client


def _app(tmp_path: Path):
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    requests = tmp_path / "requests.json"
    bootstrap_test_users(users)
    add_test_user(users, "manager1", "mgrpass", role="manager")
    add_test_user(users, "sister", "sispass", role="user")
    add_test_user(users, "brother", "bropass", role="user")
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
        requests_path=requests,
    )
    return app, user_data, requests


def test_href_for_request_kinds():
    assert href_for_request("series", "mal-1") == "/show/mal-1"
    assert href_for_request("movie", "mal-2") == "/show/mal-2"
    assert href_for_request("special", "mal-3") == "/show/mal-3"
    assert href_for_request("manga", "mal-4") == "/manga?open=mal-4"
    assert href_for_request("manhwa", "mal-5") == "/manhwa?open=mal-5"
    assert href_for_request("series", "") is None


def test_notify_request_fulfilled_writes_store(tmp_path: Path):
    base = tmp_path / "user_data"
    entry = {
        "id": "series:mal-10",
        "kind": "series",
        "media_id": "mal-10",
        "title": "Demo Show",
        "requester_id": "u_sister",
    }
    note = notify_request_fulfilled(entry, base=base)
    assert note is not None
    assert note["type"] == TYPE_REQUEST_FULFILLED
    assert note["title"] == "Request available"
    assert 'Demo Show' in note["body"]
    assert note["href"] == "/show/mal-10"
    assert note["read"] is False
    path = notifications_path("u_sister", base)
    rows = load_notifications(path)
    assert len(rows) == 1
    assert rows[0]["id"] == note["id"]


def test_notify_skips_missing_requester(tmp_path: Path):
    assert notify_request_fulfilled({"title": "X", "media_id": "1"}, base=tmp_path) is None


def test_list_and_mark_read(tmp_path: Path):
    base = tmp_path / "user_data"
    a = add_notification("u_a", type="info", title="One", body="first", base=base)
    b = add_notification("u_a", type="info", title="Two", body="second", base=base)
    assert a and b
    items, unread = list_notifications("u_a", base=base)
    assert unread == 2
    assert [n["id"] for n in items] == [b["id"], a["id"]]
    changed = mark_read("u_a", [a["id"]], base=base)
    assert changed == 1
    items, unread = list_notifications("u_a", base=base)
    assert unread == 1
    assert mark_all_read("u_a", base=base) == 1
    _, unread = list_notifications("u_a", base=base)
    assert unread == 0


def test_fulfill_creates_notification_for_requester(tmp_path: Path):
    app, user_data, _requests = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    client.post(
        "/api/requests",
        json={"kind": "series", "media_id": "mal-n1", "title": "Need This"},
    )
    client.post("/logout")
    login_client(client, "manager1", "mgrpass")
    resp = client.post("/api/requests/series:mal-n1/fulfill")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    items, unread = list_notifications("u_sister", base=user_data)
    assert unread == 1
    assert len(items) == 1
    note = items[0]
    assert note["type"] == TYPE_REQUEST_FULFILLED
    assert "Need This" in note["body"]
    assert note["href"] == "/show/mal-n1"

    # Fulfiller / other users get nothing
    assert list_notifications("u_manager1", base=user_data)[1] == 0
    assert list_notifications("u_brother", base=user_data)[1] == 0


def test_refulfill_does_not_duplicate_notification(tmp_path: Path):
    app, user_data, _requests = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    client.post(
        "/api/requests",
        json={"kind": "manga", "media_id": "mal-n2", "title": "Manga Need"},
    )
    client.post("/logout")
    login_client(client, "manager1", "mgrpass")
    assert client.post("/api/requests/manga:mal-n2/fulfill").status_code == 200
    assert client.post("/api/requests/manga:mal-n2/fulfill").status_code == 200
    items, unread = list_notifications("u_sister", base=user_data)
    assert unread == 1
    assert len(items) == 1
    assert items[0]["href"] == "/manga?open=mal-n2"


def test_api_notifications_list_and_mark(tmp_path: Path):
    app, user_data, _requests = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    add_notification(
        "u_sister",
        type="info",
        title="Hello",
        body="World",
        base=user_data,
    )
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["unread_count"] == 1
    assert len(body["notifications"]) == 1
    note_id = body["notifications"][0]["id"]

    # Another user cannot see sister's notifications
    client.post("/logout")
    login_client(client, "brother", "bropass")
    other = client.get("/api/notifications")
    assert other.get_json()["unread_count"] == 0
    assert other.get_json()["notifications"] == []

    client.post("/logout")
    login_client(client, "sister", "sispass")
    marked = client.post("/api/notifications/read", json={"ids": [note_id]})
    assert marked.status_code == 200
    assert marked.get_json()["marked"] == 1
    assert marked.get_json()["unread_count"] == 0

    add_notification(
        "u_sister",
        type="info",
        title="Again",
        body="More",
        base=user_data,
    )
    all_read = client.post("/api/notifications/read", json={"all": True})
    assert all_read.status_code == 200
    assert all_read.get_json()["unread_count"] == 0


def test_header_includes_notifications_bell(tmp_path: Path):
    app, _user_data, _requests = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    home = client.get("/")
    assert home.status_code == 200
    assert b'id="header-notify-toggle"' in home.data
    assert b'id="header-notify-tray"' in home.data
