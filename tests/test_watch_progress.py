from kostream.watch_progress import (
    episode_completed,
    filter_currently_airing,
    is_currently_airing,
    next_unwatched_episode,
    recently_added,
    sort_by_mean_score,
)
from kostream.models import Episode, Show


def _show(
    *,
    episodes_watched: int = 0,
    list_status: str | None = "watching",
    anime_status: str | None = "finished_airing",
    ep_count: int = 5,
) -> Show:
    show_id = "test-show"
    return Show(
        id=show_id,
        title="Test Anime",
        description="",
        episodes_watched=episodes_watched,
        list_status=list_status,
        anime_status=anime_status,
        episodes=[
            Episode(f"{show_id}-e{n}", show_id, 1, n, f"Episode {n}", "demo.mp4")
            for n in range(1, ep_count + 1)
        ],
    )


def test_mark_episode_watched(tmp_path):
    from kostream.watch_progress import COMPLETED_FILE, load_completed, mark_episode_watched

    completed_path = tmp_path / "completed.json"
    show = _show(ep_count=5)
    ep = show.episodes[2]
    count = mark_episode_watched(show, ep, completed_path)
    assert count == 3
    assert show.episodes_watched == 3
    data = load_completed(completed_path)
    assert data[show.id] == 3


def test_episode_completed_uses_local_completed(tmp_path):
    show = _show(episodes_watched=0)
    ep = show.episodes[1]
    assert episode_completed(show, ep, completed={show.id: 2}) is True
    show = _show(episodes_watched=3)
    eps = show.episodes
    assert episode_completed(show, eps[0]) is True
    assert episode_completed(show, eps[2]) is True
    assert episode_completed(show, eps[3]) is False


def test_episode_completed_when_list_completed():
    show = _show(list_status="completed", episodes_watched=0)
    assert episode_completed(show, show.episodes[-1]) is True


def test_next_unwatched_episode():
    show = _show(episodes_watched=2)
    nxt = next_unwatched_episode(show)
    assert nxt is not None
    assert nxt.number == 3


def test_next_unwatched_none_when_all_watched():
    show = _show(list_status="completed")
    assert next_unwatched_episode(show) is None


def test_is_currently_airing():
    airing = _show(anime_status="currently_airing", list_status="watching")
    finished = _show(anime_status="finished_airing", list_status="watching")
    completed = _show(anime_status="currently_airing", list_status="completed")
    assert is_currently_airing(airing) is True
    assert is_currently_airing(finished) is False
    assert is_currently_airing(completed) is False


def test_filter_currently_airing():
    shows = [
        _show(anime_status="currently_airing", list_status="watching"),
        _show(anime_status="finished_airing", list_status="watching"),
        _show(anime_status="currently_airing", list_status="completed"),
    ]
    result = filter_currently_airing(shows)
    assert len(result) == 1
    assert result[0].anime_status == "currently_airing"


def test_recently_added_sorts_by_added_at():
    shows = [
        Show(id="old", title="Old", description="", added_at="2026-01-01T00:00:00Z"),
        Show(id="new", title="New", description="", added_at="2026-07-25T00:00:00Z"),
        Show(id="mid", title="Mid", description="", added_at="2026-03-01T00:00:00Z"),
        Show(id="none", title="None", description=""),
    ]
    result = recently_added(shows, limit=10)
    assert [s.id for s in result] == ["new", "mid", "old", "none"]


def test_sort_by_mean_score():
    shows = [
        Show(id="a", title="A", description="", mean_score=7.5),
        Show(id="b", title="B", description="", mean_score=9.1),
        Show(id="c", title="C", description=""),
    ]
    result = sort_by_mean_score(shows, limit=10)
    assert [s.id for s in result] == ["b", "a", "c"]
