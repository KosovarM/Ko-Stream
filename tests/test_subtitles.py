"""Tests for WebVTT sidecar discovery."""

from __future__ import annotations

from pathlib import Path

from kostream.subtitles import discover_vtt_sidecars, parse_vtt_label


def test_parse_vtt_label_plain_and_lang():
    assert parse_vtt_label("S01E01", "S01E01.vtt") == ("und", "Subtitles")
    assert parse_vtt_label("S01E01", "S01E01.en.vtt") == ("en", "English")
    assert parse_vtt_label("S01E01", "S01E01.de.forced.vtt") == ("de", "German (forced)")


def test_discover_vtt_sidecars(tmp_path: Path):
    show = tmp_path / "Demo"
    season = show / "Season 01"
    season.mkdir(parents=True)
    video = season / "S01E01.mp4"
    video.write_bytes(b"x")
    (season / "S01E01.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (season / "S01E01.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (season / "S01E02.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (season / "S01E010.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (season / "other.vtt").write_text("WEBVTT\n", encoding="utf-8")

    tracks = discover_vtt_sidecars(video, show_dir=show)
    rels = {t.relpath for t in tracks}
    assert rels == {"Season 01/S01E01.vtt", "Season 01/S01E01.en.vtt"}
    by_rel = {t.relpath: t for t in tracks}
    assert by_rel["Season 01/S01E01.en.vtt"].lang == "en"
    assert by_rel["Season 01/S01E01.en.vtt"].label == "English"

def test_media_route_serves_vtt(tmp_path: Path):
    from kostream.app import create_app
    from kostream.catalog import CatalogEntry, CatalogState, save_catalog
    from tests.conftest import bootstrap_test_users, login_client

    media = tmp_path / "media"
    show = media / "Demo Show"
    show.mkdir(parents=True)
    (show / "S01E01.mp4").write_bytes(b"video")
    (show / "S01E01.en.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n", encoding="utf-8"
    )
    catalog = tmp_path / "catalog.json"
    save_catalog(
        CatalogState(
            shows=[CatalogEntry(id="demo-show", enabled=True, source="local", title="Demo Show", folder="Demo Show")]
        ),
        catalog,
    )
    users = tmp_path / "users.json"
    bootstrap_test_users(users)
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=tmp_path / "user_data",
    )
    client = app.test_client()
    login_client(client)
    resp = client.get("/media/demo-show/S01E01.en.vtt")
    assert resp.status_code == 200
    assert b"WEBVTT" in resp.data
    assert "text/vtt" in (resp.mimetype or resp.content_type or "")

def test_watch_page_uses_native_controls_with_tracks_and_autohide(tmp_path: Path):
    from kostream.app import create_app
    from kostream.catalog import CatalogEntry, CatalogState, save_catalog
    from tests.conftest import bootstrap_test_users, login_client

    media = tmp_path / "media"
    show = media / "Demo Show"
    show.mkdir(parents=True)
    (show / "S01E01.mp4").write_bytes(b"video")
    (show / "S01E01.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="demo-show",
                    enabled=True,
                    folder="Demo Show",
                    title="Demo",
                )
            ]
        ),
        catalog,
    )
    users = tmp_path / "users.json"
    bootstrap_test_users(users)
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=tmp_path / "ud",
    )
    client = app.test_client()
    login_client(client)
    resp = client.get("/watch/demo-show/demo-show-s01e01")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="player"' in body
    video_open = body.split("<video", 1)[1].split(">", 1)[0]
    assert "controls" in video_open
    assert "has-native-chrome" in body
    assert 'data-idle-ms="3000"' in body
    assert "video.controls = false" in body
    assert "nofullscreen" in body
    assert "toggleShellFullscreen" in body
    assert "player-fs-btn" in body
    assert "webkitEnterFullscreen" in body
    assert "removeAttribute('controls')" in body
    assert "player-chrome" not in body
    assert "<track" in body
    assert "S01E01.en.vtt" in body
    assert "nextWatchUrl" in body
    assert "rewatch" in body

