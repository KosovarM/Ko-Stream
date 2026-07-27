from unittest.mock import patch

from kostream.anilist import USER_AGENT, fetch_anime_by_mal_id, search_anime
from kostream.anilist import _post_graphql


def test_post_graphql_sends_user_agent():
    captured: dict = {}

    def fake_urlopen(req, timeout=0):
        captured["user_agent"] = req.headers.get("User-agent") or req.headers.get("User-Agent")
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return b'{"data":{"Page":{"media":[]}}}'

        return Resp()

    with patch("kostream.anilist.urlopen", fake_urlopen):
        _post_graphql("query { Page { media { id } } }", {})

    assert captured["user_agent"] == USER_AGENT


def test_search_anime_parses_results():
    payload = {
        "data": {
            "Page": {
                "media": [
                    {
                        "id": 21,
                        "title": {"english": "One Piece", "romaji": "ONE PIECE"},
                        "description": "A pirate adventure.",
                        "genres": ["Action", "Adventure"],
                        "coverImage": {"large": "https://example.com/poster.jpg"},
                        "bannerImage": "https://example.com/banner.jpg",
                    }
                ]
            }
        }
    }

    with patch("kostream.anilist._post_graphql", return_value=payload):
        results = search_anime("One Piece")

    assert len(results) == 1
    assert results[0].title == "One Piece"
    assert results[0].anilist_id == 21
    assert results[0].poster_url == "https://example.com/poster.jpg"
    assert results[0].banner_url == "https://example.com/banner.jpg"


def test_fetch_anime_by_mal_id_parses_banner(tmp_path, monkeypatch):
    monkeypatch.setattr("kostream.anilist.CACHE_DIR", tmp_path)
    monkeypatch.setattr("kostream.anilist.MAL_INDEX_DIR", tmp_path / "mal")
    payload = {
        "data": {
            "Media": {
                "id": 16498,
                "title": {"english": "Attack on Titan", "romaji": "Shingeki no Kyojin"},
                "description": "Titans.",
                "genres": ["Action"],
                "idMal": 16498,
                "episodes": 25,
                "coverImage": {
                    "large": "https://example.com/cover-large.jpg",
                    "extraLarge": "https://example.com/cover-xl.jpg",
                },
                "bannerImage": "https://example.com/wide-banner.jpg",
            }
        }
    }
    with patch("kostream.anilist._post_graphql", return_value=payload) as post:
        media = fetch_anime_by_mal_id(16498, network=True)
        assert post.called
    assert media is not None
    assert media.anilist_id == 16498
    assert media.mal_id == 16498
    assert media.poster_url == "https://example.com/cover-xl.jpg"
    assert media.banner_url == "https://example.com/wide-banner.jpg"

    with patch("kostream.anilist._post_graphql") as again:
        cached = fetch_anime_by_mal_id(16498, network=True)
        again.assert_not_called()
    assert cached is not None
    assert cached.banner_url == "https://example.com/wide-banner.jpg"
