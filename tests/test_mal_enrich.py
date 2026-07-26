from unittest.mock import patch

from kostream.mal import MalAnimeEntry, merge_anime_details_into_cache, write_cached_anime
from kostream.models import RelatedAnime


def test_merge_anime_details_writes_related_anime(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    write_cached_anime(
        MalAnimeEntry(
            mal_id=9919,
            title="Ao no Exorcist",
            synopsis="Old",
            poster_url=None,
            genres=["Action"],
            num_episodes=25,
            list_status="watching",
            num_episodes_watched=5,
            anime_status="finished_airing",
            score=8,
            mean_score=7.5,
        )
    )

    api_payload = {
        "id": 9919,
        "title": "Ao no Exorcist",
        "synopsis": "Updated synopsis",
        "num_episodes": 25,
        "mean": 7.47,
        "status": "finished_airing",
        "related_anime": [
            {
                "relation_type": "prequel",
                "node": {"id": 9919, "title": "Same"},
            },
            {
                "relation_type": "sequel",
                "node": {"id": 53889, "title": "Ao no Exorcist: Shimane Illuminati-hen"},
            },
        ],
        "genres": [{"name": "Action"}],
        "main_picture": {"large": "https://example.com/poster.jpg"},
    }

    with patch("kostream.mal._api_get_raw", return_value=api_payload):
        entry = merge_anime_details_into_cache("token", 9919)

    assert entry.num_episodes_watched == 5
    assert entry.score == 8
    assert len(entry.related_anime) == 2
    assert entry.related_anime[1].relation_type == "sequel"
    assert entry.related_anime[1].mal_id == 53889

    reloaded = mal_mod.load_cached_anime(9919)
    assert reloaded is not None
    assert len(reloaded.related_anime) == 2
