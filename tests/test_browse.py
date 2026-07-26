from kostream.browse import PAGE_SIZE, collect_genres, filter_shows, paginate
from kostream.models import Show


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
