"""Show detail backdrop prefers wide banners / remote large posters over card thumbs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from kostream.app import (
    _backdrop_for,
    _hydrate_show_banner,
    _remote_poster_url,
    create_app,
)
from kostream.anilist import AniListMedia
from kostream.mal import prefer_large_mal_picture_url
from kostream.models import Show

from conftest import bootstrap_test_users, login_client


def test_prefer_large_mal_picture_url_upgrades_medium_and_tiny():
    medium = "https://cdn.myanimelist.net/images/anime/10/47347.jpg"
    tiny = "https://cdn.myanimelist.net/images/anime/10/47347t.jpg"
    large = "https://cdn.myanimelist.net/images/anime/10/47347l.jpg"
    assert prefer_large_mal_picture_url(medium) == large
    assert prefer_large_mal_picture_url(tiny) == large
    assert prefer_large_mal_picture_url(large) == large
    other = "https://s4.anilist.co/file/anilistcdn/media/anime/banner/1.jpg"
    assert prefer_large_mal_picture_url(other) == other


def test_backdrop_prefers_banner_over_local_poster():
    show = Show(
        id="mal-1",
        title="Test",
        description="",
        mal_id=1,
        poster_url="/media/thumbnail/anime/1",
        banner_url="https://example.com/banner.jpg",
    )
    assert _backdrop_for(show) == "https://example.com/banner.jpg"


def test_backdrop_uses_remote_mal_poster_not_local_thumb():
    show = Show(
        id="mal-2",
        title="Test",
        description="",
        mal_id=2,
        poster_url="/media/thumbnail/anime/2",
    )
    remote = "https://cdn.myanimelist.net/images/anime/1/2.jpg"
    with patch("kostream.app.load_cached_anime") as load:
        load.return_value = type("E", (), {"poster_url": remote})()
        with patch("kostream.app._anilist_banner_url", return_value=None):
            assert _backdrop_for(show) == prefer_large_mal_picture_url(remote)


def test_remote_poster_upgrades_medium_url_on_show():
    show = Show(
        id="mal-3",
        title="Test",
        description="",
        poster_url="https://cdn.myanimelist.net/images/anime/9/28329.jpg",
    )
    assert _remote_poster_url(show) == (
        "https://cdn.myanimelist.net/images/anime/9/28329l.jpg"
    )


def test_hydrate_show_banner_from_anilist_mal_lookup():
    show = Show(id="mal-4", title="Test", description="", mal_id=16498)
    meta = AniListMedia(
        anilist_id=16498,
        title="Attack on Titan",
        description="",
        genres=[],
        poster_url="https://example.com/p.jpg",
        banner_url="https://example.com/banner.jpg",
        mal_id=16498,
    )
    with patch("kostream.app.fetch_anime_by_mal_id", return_value=meta):
        _hydrate_show_banner(show)
    assert show.banner_url == "https://example.com/banner.jpg"


def test_backdrop_sets_banner_url_when_found_in_cache():
    show = Show(
        id="mal-5",
        title="Test",
        description="",
        mal_id=5,
        poster_url="/media/thumbnail/anime/5",
    )
    with patch(
        "kostream.app._anilist_banner_url",
        return_value="https://example.com/cached-banner.jpg",
    ):
        assert _backdrop_for(show) == "https://example.com/cached-banner.jpg"
    assert show.banner_url == "https://example.com/cached-banner.jpg"


def _home_client(tmp_path: Path):
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
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
    return client


def test_home_featured_hydrates_banner_background(tmp_path: Path, monkeypatch):
    """Featured belt must hydrate AniList banners and not stretch card thumbs."""
    featured = [
        Show(
            id="mal-16498",
            title="Attack on Titan",
            description="A" * 40,
            mal_id=16498,
            poster_url="/media/thumbnail/anime/16498",
        )
    ]
    monkeypatch.setattr(
        "kostream.app._random_library_sample",
        lambda shows, limit=10: featured,
    )
    monkeypatch.setattr(
        "kostream.app._hydrate_show_banner",
        lambda show: setattr(show, "banner_url", "https://cdn.example/wide-banner.jpg"),
    )
    client = _home_client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "https://cdn.example/wide-banner.jpg" in html
    assert "spotlight-bg" in html
    assert "spotlight-bg--poster" not in html


def test_home_featured_poster_fallback_uses_soft_blur(tmp_path: Path, monkeypatch):
    featured = [
        Show(
            id="mal-99",
            title="No Banner Show",
            description="B" * 40,
            mal_id=99,
            poster_url="/media/thumbnail/anime/99",
        )
    ]
    monkeypatch.setattr(
        "kostream.app._random_library_sample",
        lambda shows, limit=10: featured,
    )
    monkeypatch.setattr("kostream.app._hydrate_show_banner", lambda show: None)
    monkeypatch.setattr(
        "kostream.app._backdrop_for",
        lambda show: show.poster_url,
    )
    client = _home_client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "spotlight-bg--poster" in html
    assert "/media/thumbnail/anime/99" in html
