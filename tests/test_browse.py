from kostream.browse import (
    AVAIL_LOCAL,
    AVAIL_STREAM,
    PAGE_SIZE,
    collect_genres,
    filter_shows,
    normalize_availability,
    paginate,
)
from kostream.models import Episode, Show


def _shows(count: int, genre: str = "Action") -> list[Show]:
    return [
        Show(
            id=f"show-{i}",
            title=f"Anime {i}",
            description=f"Description for anime {i}",
            genres=[genre, "MAL"],
        )
        for i in range(count)
    ]


def _local_show(show_id: str, title: str) -> Show:
    return Show(
        id=show_id,
        title=title,
        description="has files",
        episodes=[Episode(f"{show_id}-1", show_id, 1, 1, "EP1", "S01E01.mp4")],
    )


def _stream_show(show_id: str, title: str) -> Show:
    return Show(
        id=show_id,
        title=title,
        description="stream placeholder",
        episodes=[Episode(f"{show_id}-1", show_id, 1, 1, "EP1", "demo.mp4")],
    )


def test_collect_genres_excludes_meta_tags():
    shows = [
        Show(id="a", title="A", description="", genres=["Action", "MAL", "Local"]),
        Show(id="b", title="B", description="", genres=["Fantasy", "Demo"]),
    ]
    assert collect_genres(shows) == ["Action", "Fantasy"]


def test_filter_shows_by_query_and_genre():
    shows = [
        Show(id="a", title="One Piece", description="pirates", genres=["Action"]),
        Show(id="b", title="Frieren", description="mage", genres=["Fantasy"]),
        Show(id="c", title="Naruto", description="ninja action", genres=["Action"]),
    ]
    assert len(filter_shows(shows, query="piece")) == 1
    assert len(filter_shows(shows, genre="Action")) == 2
    assert len(filter_shows(shows, query="ninja", genre="Action")) == 1


def test_filter_shows_by_availability():
    shows = [
        _local_show("local-1", "Local A"),
        _stream_show("stream-1", "Stream B"),
        Show(id="empty-1", title="Empty C", description="no episodes"),
        Show(
            id="mixed-1",
            title="Mixed D",
            description="local + stream",
            episodes=[
                Episode("m1", "mixed-1", 1, 1, "EP1", "S01E01.mp4"),
                Episode("m2", "mixed-1", 1, 2, "EP2", "demo.mp4"),
            ],
        ),
    ]
    local = filter_shows(shows, availability=AVAIL_LOCAL)
    stream = filter_shows(shows, availability=AVAIL_STREAM)
    assert [s.id for s in local] == ["local-1", "mixed-1"]
    assert [s.id for s in stream] == ["empty-1", "stream-1"]
    assert len(filter_shows(shows, availability="all")) == 4


def test_normalize_availability():
    assert normalize_availability(None) == "all"
    assert normalize_availability("LOCAL") == "local"
    assert normalize_availability("stream") == "stream"
    assert normalize_availability("nope") == "all"


def test_paginate_25_per_page():
    shows = _shows(30)
    page1, p, total = paginate(shows, 1, PAGE_SIZE)
    assert len(page1) == 25
    assert p == 1
    assert total == 2

    page2, p2, _ = paginate(shows, 2, PAGE_SIZE)
    assert len(page2) == 5
    assert p2 == 2


def test_paginate_empty():
    items, page, total = paginate([], 1)
    assert items == []
    assert page == 1
    assert total == 1
