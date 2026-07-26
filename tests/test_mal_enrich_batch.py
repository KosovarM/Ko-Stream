from kostream.mal import MalAnimeEntry, enrich_mal_details, write_cached_anime
from kostream.models import RelatedAnime


def test_enrich_skips_already_related(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod, "ensure_episode_titles", lambda *_a, **_k: False)
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


def test_enrich_still_fetches_episode_titles_when_relation_batch_full(tmp_path, monkeypatch):
    """Relation enrich must not consume the entire budget for episode titles."""
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)

    # Id 1 already has relations but no episode titles.
    write_cached_anime(
        MalAnimeEntry(
            mal_id=1,
            title="Has relations",
            synopsis="",
            poster_url=None,
            genres=[],
            num_episodes=12,
            list_status="watching",
            num_episodes_watched=0,
            anime_status="finished_airing",
            score=0,
            mean_score=None,
            related_anime=[RelatedAnime(99, "Other", "sequel")],
        )
    )
    # Ids 2..11 need relation enrich — fill a limit=10 batch.
    for mid in range(2, 12):
        write_cached_anime(
            MalAnimeEntry(
                mal_id=mid,
                title=f"Needs {mid}",
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

    title_calls: list[int] = []

    def fake_merge(token, mal_id, title_fallback=None):
        return mal_mod.load_cached_anime(mal_id)

    def fake_ensure(mal_id, *, force=False):
        title_calls.append(mal_id)
        return mal_id == 1

    monkeypatch.setattr(mal_mod, "merge_anime_details_into_cache", fake_merge)
    monkeypatch.setattr(mal_mod, "ensure_episode_titles", fake_ensure)

    count = enrich_mal_details("token", set(range(1, 12)), limit=10)
    assert 1 in title_calls
    assert count >= 11  # 10 relation merges + at least id 1 titles
