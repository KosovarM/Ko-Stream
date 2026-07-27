"""Browse/search helpers — grid pagination, kind filters, and MAL genre filtering."""

from __future__ import annotations

from kostream.models import Show

META_GENRES = frozenset({"Local", "Demo", "Catalog", "MAL"})
PAGE_SIZE = 25
GRID_COLS = 5
AVAIL_ALL = "all"
AVAIL_LOCAL = "local"
AVAIL_STREAM = "stream"
AVAIL_OPTIONS = frozenset({AVAIL_ALL, AVAIL_LOCAL, AVAIL_STREAM})
AVAIL_COOKIE = "kostream_avail"
AVAIL_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year

# Browse subcategories (mutually exclusive)
KIND_ANIMES = "animes"  # Hauptanimes — TV (+ unknown/missing)
KIND_MOVIES = "movies"
KIND_SPECIALS = "specials"  # OVA, Special, ONA, Music, …
KIND_OPTIONS = frozenset({KIND_ANIMES, KIND_MOVIES, KIND_SPECIALS})

KIND_LABELS = {
    KIND_ANIMES: "Animes",
    KIND_MOVIES: "Movies",
    KIND_SPECIALS: "Specials",
}

_TYPE_LABELS = {
    "tv": "TV",
    "movie": "Movie",
    "ova": "OVA",
    "ona": "ONA",
    "special": "Special",
    "tv_special": "TV Special",
    "music": "Music",
    "pv": "PV",
    "cm": "CM",
}

# Strict MAL movie types
_MOVIE_TYPES = frozenset({"movie", "film"})
# Primary series list — TV only when type is known
_TV_TYPES = frozenset({"tv"})
# Non-TV / non-Movie extras
_SPECIAL_TYPES = frozenset({
    "ova",
    "ona",
    "special",
    "tv_special",
    "music",
    "pv",
    "cm",
})


def normalize_availability(value: str | None) -> str:
    v = (value or "").strip().casefold()
    if v in AVAIL_OPTIONS:
        return v
    return AVAIL_ALL


def resolve_request_availability(
    *,
    has_avail_param: bool,
    avail_param: str | None,
    cookie_value: str | None,
) -> tuple[str, bool]:
    """Return ``(availability, should_set_cookie)`` for anime browse routes.

    Query ``avail`` wins and is persisted to the cookie; otherwise the cookie
    (or ``all``) is used without rewriting the cookie.
    """
    if has_avail_param:
        return normalize_availability(avail_param), True
    return normalize_availability(cookie_value), False


def normalize_browse_kind(value: str | None) -> str:
    v = (value or "").strip().casefold()
    if v in KIND_OPTIONS:
        return v
    return KIND_ANIMES


def normalize_media_type(value: str | None) -> str:
    return (value or "").strip().casefold().replace(" ", "_").replace("-", "_")


def format_type_label(media_type: str | None) -> str:
    """Human badge for cards (TV, Movie, OVA, …). Missing → TV."""
    key = normalize_media_type(media_type)
    if not key:
        return "TV"
    if key in _TYPE_LABELS:
        return _TYPE_LABELS[key]
    return key.replace("_", " ").title()


def classify_show_kind(show: Show) -> str:
    """Map a show to Animes / Movies / Specials (mutually exclusive).

    Rules (MAL ``media_type`` / ``type_label``):
    - Movies: movie (and film)
    - Specials: ova, ona, special, tv_special, music, pv, cm
    - Animes: tv, or unknown/missing type (prefer main list so nothing disappears)
    """
    raw = normalize_media_type(show.media_type)
    if not raw:
        # Fall back to display label (e.g. demos / Jellyfin default "TV")
        raw = normalize_media_type(show.type_label)
    if raw in _MOVIE_TYPES:
        return KIND_MOVIES
    if raw in _SPECIAL_TYPES:
        return KIND_SPECIALS
    # tv, empty, or unrecognized → main Animes list
    return KIND_ANIMES


def filter_by_kind(shows: list[Show], kind: str = KIND_ANIMES) -> list[Show]:
    want = normalize_browse_kind(kind)
    return [s for s in shows if classify_show_kind(s) == want]


def collect_genres(shows: list[Show]) -> list[str]:
    found: set[str] = set()
    for show in shows:
        for genre in show.genres or []:
            if genre and genre not in META_GENRES:
                found.add(genre)
    return sorted(found, key=str.casefold)


def filter_shows(
    shows: list[Show],
    query: str = "",
    genre: str = "",
    availability: str = AVAIL_ALL,
) -> list[Show]:
    result = list(shows)
    q = query.strip().casefold()
    if q:
        result = [
            s
            for s in result
            if q in s.title.casefold() or q in (s.description or "").casefold()
        ]
    g = genre.strip()
    if g:
        result = [s for s in result if g in (s.genres or [])]
    avail = normalize_availability(availability)
    if avail == AVAIL_LOCAL:
        result = [s for s in result if s.has_local_files]
    elif avail == AVAIL_STREAM:
        result = [s for s in result if s.is_stream_only]
    return sorted(result, key=lambda s: s.title.casefold())


def paginate(items: list[Show], page: int, per_page: int = PAGE_SIZE) -> tuple[list[Show], int, int]:
    total = len(items)
    if total == 0:
        return [], 1, 1
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return items[start : start + per_page], page, total_pages
