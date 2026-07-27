"""Tests for Grab URL resolve, cache, override, and proxy route."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Response

from kostream.app import create_app
from kostream.catalog import CatalogEntry, CatalogState, save_catalog
from kostream.grab import (
    DEMO_STREAM_URLS,
    get_override,
    resolve_stream_url,
    run_external_resolver,
    set_override,
    set_overrides_bulk,
)
from kostream.library import get_show
from kostream.models import Episode, Show

from conftest import bootstrap_test_users, login_client


@pytest.fixture
def grab_base(tmp_path: Path) -> Path:
    path = tmp_path / "grab"
    path.mkdir()
    return path


@pytest.fixture
def demo_show() -> Show:
    ep = Episode("show-s01e01", "show", 1, 1, "Episode 1", "demo.mp4")
    return Show(id="show", title="Show", description="", episodes=[ep])


def test_resolve_demo_url(grab_base: Path, demo_show: Show, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    monkeypatch.setenv("KOSTREAM_GRAB_DEMO", "1")
    monkeypatch.delenv("KOSTREAM_GRAB_CMD", raising=False)
    result = resolve_stream_url(demo_show, demo_show.episodes[0], base=grab_base)
    assert result is not None
    assert result.source == "demo"
    assert result.url == DEMO_STREAM_URLS[0]


def test_resolve_without_demo_or_cmd_returns_none(
    grab_base: Path, demo_show: Show, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    monkeypatch.setenv("KOSTREAM_GRAB_DEMO", "0")
    monkeypatch.delenv("KOSTREAM_GRAB_CMD", raising=False)
    assert resolve_stream_url(demo_show, demo_show.episodes[0], base=grab_base) is None


def test_resolve_override_beats_demo(
    grab_base: Path, demo_show: Show, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    monkeypatch.setenv("KOSTREAM_GRAB_DEMO", "1")
    custom = "https://example.com/custom.mp4"
    set_override("show", "show-s01e01", custom, base=grab_base)
    result = resolve_stream_url(demo_show, demo_show.episodes[0], base=grab_base)
    assert result is not None
    assert result.source == "override"
    assert result.url == custom
    assert get_override("show", "show-s01e01", base=grab_base) == custom


def test_resolve_uses_cache(
    grab_base: Path, demo_show: Show, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    monkeypatch.setenv("KOSTREAM_GRAB_DEMO", "1")
    monkeypatch.delenv("KOSTREAM_GRAB_CMD", raising=False)
    first = resolve_stream_url(demo_show, demo_show.episodes[0], base=grab_base)
    assert first is not None and first.source == "demo"
    second = resolve_stream_url(demo_show, demo_show.episodes[0], base=grab_base)
    assert second is not None
    assert second.source == "cache"
    assert second.url == first.url


def test_resolve_external_cmd(
    grab_base: Path, demo_show: Show, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    monkeypatch.setenv("KOSTREAM_GRAB_DEMO", "0")
    script = tmp_path / "resolver.py"
    script.write_text(
        "import json,sys\n"
        "data=json.load(sys.stdin)\n"
        "print('https://cdn.example/ep' + str(data['number']) + '.mp4')\n",
        encoding="utf-8",
    )
    cmd = f'"{sys.executable}" "{script}"'
    monkeypatch.setenv("KOSTREAM_GRAB_CMD", cmd)
    result = resolve_stream_url(demo_show, demo_show.episodes[0], base=grab_base)
    assert result is not None
    assert result.source == "external"
    assert result.url == "https://cdn.example/ep1.mp4"


def test_run_external_resolver_json_stdout(demo_show: Show, tmp_path: Path):
    script = tmp_path / "resolver.py"
    script.write_text(
        "import json,sys\nprint(json.dumps({'url':'https://cdn.example/x.mp4'}))\n",
        encoding="utf-8",
    )
    url = run_external_resolver(f'"{sys.executable}" "{script}"', demo_show, demo_show.episodes[0])
    assert url == "https://cdn.example/x.mp4"


def test_grab_disabled_returns_none(
    grab_base: Path, demo_show: Show, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "0")
    assert resolve_stream_url(demo_show, demo_show.episodes[0], base=grab_base) is None


def test_non_demo_without_override_returns_none(
    grab_base: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    ep = Episode("s-e1", "s", 1, 1, "Local", "S01E01.mp4")
    show = Show(id="s", title="S", description="", episodes=[ep])
    assert resolve_stream_url(show, ep, base=grab_base) is None


def test_set_overrides_bulk(grab_base: Path):
    saved = set_overrides_bulk(
        "show",
        {"show-s01e01": "https://a.example/1.mp4", "show-s01e02": "https://a.example/2.mp4"},
        base=grab_base,
    )
    assert len(saved) == 2
    assert get_override("show", "show-s01e01", base=grab_base) == "https://a.example/1.mp4"


def _app_with_demo(tmp_path: Path, grab_base: Path):
    catalog = tmp_path / "selected.json"
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    state = CatalogState(
        shows=[
            CatalogEntry(
                id="demo-show",
                enabled=True,
                source="demo",
                title="Demo Show",
            )
        ]
    )
    save_catalog(state, catalog)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    return create_app(
        media_root=media,
        catalog_path=catalog,
        grab_base=grab_base,
        users_path=users,
        user_data_base=user_data,
    )


def _logged_in_client(app):
    client = app.test_client()
    login_client(client)
    return client


def test_watch_page_uses_grab_when_demo_enabled(
    tmp_path: Path, grab_base: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    monkeypatch.setenv("KOSTREAM_GRAB_DEMO", "1")
    monkeypatch.delenv("KOSTREAM_GRAB_CMD", raising=False)
    app = _app_with_demo(tmp_path, grab_base)
    client = _logged_in_client(app)
    show = get_show("demo-show", app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
    assert show is not None
    ep = show.episodes[0]
    resp = client.get(f"/watch/{show.id}/{ep.id}")
    assert resp.status_code == 200
    assert b"/stream/grab/" in resp.data
    assert b"On-demand stream (grab" in resp.data
    assert b'id="player"' in resp.data


def test_watch_page_needs_resolve_without_demo(
    tmp_path: Path, grab_base: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    monkeypatch.setenv("KOSTREAM_GRAB_DEMO", "0")
    monkeypatch.delenv("KOSTREAM_GRAB_CMD", raising=False)
    app = _app_with_demo(tmp_path, grab_base)
    client = _logged_in_client(app)
    show = get_show("demo-show", app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
    assert show is not None
    ep = show.episodes[0]
    resp = client.get(f"/watch/{show.id}/{ep.id}")
    assert resp.status_code == 200
    assert b"Stream only" in resp.data
    assert b"/stream/grab/" not in resp.data


def test_watch_page_demo_when_grab_off(
    tmp_path: Path, grab_base: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "0")
    app = _app_with_demo(tmp_path, grab_base)
    client = _logged_in_client(app)
    show = get_show("demo-show", app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
    assert show is not None
    ep = show.episodes[0]
    resp = client.get(f"/watch/{show.id}/{ep.id}")
    assert resp.status_code == 200
    assert b"Stream only" in resp.data
    assert b"/stream/grab/" not in resp.data


def test_proxy_grab_route(
    tmp_path: Path, grab_base: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    monkeypatch.setenv("KOSTREAM_GRAB_DEMO", "1")
    monkeypatch.delenv("KOSTREAM_GRAB_CMD", raising=False)
    app = _app_with_demo(tmp_path, grab_base)
    client = _logged_in_client(app)
    show = get_show("demo-show", app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
    assert show is not None
    ep = show.episodes[0]

    def fake_proxy(url: str, request, **kwargs):
        assert url.startswith("https://")
        return Response(b"ok", status=200, mimetype="video/mp4")

    with patch("kostream.app.proxy_remote_stream", side_effect=fake_proxy):
        resp = client.get(f"/stream/grab/{show.id}/{ep.id}")
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_api_grab_override(
    tmp_path: Path, grab_base: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    app = _app_with_demo(tmp_path, grab_base)
    client = _logged_in_client(app)
    show = get_show("demo-show", app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
    assert show is not None
    ep = show.episodes[0]
    url = "https://example.com/ep.mp4"
    resp = client.post(
        "/api/grab/override",
        json={"show_id": show.id, "episode_id": ep.id, "url": url},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert get_override(show.id, ep.id, base=grab_base) == url


def test_api_grab_resolve_and_bulk(
    tmp_path: Path, grab_base: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KOSTREAM_GRAB", "1")
    monkeypatch.setenv("KOSTREAM_GRAB_DEMO", "1")
    monkeypatch.delenv("KOSTREAM_GRAB_CMD", raising=False)
    app = _app_with_demo(tmp_path, grab_base)
    client = _logged_in_client(app)
    show = get_show("demo-show", app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
    assert show is not None
    ep = show.episodes[0]

    resp = client.post(
        "/api/grab/resolve",
        json={"show_id": show.id, "episode_id": ep.id, "force": True},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["source"] == "demo"

    resp = client.post(
        "/api/grab/overrides/bulk",
        json={"show_id": show.id, "urls": {ep.id: "https://bulk.example/a.mp4"}},
    )
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 1
