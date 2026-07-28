"""Catalog missing-episode upload API (admin/manager only)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from kostream.app import create_app
from kostream.catalog import CatalogEntry, CatalogState, save_catalog
from kostream.local_media import (
    expected_subtitle_filename,
    list_missing_episodes,
    save_episode_file,
)
from kostream.models import Episode, Show

from conftest import add_test_user, bootstrap_test_users, login_client


def _app(tmp_path: Path):
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="demo-show",
                    enabled=True,
                    source="demo",
                    title="Demo Show",
                    folder="Demo Show",
                )
            ]
        ),
        catalog,
    )
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    add_test_user(users, "regular", "regularpass", role="user")
    add_test_user(users, "manager", "managerpass", role="manager")
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )
    return app, media


def test_expected_subtitle_filename_keeps_lang():
    ep = Episode("s-s01e02", "s", 1, 2, "Ep 2", "demo.mp4")
    assert expected_subtitle_filename(ep, "whatever.vtt") == "S01E02.vtt"
    assert expected_subtitle_filename(ep, "track.en.vtt") == "S01E02.en.vtt"


def test_list_missing_episodes_skips_local(tmp_path: Path):
    media = tmp_path / "shows"
    folder = media / "Demo"
    folder.mkdir(parents=True)
    (folder / "S01E01.mp4").write_bytes(b"a")
    show = Show(
        id="demo",
        title="Demo",
        description="",
        episodes=[
            Episode("demo-s01e01", "demo", 1, 1, "Episode 1", "S01E01.mp4"),
            Episode("demo-s01e02", "demo", 1, 2, "Episode 2", "demo.mp4"),
        ],
    )
    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="demo",
                    enabled=True,
                    source="local",
                    folder="Demo",
                    title="Demo",
                )
            ]
        ),
        catalog,
    )
    missing = list_missing_episodes(show, media, catalog_path=catalog)
    assert [m["episode_id"] for m in missing] == ["demo-s01e02"]


def test_catalog_upload_forbidden_for_regular_user(tmp_path: Path):
    app, _media = _app(tmp_path)
    client = app.test_client()
    login_client(client, "regular", "regularpass")
    resp = client.get("/api/catalog/incomplete-shows")
    assert resp.status_code == 403
    resp = client.post(
        "/api/catalog/upload-episode",
        data={
            "show_id": "demo-show",
            "episode_id": "x",
            "video": (BytesIO(b"vid"), "ep.mp4"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 403


def test_catalog_upload_episode_with_optional_subtitle(tmp_path: Path):
    app, media = _app(tmp_path)
    client = app.test_client()
    login_client(client, "manager", "managerpass")

    shows = client.get("/api/catalog/incomplete-shows")
    assert shows.status_code == 200
    body = shows.get_json()
    assert body["ok"] is True
    assert body["count"] >= 1
    assert any(row["id"] == "demo-show" for row in body["shows"])

    missing = client.get("/api/catalog/demo-show/missing-episodes")
    assert missing.status_code == 200
    mbody = missing.get_json()
    assert mbody["ok"] is True
    assert mbody["count"] >= 1
    episode_id = mbody["episodes"][0]["episode_id"]

    resp = client.post(
        "/api/catalog/upload-episode",
        data={
            "show_id": "demo-show",
            "episode_id": episode_id,
            "video": (BytesIO(b"vid-bytes"), "clip.mp4"),
            "subtitle": (BytesIO(b"WEBVTT\n\n"), "clip.en.vtt"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["filename"].endswith(".mp4")
    assert data["subtitle"]["filename"] == data["filename"].rsplit(".", 1)[0] + ".en.vtt"
    folder = media / data["folder"]
    assert (folder / data["filename"]).read_bytes() == b"vid-bytes"
    assert (folder / data["subtitle"]["filename"]).is_file()

    # Uploaded episode is no longer missing
    remaining_ids = {ep["episode_id"] for ep in data["missing_episodes"]}
    assert episode_id not in remaining_ids

    # Reject re-upload of the same episode
    again = client.post(
        "/api/catalog/upload-episode",
        data={
            "show_id": "demo-show",
            "episode_id": episode_id,
            "video": (BytesIO(b"other"), "clip.mp4"),
        },
        content_type="multipart/form-data",
    )
    assert again.status_code == 400


def test_require_missing_blocks_existing_file(tmp_path: Path):
    media = tmp_path / "shows"
    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-1",
                    enabled=True,
                    source="mal",
                    folder="Demo Show",
                    mal_id=1,
                    title="Demo Show",
                )
            ]
        ),
        catalog,
    )
    ep = Episode("mal-1-s01e01", "mal-1", 1, 1, "Episode 1", "demo.mp4")
    show = Show(id="mal-1", title="Demo Show", description="", mal_id=1, episodes=[ep])
    save_episode_file(
        show,
        ep,
        "a.mp4",
        b"one",
        media,
        catalog_path=catalog,
    )
    try:
        save_episode_file(
            show,
            ep,
            "b.mp4",
            b"two",
            media,
            catalog_path=catalog,
            require_missing=True,
        )
        assert False, "expected LocalMediaError"
    except Exception as exc:
        from kostream.local_media import LocalMediaError

        assert isinstance(exc, LocalMediaError)
