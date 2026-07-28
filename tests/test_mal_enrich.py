from unittest.mock import patch
import json

from kostream.mal import MalAnimeEntry, merge_anime_details_into_cache, write_cached_anime


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
        "studios": [{"id": 7, "name": "A-1 Pictures"}],
        "main_picture": {"large": "https://example.com/poster.jpg"},
    }

    with patch("kostream.mal._api_get_raw", return_value=api_payload):
        entry = merge_anime_details_into_cache("token", 9919)

    assert entry.title == "Ao no Exorcist"
    assert len(entry.related_anime) == 2
    assert entry.related_anime[1].relation_type == "sequel"
    assert entry.related_anime[1].mal_id == 53889
    assert entry.studios == ["A-1 Pictures"]

    reloaded = mal_mod.load_cached_anime(9919)
    assert reloaded is not None
    assert len(reloaded.related_anime) == 2
    assert reloaded.studios == ["A-1 Pictures"]
    raw = json.loads((tmp_path / "9919.json").read_text(encoding="utf-8"))
    assert "list_status" not in raw
    assert "num_episodes_watched" not in raw
    assert raw["studios"] == ["A-1 Pictures"]


def test_cache_needs_enrichment_when_studios_missing(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    path = tmp_path / "42.json"
    path.write_text(
        json.dumps(
            {
                "mal_id": 42,
                "title": "Old",
                "genres": ["Action"],
                "details_enriched": True,
                "related_anime": [{"mal_id": 1, "title": "X", "relation_type": "sequel"}],
            }
        ),
        encoding="utf-8",
    )
    assert mal_mod.cache_needs_enrichment(42) is True

    path.write_text(
        json.dumps(
            {
                "mal_id": 42,
                "title": "Old",
                "genres": ["Action"],
                "studios": ["Bones"],
                "details_enriched": True,
                "related_anime": [{"mal_id": 1, "title": "X", "relation_type": "sequel"}],
            }
        ),
        encoding="utf-8",
    )
    assert mal_mod.cache_needs_enrichment(42) is False


def test_load_cached_anime_reads_studios(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    (tmp_path / "7.json").write_text(
        json.dumps(
            {
                "mal_id": 7,
                "title": "Cached",
                "genres": ["Drama"],
                "studios": ["Studio Ghibli", {"name": "Ignored-dict-ok"}],
                "num_episodes": 1,
            }
        ),
        encoding="utf-8",
    )
    entry = mal_mod.load_cached_anime(7)
    assert entry is not None
    assert "Studio Ghibli" in entry.studios
    assert "Ignored-dict-ok" in entry.studios
