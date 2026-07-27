"""Tests for local folder prepare + episode upload."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from kostream.app import create_app
from kostream.catalog import CatalogEntry, CatalogState, load_catalog, save_catalog
from kostream.library import get_show
from kostream.local_media import (
    expected_episode_filename,
    prepare_show_folder,
    save_episode_file,
    suggest_folder_name,
)
from kostream.models import Episode, Show

from conftest import bootstrap_test_users, login_client


def test_suggest_and_expected_names():
    show = Show(
        id="mal-1",
        title="Demo Anime",
        description="",
        episodes=[Episode("mal-1-s04e03", "mal-1", 4, 3, "Episode 3", "demo.mp4")],
    )
    assert suggest_folder_name(show) == "Demo Anime Season 4"
    assert expected_episode_filename(show.episodes[0]) == "S04E03.mp4"
    assert expected_episode_filename(show.episodes[0], ext=".mkv") == "S04E03.mkv"


def test_prepare_folder_creates_and_links_catalog(tmp_path: Path):
    media = tmp_path / "shows"
    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-61316",
                    enabled=True,
                    source="mal",
                    mal_id=61316,
                    title="Re:Zero S4",
                )
            ]
        ),
        catalog,
    )
    show = Show(
        id="mal-61316",
        title="Re:Zero S4",
        description="",
        mal_id=61316,
        episodes=[Episode("mal-61316-s04e01", "mal-61316", 4, 1, "Episode 1", "demo.mp4")],
    )
    info = prepare_show_folder(show, media, catalog_path=catalog)
    assert info["folder_exists"] is True
    assert (media / info["folder"]).is_dir()
    entry = load_catalog(catalog).get("mal-61316")
    assert entry is not None
    assert entry.folder == info["folder"]


def test_upload_renames_to_sxxexx(tmp_path: Path):
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
    ep = Episode("mal-1-s04e02", "mal-1", 4, 2, "Episode 2", "demo.mp4")
    show = Show(id="mal-1", title="Demo Show", description="", mal_id=1, episodes=[ep])
    result = save_episode_file(
        show,
        ep,
        "Episode 2.mp4",
        b"fake-video-bytes",
        media,
        catalog_path=catalog,
    )
    assert result["filename"] == "S04E02.mp4"
    assert (media / "Demo Show" / "S04E02.mp4").read_bytes() == b"fake-video-bytes"


def test_api_prepare_and_upload(tmp_path: Path):
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
                )
            ]
        ),
        catalog,
    )
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    app = create_app(media_root=media, catalog_path=catalog, users_path=users, user_data_base=user_data)
    client = app.test_client()
    login_client(client)
    show = get_show("demo-show", media, catalog)
    assert show is not None
    ep = show.episodes[0]

    resp = client.post(f"/api/show/{show.id}/prepare-folder", json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["folder_exists"] is True

    resp = client.post(
        f"/api/show/{show.id}/upload-episode",
        data={
            "episode_id": ep.id,
            "file": (BytesIO(b"vid-bytes"), "whatever.mp4"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["filename"].endswith(".mp4")
    assert data["filename"].startswith("S")
