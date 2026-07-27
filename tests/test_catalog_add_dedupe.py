"""AniList / catalog add must not create duplicate rows."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from kostream.app import create_app
from kostream.catalog import (
    CatalogEntry,
    CatalogState,
    find_matching_entry,
    load_catalog,
    save_catalog,
)

from conftest import add_test_user, bootstrap_test_users, login_client


def _app(tmp_path: Path, shows: list[CatalogEntry] | None = None):
    catalog = tmp_path / "selected.json"
    save_catalog(CatalogState(shows=shows or []), catalog)
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


def test_find_matching_entry_by_mal_id(tmp_path: Path):
    state = CatalogState(
        shows=[
            CatalogEntry(id="mal-21", enabled=True, source="mal", mal_id=21, title="One Piece"),
        ]
    )
    found = find_matching_entry(state, entry_id="anilist-999", mal_id=21, anilist_id=999)
    assert found is not None
    assert found.id == "mal-21"


def test_find_matching_entry_by_anilist_id(tmp_path: Path):
    state = CatalogState(
        shows=[
            CatalogEntry(
                id="anilist-154587",
                enabled=True,
                source="anilist",
                anilist_id=154587,
                title="Frieren",
            ),
        ]
    )
    found = find_matching_entry(state, entry_id="other", anilist_id=154587)
    assert found is not None
    assert found.id == "anilist-154587"


def test_add_existing_mal_id_returns_existing_no_duplicate(tmp_path: Path):
    app, catalog_path = _app(
        tmp_path,
        shows=[
            CatalogEntry(id="mal-21", enabled=True, source="mal", mal_id=21, title="One Piece"),
        ],
    )
    client = app.test_client()
    login_client(client)
    with patch("kostream.app.fetch_mal_id", return_value=21):
        resp = client.post(
            "/api/catalog/add",
            json={
                "source": "anilist",
                "id": "anilist-21",
                "anilist_id": 21,
                "title": "One Piece (AniList)",
            },
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["existing"] is True
    assert data["id"] == "mal-21"
    assert data["redirect"].endswith("/show/mal-21")
    loaded = load_catalog(catalog_path)
    assert len(loaded.shows) == 1
    assert loaded.shows[0].id == "mal-21"
    assert loaded.shows[0].title == "One Piece"


def test_add_existing_html_redirects_to_show(tmp_path: Path):
    app, catalog_path = _app(
        tmp_path,
        shows=[
            CatalogEntry(id="mal-21", enabled=True, source="mal", mal_id=21, title="One Piece"),
        ],
    )
    client = app.test_client()
    login_client(client)
    resp = client.post(
        "/api/catalog/add",
        data={"source": "mal", "id": "mal-21", "mal_id": "21", "title": "One Piece"},
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.location.endswith("/show/mal-21")
    assert len(load_catalog(catalog_path).shows) == 1


def test_add_new_entry_creates_row(tmp_path: Path):
    app, catalog_path = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    with patch("kostream.app.fetch_mal_id", return_value=31240):
        resp = client.post(
            "/api/catalog/add",
            json={
                "source": "anilist",
                "id": "anilist-108465",
                "anilist_id": 108465,
                "title": "Re:Zero",
            },
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data.get("existing") is False
    assert data["id"] == "anilist-108465"
    loaded = load_catalog(catalog_path)
    assert len(loaded.shows) == 1
    assert loaded.shows[0].mal_id == 31240


def test_non_master_can_add_via_catalog_api(tmp_path: Path):
    app, catalog_path = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    with patch("kostream.app.fetch_mal_id", return_value=16498):
        resp = client.post(
            "/api/catalog/add",
            json={
                "source": "anilist",
                "id": "anilist-16498",
                "anilist_id": 16498,
                "title": "Attack on Titan",
            },
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data.get("existing") is False
    assert data["id"] == "anilist-16498"
    loaded = load_catalog(catalog_path)
    assert len(loaded.shows) == 1
    assert loaded.shows[0].title == "Attack on Titan"


def test_library_page_shows_anilist_search_for_non_master(tmp_path: Path):
    app, _catalog = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    resp = client.get("/catalog")
    assert resp.status_code == 200
    assert b"Search AniList" in resp.data
    assert b'id="anilist-search"' in resp.data
    # Section must not be master-gated with the HTML ``hidden`` attribute.
    assert b'class="catalog-section" hidden' not in resp.data