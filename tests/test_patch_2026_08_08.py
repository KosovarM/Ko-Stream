"""Focused tests for 08.08.2026 manga reader release."""

from __future__ import annotations

from pathlib import Path

from kostream.app import create_app
from kostream.manga_catalog import MangaCatalogState, save_manga_catalog
from kostream.notifications import (
    add_notification,
    load_notifications,
    notifications_path,
    upsert_product_update_notification,
)
from kostream.releases import (
    PATCH_2026_08_02,
    PATCH_2026_08_08,
    load_releases,
    seed_patch_release,
    sort_releases,
)

from conftest import add_test_user, bootstrap_test_users, login_client


def _app(tmp_path: Path):
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    manga_root = tmp_path / "manga"
    manga_root.mkdir(parents=True)
    manga_catalog = tmp_path / "manga_selected.json"
    save_manga_catalog(MangaCatalogState(titles=[]), manga_catalog)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    add_test_user(users, "manager", "managerpass", role="manager")
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
        users_path=users,
        user_data_base=user_data,
    )
    return app


def test_seed_prepends_08_08_keeps_older(tmp_path: Path):
    path = tmp_path / "releases.json"
    users = tmp_path / "users_seed.json"
    base = tmp_path / "ud_seed"
    bootstrap_test_users(users)
    seed_patch_release(path=path, notify=True, users_path=users, base=base)
    items = sort_releases(load_releases(path))
    assert [r["date"] for r in items[:3]] == ["08.08.2026", "02.08.2026", "31.07.2026"]
    assert items[0]["sections"] == PATCH_2026_08_08["sections"]
    assert items[1]["sections"] == PATCH_2026_08_02["sections"]


def test_product_update_notification_replaces_existing(tmp_path: Path):
    base = tmp_path / "ud"
    first = add_notification(
        "u_a",
        type="product_update",
        title="New update released",
        body="Update - 02.08.2026",
        href="/releases",
        base=base,
    )
    assert first is not None
    second = upsert_product_update_notification(
        "u_a",
        title="New update released",
        body="Update - 08.08.2026",
        href="/releases",
        base=base,
    )
    assert second is not None
    notes = load_notifications(notifications_path("u_a", base))
    updates = [n for n in notes if n.get("type") == "product_update"]
    assert len(updates) == 1
    assert updates[0]["id"] == first["id"]
    assert updates[0]["body"] == "Update - 08.08.2026"
    assert updates[0]["read"] is False


def test_releases_page_shows_08_08_accordion(tmp_path: Path):
    app = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.get("/releases")
    assert resp.status_code == 200
    assert b"<details" in resp.data
    assert b"Update - 08.08.2026" in resp.data
    assert b"side-scroll" in resp.data
    assert b"end-stop" in resp.data


def test_manga_reader_horizontal_scroll_and_vertical_end_stop():
    html = Path("src/kostream/templates/manga.html").read_text(encoding="utf-8")
    css = Path("src/kostream/static/style.css").read_text(encoding="utf-8")
    assert "function renderPaged" in html
    assert "scroll-snap-type: x proximity" in css
    assert "isNearWebtoonBottom" in html
    assert "chapterAdvanceArmed" in html
    assert "manga-reader-next-chapter" in html
    assert "Past end of last page" not in html
    assert "pointer-events: none" in css
