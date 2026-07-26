from kostream.mal import _parse_related_anime


def test_parse_related_anime():
    node = {
        "related_anime": [
            {
                "node": {"id": 1, "title": "Prequel Show"},
                "relation_type": "prequel",
            },
            {
                "node": {"id": 2, "title": "Sequel Show"},
                "relation_type": "sequel",
            },
            {
                "node": {"id": 3, "title": "Spinoff"},
                "relation_type": "side_story",
            },
        ]
    }
    related = _parse_related_anime(node)
    assert len(related) == 3
    assert related[0].mal_id == 1
    assert related[0].relation_type == "prequel"
