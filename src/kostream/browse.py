"""Browse/search helpers — grid pagination and MAL genre filtering."""

from __future__ import annotations

from kostream.models import Show

META_GENRES = frozenset({"Local", "Demo", "Catalog", "MAL"})
PAGE_SIZE = 25
GRID_COLS = 5


def collect_genres(shows: list[Show]) -> list[str]:
    found: set[str] = set()
    for show in shows:
        for genre in show.genres or []:
            if genre and genre not in META_GENRES:
                found.add(genre)
    return sorted(found, key=str.casefold)


def filter_shows(shows: list[Show], query: str = "", genre: str = "") -> list[Show]:
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
    return sorted(result, key=lambda s: s.title.casefold())


def paginate(items: list[Show], page: int, per_page: int = PAGE_SIZE) -> tuple[list[Show], int, int]:
    total = len(items)
    if total == 0:
        return [], 1, 1
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return items[start : start + per_page], page, total_pages
