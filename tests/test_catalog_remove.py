"""Master-only catalog remove from show overview."""

from __future__ import annotations

from pathlib import Path

from kostream.app import create_app
from kostream.catalog import CatalogEntry, CatalogState, load_catalog, save_catalog

from conftest import add_test_user, bootstrap_test_users, login_client


def _app(tmp_path: Path):
    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-21",
                    enabled=True,
                    source="mal",
                    mal_id=21,
                    title="One Piece",
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
    add_test_user(users, "sister", "sispass", role="user")
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )
    return app, catalog


def test_master_can_remove_from_catalog(tmp_path: Path):
    app, catalog_path = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.post("/api/catalog/remove", json={"id": "mal-21"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["id"] == "mal-21"
    assert "redirect" in data
    assert load_catalog(catalog_path).get("mal-21") is None


def test_non_master_cannot_remove_from_catalog(tmp_path: Path):
    app, catalog_path = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    resp = client.post("/api/catalog/remove", json={"id": "mal-21"})
    assert resp.status_code == 403
    assert load_catalog(catalog_path).get("mal-21") is not None


def test_show_page_hides_remove_for_non_master(tmp_path: Path):
    app, _catalog = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    resp = client.get("/show/mal-21")
    assert resp.status_code == 200
    assert b"Remove from catalog" not in resp.data
    assert b"btn-catalog-remove" not in resp.data


def test_show_page_shows_remove_for_master(tmp_path: Path):
    app, _catalog = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.get("/show/mal-21")
    assert resp.status_code == 200
    assert b"Remove from catalog" in resp.data
    assert b"btn-catalog-remove" in resp.data
