from kostream.mal import MalAnimeEntry, enrich_mal_details, write_cached_anime
from kostream.models import RelatedAnime


def test_enrich_skips_already_related(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    write_cached_anime(
        MalAnimeEntry(
            mal_id=1,
            title="Done",
            synopsis="",
            poster_url=None,
            genres=[],
            num_episodes=12,
            list_status="watching",
            num_episodes_watched=0,
            anime_status="finished_airing",
            score=0,
            mean_score=None,
            related_anime=[RelatedAnime(2, "Sequel", "sequel")],
        )
    )
    write_cached_anime(
        MalAnimeEntry(
            mal_id=2,
            title="Needs",
            synopsis="",
            poster_url=None,
            genres=[],
            num_episodes=12,
            list_status="watching",
            num_episodes_watched=0,
            anime_status="finished_airing",
            score=0,
            mean_score=None,
            related_anime=[],
        )
    )

    calls: list[int] = []

    def fake_merge(token, mal_id, title_fallback=None):
        calls.append(mal_id)
        return mal_mod.load_cached_anime(mal_id)

    monkeypatch.setattr(mal_mod, "merge_anime_details_into_cache", fake_merge)
    count = enrich_mal_details("token", {1, 2}, limit=10)
    assert calls == [2]
    assert count == 1
