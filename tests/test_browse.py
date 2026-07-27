from kostream.browse import (
    AVAIL_LOCAL,
    AVAIL_STREAM,
    KIND_ANIMES,
    KIND_MOVIES,
    KIND_SPECIALS,
    PAGE_SIZE,
    classify_show_kind,
    collect_genres,
    filter_by_kind,
    filter_shows,
    format_type_label,
    normalize_availability,
    normalize_browse_kind,
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


def test_format_type_label():
    assert format_type_label(None) == "TV"
    assert format_type_label("tv") == "TV"
    assert format_type_label("movie") == "Movie"
    assert format_type_label("ova") == "OVA"
    assert format_type_label("tv_special") == "TV Special"


def test_classify_show_kind_three_way():
    tv = Show(id="tv", title="TV", description="", media_type="tv", type_label="TV")
    movie = Show(id="m", title="Film", description="", media_type="movie", type_label="Movie")
    ova = Show(id="o", title="OVA", description="", media_type="ova", type_label="OVA")
    special = Show(id="s", title="Sp", description="", media_type="special", type_label="Special")
    ona = Show(id="n", title="ONA", description="", media_type="ona", type_label="ONA")
    music = Show(id="mu", title="OP", description="", media_type="music", type_label="Music")
    missing = Show(id="x", title="Unknown", description="")  # default type_label TV
    weird = Show(id="w", title="Weird", description="", media_type="something_new")

    assert classify_show_kind(tv) == KIND_ANIMES
    assert classify_show_kind(movie) == KIND_MOVIES
    assert classify_show_kind(ova) == KIND_SPECIALS
    assert classify_show_kind(special) == KIND_SPECIALS
    assert classify_show_kind(ona) == KIND_SPECIALS
    assert classify_show_kind(music) == KIND_SPECIALS
    assert classify_show_kind(missing) == KIND_ANIMES
    assert classify_show_kind(weird) == KIND_ANIMES  # unknown → main list


def test_filter_by_kind_mutually_exclusive():
    shows = [
        Show(id="tv", title="A", description="", media_type="tv"),
        Show(id="movie", title="B", description="", media_type="movie"),
        Show(id="ova", title="C", description="", media_type="ova"),
        Show(id="unknown", title="D", description=""),
    ]
    animes = filter_by_kind(shows, KIND_ANIMES)
    movies = filter_by_kind(shows, KIND_MOVIES)
    specials = filter_by_kind(shows, KIND_SPECIALS)
    assert {s.id for s in animes} == {"tv", "unknown"}
    assert {s.id for s in movies} == {"movie"}
    assert {s.id for s in specials} == {"ova"}
    # No overlap
    ids = [s.id for s in animes + movies + specials]
    assert len(ids) == len(set(ids)) == len(shows)


def test_normalize_browse_kind():
    assert normalize_browse_kind(None) == KIND_ANIMES
    assert normalize_browse_kind("movies") == KIND_MOVIES
    assert normalize_browse_kind("SPECIALS") == KIND_SPECIALS
    assert normalize_browse_kind("nope") == KIND_ANIMES


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
