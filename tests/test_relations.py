from kostream.models import RelatedAnime, Show
from kostream.relations import build_relation_links, mal_anime_url


def test_build_relation_links_internal():
    show = Show(
        id="mal-2",
        title="Season 2",
        description="",
        mal_id=2,
        related_anime=[
            RelatedAnime(mal_id=1, title="Season 1", relation_type="prequel"),
            RelatedAnime(mal_id=3, title="Season 3", relation_type="sequel"),
        ],
    )
    links = build_relation_links(show, {1: "mal-1", 2: "mal-2", 3: "mal-3"}, lambda sid: f"/show/{sid}")
    assert len(links) == 2
    assert links[0].kind == "prequel"
    assert links[0].href == "/show/mal-1"
    assert links[0].external is False
    assert links[1].kind == "sequel"
    assert links[1].href == "/show/mal-3"


def test_build_relation_links_external_when_not_in_catalog():
    show = Show(
        id="mal-2",
        title="Season 2",
        description="",
        mal_id=2,
        related_anime=[RelatedAnime(mal_id=3, title="Season 3", relation_type="sequel")],
    )
    links = build_relation_links(show, {2: "mal-2"}, lambda sid: f"/show/{sid}")
    assert len(links) == 1
    assert links[0].external is True
    assert links[0].href == mal_anime_url(3)


def test_build_relation_links_ignores_other_relation_types():
    show = Show(
        id="mal-1",
        title="Main",
        description="",
        related_anime=[
            RelatedAnime(mal_id=9, title="Side Story", relation_type="side_story"),
            RelatedAnime(mal_id=2, title="Part 2", relation_type="sequel"),
        ],
    )
    links = build_relation_links(show, {}, lambda sid: f"/show/{sid}")
    assert len(links) == 1
    assert links[0].kind == "sequel"
