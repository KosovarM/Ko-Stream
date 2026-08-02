"""Display-title preference helpers (EN / JP) with fallbacks.

Leftover ``ger`` preferences (removed from UI) normalize to English.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

TITLE_LANG_EN = "en"
TITLE_LANG_JP = "jp"
TITLE_LANG_GER = "ger"  # legacy preference key only
SUPPORTED_TITLE_LANGS = frozenset({TITLE_LANG_EN, TITLE_LANG_JP})
DEFAULT_TITLE_LANG = TITLE_LANG_EN
TITLE_LANG_LABELS = {
    TITLE_LANG_JP: "Japanese",
    TITLE_LANG_EN: "English",
}


@dataclass(frozen=True)
class TitleVariants:
    """Known title strings for one series (any source)."""

    en: str | None = None
    jp: str | None = None
    ger: str | None = None
    romaji: str | None = None
    default: str | None = None
    synonyms: tuple[str, ...] = ()


def normalize_title_lang(value: str | None) -> str:
    v = (value or "").strip().casefold()
    if v in ("ger", "de", "deu", "deutsch", "german"):
        return DEFAULT_TITLE_LANG
    if v in SUPPORTED_TITLE_LANGS:
        return v
    return DEFAULT_TITLE_LANG


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def pick_display_title(variants: TitleVariants, pref: str | None = None) -> str:
    """Pick a display title: preferred → en → jp → romaji → default → synonyms."""
    want = normalize_title_lang(pref)
    preferred_chain: list[str | None] = []
    if want == TITLE_LANG_EN:
        preferred_chain.append(variants.en)
    elif want == TITLE_LANG_JP:
        preferred_chain.append(variants.jp)
        preferred_chain.append(variants.romaji)

    preferred_chain.extend(
        [
            variants.en,
            variants.jp,
            variants.romaji,
            variants.default,
            *variants.synonyms,
        ]
    )
    seen: set[str] = set()
    for candidate in preferred_chain:
        cleaned = _clean(candidate)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        return cleaned
    return "Unknown"


def all_searchable_titles(variants: TitleVariants) -> list[str]:
    """Unique title strings for search matching (any language / synonym)."""
    out: list[str] = []
    seen: set[str] = set()
    for candidate in (
        variants.en,
        variants.jp,
        variants.ger,
        variants.romaji,
        variants.default,
        *variants.synonyms,
    ):
        cleaned = _clean(candidate)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def merge_title_variants(*parts: TitleVariants | None) -> TitleVariants:
    """Merge variants; first non-empty field wins per language."""
    en = jp = ger = romaji = default = None
    synonyms: list[str] = []
    seen_syn: set[str] = set()
    for part in parts:
        if part is None:
            continue
        if en is None:
            en = _clean(part.en)
        if jp is None:
            jp = _clean(part.jp)
        if ger is None:
            ger = _clean(part.ger)
        if romaji is None:
            romaji = _clean(part.romaji)
        if default is None:
            default = _clean(part.default)
        for syn in part.synonyms:
            cleaned = _clean(syn)
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key in seen_syn:
                continue
            seen_syn.add(key)
            synonyms.append(cleaned)
    return TitleVariants(
        en=en,
        jp=jp,
        ger=ger,
        romaji=romaji,
        default=default,
        synonyms=tuple(synonyms),
    )


def variants_from_mal_fields(
    *,
    title: str | None,
    title_en: str | None = None,
    title_ja: str | None = None,
    title_ger: str | None = None,
    synonyms: Iterable[str] | None = None,
) -> TitleVariants:
    syn = tuple(s for s in (_clean(x) for x in (synonyms or ())) if s)
    return TitleVariants(
        en=_clean(title_en),
        jp=_clean(title_ja),
        ger=_clean(title_ger),
        default=_clean(title),
        synonyms=syn,
    )


def variants_from_anilist_fields(
    *,
    title: str | None = None,
    english: str | None = None,
    romaji: str | None = None,
    native: str | None = None,
) -> TitleVariants:
    return TitleVariants(
        en=_clean(english),
        jp=_clean(native),
        romaji=_clean(romaji),
        default=_clean(title) or _clean(english) or _clean(romaji) or _clean(native),
    )


def resolve_title_language(explicit: str | None = None) -> str:
    """Resolve preference from an explicit value or the request ``g`` context."""
    if explicit is not None:
        return normalize_title_lang(explicit)
    try:
        from flask import g, has_request_context
    except ImportError:
        return DEFAULT_TITLE_LANG
    if has_request_context() and hasattr(g, "title_language"):
        return normalize_title_lang(getattr(g, "title_language", None))
    return DEFAULT_TITLE_LANG
