"""MAL start_date → release year parsing."""

from kostream.mal import parse_mal_start_year


def test_parse_year_from_node():
    assert parse_mal_start_year({"start_date": {"year": 2011, "month": 10, "day": 3}}) == 2011


def test_parse_year_from_start_date_object():
    assert parse_mal_start_year({"year": 1999}) == 1999


def test_parse_year_from_mal_date_string():
    assert parse_mal_start_year({"start_date": "2011-07-22"}) == 2011
    assert parse_mal_start_year({"start_date": "2017-10"}) == 2017
    assert parse_mal_start_year({"start_date": "2007"}) == 2007


def test_parse_year_from_start_season():
    assert parse_mal_start_year({"start_season": {"year": 2006, "season": "spring"}}) == 2006
    assert parse_mal_start_year({"start_date": "", "start_season": {"year": 1998}}) == 1998


def test_parse_year_missing_or_invalid():
    assert parse_mal_start_year(None) is None
    assert parse_mal_start_year({}) is None
    assert parse_mal_start_year({"start_date": {}}) is None
    assert parse_mal_start_year({"start_date": {"year": 1800}}) is None
    assert parse_mal_start_year({"start_date": "not-a-date"}) is None
