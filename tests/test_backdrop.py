"""Show detail backdrop prefers wide banners / remote large posters over card thumbs."""

from __future__ import annotations

from unittest.mock import patch

from kostream.app import _backdrop_for, _hydrate_show_banner, _remote_poster_url
from kostream.anilist import AniListMedia
from kostream.mal import prefer_large_mal_picture_url
from kostream.models import Show


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
