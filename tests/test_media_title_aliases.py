from kostream.media_title_aliases import (
    entry_match_keys,
    folder_match_keys,
    match_score,
    normalize_search_query,
)


def test_normalize_search_query_fixes_jojos():
    q = normalize_search_query("JoJos Bizarre Adventure Golden Wind")
    assert "JoJo" in q
    assert "golden wind" in q.casefold()


def test_english_folder_matches_japanese_mal_title():
    folder_keys = folder_match_keys("JoJos Bizarre Adventure Golden Wind")
    entry_keys = entry_match_keys(
        "JoJo no Kimyou na Bouken Part 5: Ougon no Kaze",
        mal_id=37991,
    )
    assert match_score(folder_keys, entry_keys) >= 0.45


def test_stone_ocean_part_3_alias():
    folder_keys = folder_match_keys("JoJos Bizarre Adventure Stone Ocean Part 3")
    entry_keys = entry_match_keys(
        "JoJo no Kimyou na Bouken Part 6: Stone Ocean Part 3",
        mal_id=53273,
    )
    assert "53273" in folder_keys
    assert match_score(folder_keys, entry_keys) >= 0.45
