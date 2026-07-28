"""Title language preference and display fallbacks."""

from __future__ import annotations

from pathlib import Path

from kostream.titles import (
    TitleVariants,
    all_searchable_titles,
    normalize_title_lang,
    pick_display_title,
)
from kostream.user_settings import get_title_language, set_title_language
from kostream.browse import filter_shows
from kostream.models import Show


def test_normalize_title_lang():
    assert normalize_title_lang("jp") == "jp"
    assert normalize_title_lang("EN") == "en"
    assert normalize_title_lang("ger") == "ger"
    assert normalize_title_lang("de") == "en"
    assert normalize_title_lang(None) == "en"


def test_pick_display_title_fallback_order():
    variants = TitleVariants(
        en="Attack on Titan",
        jp="進撃の巨人",
        romaji="Shingeki no Kyojin",
        default="Shingeki no Kyojin",
        synonyms=("AoT",),
    )
    assert pick_display_title(variants, "en") == "Attack on Titan"
    assert pick_display_title(variants, "jp") == "進撃の巨人"
    # German missing → English
    assert pick_display_title(variants, "ger") == "Attack on Titan"

    no_en = TitleVariants(jp="進撃の巨人", romaji="Shingeki no Kyojin", default="Shingeki no Kyojin")
    assert pick_display_title(no_en, "en") == "進撃の巨人"
    assert pick_display_title(no_en, "ger") == "進撃の巨人"


def test_search_matches_aliases_not_only_display_title():
    shows = [
        Show(
            id="a",
            title="Attack on Titan",
            description="",
            title_aliases=["Attack on Titan", "進撃の巨人", "Shingeki no Kyojin"],
        )
    ]
    assert len(filter_shows(shows, query="shingeki")) == 1
    assert len(filter_shows(shows, query="進撃")) == 1
    assert len(filter_shows(shows, query="missing")) == 0


def test_user_settings_title_language(tmp_path: Path):
    path = tmp_path / "settings.json"
    assert get_title_language(path) == "en"
    assert set_title_language(path, "ger") == "ger"
    assert get_title_language(path) == "ger"
    titles = all_searchable_titles(
        TitleVariants(ger="Angriff auf Titan", en="Attack on Titan")
    )
    assert "Angriff auf Titan" in titles
    assert "Attack on Titan" in titles
