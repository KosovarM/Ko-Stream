"""Request creation stamps requester; manager fulfill; users cannot fulfill."""

from __future__ import annotations

from pathlib import Path

from kostream.app import create_app
from kostream.requests_store import load_requests, open_requests

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
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
        requests_path=requests,
    )
    return app, requests


def test_user_create_stamps_requester(tmp_path: Path):
    app, requests_path = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    resp = client.post(
        "/api/requests",
        json={
            "kind": "series",
            "media_id": "mal-1",
            "title": "Demo",
            "local_count": 0,
            "expected_count": 12,
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["created"] is True
    entry = body["request"]
    assert entry["requester_id"] == "u_sister"
    assert entry["requester_username"] == "sister"
    assert entry["fulfilled_at"] is None
    assert entry["fulfilled_by"] is None
    rows = load_requests(requests_path)
    assert len(rows) == 1
    assert rows[0]["requester_id"] == "u_sister"


def test_manager_can_fulfill(tmp_path: Path):
    app, requests_path = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    client.post(
        "/api/requests",
        json={"kind": "series", "media_id": "mal-2", "title": "Need"},
    )
    client.post("/logout")
    login_client(client, "manager1", "mgrpass")
    resp = client.post("/api/requests/series:mal-2/fulfill")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["request"]["fulfilled_by"] == "u_manager1"
    assert body["request"]["fulfilled_at"]
    assert open_requests(requests_path) == []


def test_user_cannot_fulfill(tmp_path: Path):
    app, _requests_path = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    client.post(
        "/api/requests",
        json={"kind": "series", "media_id": "mal-3", "title": "Mine"},
    )
    resp = client.post("/api/requests/series:mal-3/fulfill")
    assert resp.status_code == 403
    assert resp.get_json()["ok"] is False


def test_user_cannot_dismiss(tmp_path: Path):
    app, _requests_path = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    client.post(
        "/api/requests",
        json={"kind": "series", "media_id": "mal-4", "title": "Mine"},
    )
    resp = client.delete("/api/requests/series:mal-4")
    assert resp.status_code == 403


def test_master_can_fulfill(tmp_path: Path):
    app, requests_path = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    client.post(
        "/api/requests",
        json={"kind": "manga", "media_id": "mal-9", "title": "Manga"},
    )
    client.post("/logout")
    login_client(client)
    resp = client.post("/api/requests/manga:mal-9/fulfill")
    assert resp.status_code == 200
    assert resp.get_json()["request"]["fulfilled_by"] == "u_testuser"
    assert open_requests(requests_path) == []


def test_catalog_shows_requester(tmp_path: Path):
    app, requests_path = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    client.post(
        "/api/requests",
        json={"kind": "series", "media_id": "mal-ui", "title": "Show Me"},
    )
    # Requester sees own name on catalog
    own = client.get("/catalog")
    assert own.status_code == 200
    assert b"by sister" in own.data
    assert b"Show Me" in own.data

    client.post("/logout")
    login_client(client, "manager1", "mgrpass")
    mgr = client.get("/catalog")
    assert mgr.status_code == 200
    assert b"by sister" in mgr.data

    # Legacy entries without requester fields show Unknown
    from kostream.requests_store import save_requests

    save_requests(
        [
            {
                "id": "series:legacy",
                "kind": "series",
                "media_id": "legacy",
                "title": "Old Title",
                "created_at": "2020-01-01T00:00:00+00:00",
                "updated_at": "2020-01-01T00:00:00+00:00",
                "fulfilled_at": None,
            }
        ],
        requests_path,
    )
    legacy = client.get("/catalog")
    assert b"by Unknown" in legacy.data
    assert b"Old Title" in legacy.data
