from unittest.mock import patch

from kostream.anilist import USER_AGENT, search_anime
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
