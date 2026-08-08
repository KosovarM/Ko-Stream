"""Focused tests for 02.08.2026 patch."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from kostream.aniskip import _timestamps_to_skips
from kostream.app import create_app
from kostream.catalog import CatalogEntry, CatalogState, save_catalog
from kostream.local_media import parse_episode_slot_from_filename
from kostream.manga_catalog import MangaCatalogEntry, MangaCatalogState, save_manga_catalog
from kostream.notifications import (
    add_notification,
    load_notifications,
    notifications_path,
    upsert_product_update_notification,
)
from kostream.releases import PATCH_2026_08_02, load_releases, seed_patch_release, sort_releases
from kostream.titles import normalize_title_lang

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
    return app, media, manga_root, manga_catalog


def test_ger_title_lang_falls_back_to_en():
    assert normalize_title_lang("ger") == "en"
    assert normalize_title_lang("deutsch") == "en"
    assert normalize_title_lang("jp") == "jp"


def test_catalog_hides_german_title_lang(tmp_path: Path):
    app, *_ = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.get("/catalog")
    assert resp.status_code == 200
    assert b'lang=ger' not in resp.data
    assert b'lang=jp' in resp.data
    assert b'lang=en' in resp.data


def test_product_update_notification_replaces_existing(tmp_path: Path):
    base = tmp_path / "ud"
    first = add_notification(
        "u_a",
        type="product_update",
        title="New update released",
        body="Update - 31.07.2026",
        href="/releases",
        base=base,
    )
    assert first is not None
    second = upsert_product_update_notification(
        "u_a",
        title="New update released",
        body="Update - 02.08.2026",
        href="/releases",
        base=base,
    )
    assert second is not None
    notes = load_notifications(notifications_path("u_a", base))
    updates = [n for n in notes if n.get("type") == "product_update"]
    assert len(updates) == 1
    assert updates[0]["id"] == first["id"]
    assert updates[0]["body"] == "Update - 02.08.2026"
    assert updates[0]["read"] is False


def test_seed_prepends_02_08_keeps_31_07(tmp_path: Path):
    path = tmp_path / "releases.json"
    users = tmp_path / "users_seed.json"
    base = tmp_path / "ud_seed"
    bootstrap_test_users(users)
    seed_patch_release(path=path, notify=True, users_path=users, base=base)
    items = sort_releases(load_releases(path))
    # Latest seed is 08.08; 02.08 and 31.07 remain historical.
    assert "02.08.2026" in [r["date"] for r in items]
    assert "31.07.2026" in [r["date"] for r in items]
    row = next(r for r in items if r["date"] == "02.08.2026")
    assert row["sections"] == PATCH_2026_08_02["sections"]


def test_releases_page_accordion(tmp_path: Path):
    app, *_ = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.get("/releases")
    assert resp.status_code == 200
    assert b"<details" in resp.data
    assert b"Update -" in resp.data


def test_skip_button_mutual_exclusion_in_watch_template():
    html = Path("src/kostream/templates/watch.html").read_text(encoding="utf-8")
    assert "if (showOp && showEd) showEd = false;" in html


def test_anime_skip_timestamp_intervals():
    skips = _timestamps_to_skips(
        [
            {"at": 10, "type": {"id": "14550023-2589-46f0-bfb4-152976506b4c", "name": "Intro"}},
            {"at": 100, "type": {"id": "9edc0037-fa4e-47a7-a29a-d9c43368daa8", "name": "Canon"}},
            {"at": 1200, "type": {"id": "2a730a51-a601-439b-bc1f-7b94a640ffb9", "name": "Credits"}},
            {"at": 1290, "type": {"id": "c7b1eddb-defa-4bc6-a598-f143081cfe4b", "name": "Preview"}},
        ],
        episode_length=1400,
    )
    assert skips["op"]["start"] == 10
    assert skips["op"]["end"] == 100
    assert skips["ed"]["start"] == 1200
    assert skips["ed"]["end"] == 1290


def test_parse_episode_slot_from_filename():
    assert parse_episode_slot_from_filename("Show - S01E03.mkv") == (1, 3)
    assert parse_episode_slot_from_filename("ep12.mp4") == (1, 12)


def test_sync_skip_times_label(tmp_path: Path):
    app, *_ = _app(tmp_path)
    client = app.test_client()
    login_client(client, "manager", "managerpass")
    resp = client.get("/catalog")
    assert b"Sync skip times" in resp.data
    assert b"Sync AniSkip" not in resp.data


def test_manga_chapter_upload(tmp_path: Path):
    app, _media, manga_root, manga_catalog = _app(tmp_path)
    save_manga_catalog(
        MangaCatalogState(
            titles=[
                MangaCatalogEntry(
                    id="mal-manga-1",
                    enabled=True,
                    source="mal",
                    folder="Demo Manga",
                    mal_id=1,
                    title="Demo Manga",
                    media_type="manga",
                )
            ]
        ),
        manga_catalog,
    )
    (manga_root / "Demo Manga").mkdir(parents=True)
    # Pretend chapter 1 exists so title is incomplete only for known gaps via num — use upload key directly.
    client = app.test_client()
    login_client(client, "manager", "managerpass")

    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("001.png", b"fakepng")
    buf.seek(0)

    # Without known chapters list, missing list may be empty — upload still works with explicit key.
    resp = client.post(
        "/api/catalog/upload-chapter",
        data={
            "manga_id": "mal-manga-1",
            "chapter_key": "2",
            "file": (buf, "ch2.cbz"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert (manga_root / "Demo Manga" / "Chapter 2.cbz").is_file()
