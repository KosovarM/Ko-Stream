from kostream.library import _mal_episode_display_title, _merge_mal_and_local_episodes
from kostream.models import Episode


def test_merge_uses_mal_episode_titles():
    local = [
        Episode(
            id="x-s01e01",
            show_id="x",
            season=1,
            number=1,
            title="ignored",
            filename="S01E01.mp4",
        )
    ]
    merged = _merge_mal_and_local_episodes(
        "x",
        3,
        local,
        episode_titles={1: "Asteroid Blues", 2: "Stray Dog Strut"},
    )
    assert [e.title for e in merged] == [
        "Asteroid Blues",
        "Stray Dog Strut",
        "Episode 3",
    ]
    assert merged[0].filename == "S01E01.mp4"
    assert merged[2].filename == "demo.mp4"


def test_display_title_fallback():
    assert _mal_episode_display_title(5, None) == "Episode 5"
    assert _mal_episode_display_title(5, {}) == "Episode 5"
    assert _mal_episode_display_title(5, {5: "  Ballad  "}) == "Ballad"


def test_mal_episode_count_can_exceed_300():
    from kostream.library import _mal_episode_count
    from kostream.mal import MalAnimeEntry

    cached = MalAnimeEntry(
        mal_id=21,
        title="One Piece",
        synopsis="",
        poster_url=None,
        genres=["Action"],
        num_episodes=1122,
        list_status="watching",
        num_episodes_watched=1100,
        anime_status="currently_airing",
        score=10,
        mean_score=8.7,
    )
    assert _mal_episode_count(cached) == 1122


def test_mal_episode_count_airing_extends_past_mal_total_without_cap():
    from kostream.library import _mal_episode_count
    from kostream.mal import MalAnimeEntry

    cached = MalAnimeEntry(
        mal_id=21,
        title="One Piece",
        synopsis="",
        poster_url=None,
        genres=["Action"],
        num_episodes=0,
        list_status="watching",
        num_episodes_watched=350,
        anime_status="currently_airing",
        score=10,
        mean_score=8.7,
    )
    assert _mal_episode_count(cached) == 351


def test_merge_builds_more_than_300_rows():
    merged = _merge_mal_and_local_episodes("mal-21", 450, local=[])
    assert len(merged) == 450
    assert merged[-1].number == 450
    assert merged[-1].title == "Episode 450"

