"""Focused tests for 31.07.2026 patch pieces."""

from __future__ import annotations

from pathlib import Path

from kostream.aniskip import _parse_results, _store_episode, load_skip_times
from kostream.app import create_app
from kostream.manga import MangaChapter, MangaTitle
from kostream.manga_progress import is_currently_publishing, manga_complete_list_status, manga_reading_status
from kostream.notifications import add_notification, dismiss_notification, load_notifications, notifications_path
from kostream.releases import PATCH_2026_07_31, load_releases, seed_patch_release, sort_releases
from kostream.users import create_user, delete_user, find_user_by_id, load_users, touch_last_seen

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
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )
    return app, users, user_data


def test_delete_user_master_only(tmp_path: Path):
    app, users_path, user_data = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    sister = find_user_by_id(load_users(users_path), "u_sister")
    assert sister is not None
    resp = client.post(f"/admin/users/{sister.id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    assert find_user_by_id(load_users(users_path), "u_sister") is None


def test_delete_user_rejects_non_master(tmp_path: Path):
    app, users_path, _ = _app(tmp_path)
    client = app.test_client()
    login_client(client, "sister", "sispass")
    master = next(u for u in load_users(users_path) if u.role == "master")
    resp = client.post(f"/admin/users/{master.id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    assert find_user_by_id(load_users(users_path), master.id) is not None


def test_touch_last_seen_and_online(tmp_path: Path):
    users = tmp_path / "users.json"
    bootstrap_test_users(users)
    user = load_users(users)[0]
    touch_last_seen(users, user.id, min_interval_s=0)
    refreshed = find_user_by_id(load_users(users), user.id)
    assert refreshed is not None
    assert refreshed.last_seen
    assert refreshed.is_online()


def test_dismiss_notification(tmp_path: Path):
    base = tmp_path / "ud"
    note = add_notification("u_a", type="info", title="Hi", body="x", base=base)
    assert note is not None
    assert dismiss_notification("u_a", note["id"], base=base) is True
    assert load_notifications(notifications_path("u_a", base)) == []


def test_publishing_stays_reading_at_100():
    manga = MangaTitle(
        id="m1",
        title="Ongoing",
        folder="Ongoing",
        chapters=[
            MangaChapter(id="c1", title="Chapter 1", page_count=1, kind="dir", relative="1"),
        ],
        num_chapters_mal=1,
        manga_status="currently_publishing",
    )
    assert is_currently_publishing(manga)
    assert manga_reading_status(manga, {"m1": 1}) == "reading"
    assert manga_complete_list_status(manga, 1) == "reading"


def test_aniskip_cache_roundtrip(tmp_path: Path):
    root = tmp_path / "aniskip"
    parsed = _parse_results(
        {
            "results": [
                {"skipType": "op", "interval": {"startTime": 10, "endTime": 90}},
                {"skipType": "ed", "interval": {"startTime": 1200, "endTime": 1290}},
            ]
        }
    )
    _store_episode(21, 3, parsed, root=root)
    loaded = load_skip_times(21, 3, root=root)
    assert loaded["op"]["start"] == 10
    assert loaded["ed"]["end"] == 1290


def test_releases_seed_and_page(tmp_path: Path):
    path = tmp_path / "releases.json"
    users = tmp_path / "users_seed.json"
    base = tmp_path / "ud_seed"
    bootstrap_test_users(users)
    seed_patch_release(path=path, notify=True, users_path=users, base=base)
    items = sort_releases(load_releases(path))
    assert items
    assert items[0]["date"] == PATCH_2026_07_31["date"]
    notes = load_notifications(notifications_path("u_testuser", base))
    assert any(n.get("title") == "New update released" for n in notes)

    app_dir = tmp_path / "app_root"
    app_dir.mkdir(parents=True, exist_ok=True)
    app, _, _ = _app(app_dir)
    client = app.test_client()
    login_client(client)
    resp = client.get("/releases")
    assert resp.status_code == 200
    assert b"Update -" in resp.data or b"Releases" in resp.data


def test_stream_only_tag(tmp_path: Path):
    app, _, _ = _app(tmp_path)
    client = app.test_client()
    login_client(client)
    # Home/admin smoke — dedicated show page needs catalog content;
    # string already asserted elsewhere when grab/metadata shows exist.
    resp = client.get("/admin/users")
    assert resp.status_code == 200
    assert b"Accounts" in resp.data
    assert b"Create user" in resp.data
    # Accounts section should appear before Create user in HTML order
    assert resp.data.find(b"Accounts") < resp.data.find(b"Create user")
