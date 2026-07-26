from unittest.mock import patch

from tests.test_app import _test_app


def test_anilist_search_api(tmp_path):
    app = _test_app(tmp_path)
    client = app.test_client()
    with patch("kostream.app.search_anime") as mock_search:
        from kostream.anilist import AniListMedia

        mock_search.return_value = [
            AniListMedia(
                anilist_id=154587,
                title="Frieren",
                description="After the party.",
                genres=["Adventure", "Fantasy"],
                poster_url="https://example.com/frieren.jpg",
                banner_url=None,
            )
        ]
        resp = client.get("/api/anilist/search?q=Frieren")

    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["results"]) == 1
    assert data["results"][0]["title"] == "Frieren"
