"""Media request wishlist — track titles with incomplete local files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kostream.browse import KIND_ANIMES, KIND_MOVIES, KIND_SPECIALS, classify_show_kind
from kostream.jsonio import atomic_write_json
from kostream.manga import MangaTitle
from kostream.manga_progress import total_chapters_target
from kostream.models import Show, is_local_file_episode

REQUESTS_FILE = Path(__file__).resolve().parents[2] / "data" / "requests.json"

KIND_SERIES = "series"
KIND_MOVIE = "movie"
KIND_SPECIAL = "special"
KIND_MANGA = "manga"
KIND_MANHWA = "manhwa"

KIND_LABELS = {
    KIND_SERIES: "Series",
    KIND_MOVIE: "Movies",
    KIND_SPECIAL: "Specials",
    KIND_MANGA: "Manga",
    KIND_MANHWA: "Manhwa",
}

_SHOW_KIND_MAP = {
    KIND_ANIMES: KIND_SERIES,
    KIND_MOVIES: KIND_MOVIE,
    KIND_SPECIALS: KIND_SPECIAL,
}

_VALID_KINDS = frozenset(KIND_LABELS)


def request_key(kind: str, media_id: str) -> str:
    return f"{normalize_kind(kind)}:{media_id.strip()}"


def normalize_kind(value: str | None) -> str:
    v = (value or "").strip().casefold()
    if v in ("animes", "anime", "tv", "series"):
        return KIND_SERIES
    if v in ("movies", "film"):
        return KIND_MOVIE
    if v in ("specials",):
        return KIND_SPECIAL
    if v in _VALID_KINDS:
        return v
    return KIND_SERIES


def kind_for_show(show: Show) -> str:
    return _SHOW_KIND_MAP.get(classify_show_kind(show), KIND_SERIES)


def kind_for_manga(manga: MangaTitle, *, library_kind: str | None = None) -> str:
    if library_kind in (KIND_MANGA, KIND_MANHWA):
        return library_kind
    if manga.is_manhwa:
        return KIND_MANHWA
    return KIND_MANGA


def show_local_counts(
    show: Show,
    local_info: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """Return (local_count, expected_count) for a show."""
    if local_info and isinstance(local_info.get("episodes"), list):
        episodes = local_info["episodes"]
        local_count = sum(1 for ep in episodes if ep.get("is_local"))
        expected = max(len(episodes), show.episode_count or 0)
        return local_count, expected
    local_count = sum(1 for ep in show.episodes if is_local_file_episode(ep))
    expected = max(len(show.episodes), show.episode_count or 0)
    return local_count, expected


def show_is_locally_complete(
    show: Show,
    local_info: dict[str, Any] | None = None,
) -> bool:
    """True when local file count meets/exceeds the expected episode total."""
    local_count, expected = show_local_counts(show, local_info)
    if expected <= 0:
        return False
    return local_count >= expected


def show_needs_request(
    show: Show,
    local_info: dict[str, Any] | None = None,
) -> bool:
    """True when the Request button should be offered.

    Incomplete non-airing titles are eligible. Currently airing TV is eligible
    only when there is not a single local episode (partial airing downloads are
    expected and should not prompt a request).
    """
    from kostream.watch_progress import is_currently_airing

    local_count, expected = show_local_counts(show, local_info)
    if is_currently_airing(show) and local_count > 0:
        return False
    if show_is_locally_complete(show, local_info):
        return False
    if expected <= 0:
        return True
    return local_count < expected


def manga_local_counts(manga: MangaTitle) -> tuple[int, int]:
    local_count = manga.chapter_count
    expected = total_chapters_target(manga)
    return local_count, expected


def manga_is_locally_complete(manga: MangaTitle) -> bool:
    """True when local chapter count meets/exceeds the expected total."""
    local_count, expected = manga_local_counts(manga)
    if expected <= 0:
        # Unknown total: treat any local chapters as satisfied (matches needs_request).
        return bool(manga.has_local)
    return local_count >= expected


def manga_needs_request(manga: MangaTitle) -> bool:
    local_count, expected = manga_local_counts(manga)
    if expected <= 0:
        return not manga.has_local
    return local_count < expected


def is_open_request(row: dict[str, Any]) -> bool:
    """True when the request has not been manually fulfilled."""
    return not row.get("fulfilled_at")


def open_requests(path: Path | None = None) -> list[dict[str, Any]]:
    """Open (unfulfilled) requests only."""
    return [row for row in load_requests(path) if is_open_request(row)]


def has_request(kind: str, media_id: str, path: Path | None = None) -> bool:
    """True when this title is already in the open requests list."""
    media_id = (media_id or "").strip()
    if not media_id:
        return False
    kind_n = normalize_kind(kind)
    key = request_key(kind_n, media_id)
    for row in open_requests(path):
        if row.get("id") == key:
            return True
        if normalize_kind(str(row.get("kind") or "")) == kind_n and row.get("media_id") == media_id:
            return True
    return False


def requested_ids(path: Path | None = None) -> set[str]:
    """Set of request id keys (`kind:media_id`) currently open."""
    return {
        str(row.get("id") or request_key(str(row.get("kind") or ""), str(row.get("media_id") or "")))
        for row in open_requests(path)
        if row.get("media_id")
    }


def clear_fulfilled_requests(
    *,
    path: Path | None = None,
    media_root: Path | None = None,
    catalog_path: Path | None = None,
    manga_root: Path | None = None,
    manga_catalog_path: Path | None = None,
    scope: str = "all",
) -> int:
    """Drop requests whose media is now fully available locally. Returns removed count.

    ``scope``: ``\"all\"`` | ``\"anime\"`` (series/movie/special) | ``\"manga\"``.
    """
    items = load_requests(path)
    if not items:
        return 0

    show_kinds = {KIND_SERIES, KIND_MOVIE, KIND_SPECIAL}
    manga_kinds = {KIND_MANGA, KIND_MANHWA}
    scope_n = (scope or "all").strip().casefold()
    if scope_n in ("anime", "animes", "show", "shows"):
        allow_kinds = show_kinds
    elif scope_n in ("manga", "mangas", "manhwa"):
        allow_kinds = manga_kinds
    else:
        allow_kinds = show_kinds | manga_kinds
    open_items = [r for r in items if is_open_request(r)]
    need_shows = show_kinds & allow_kinds and any(
        normalize_kind(str(r.get("kind") or "")) in show_kinds for r in open_items
    )
    need_manga = manga_kinds & allow_kinds and any(
        normalize_kind(str(r.get("kind") or "")) in manga_kinds for r in open_items
    )

    shows_by_id: dict[str, Show] = {}
    manga_by_id: dict[str, MangaTitle] = {}

    if need_shows:
        from kostream.library import MEDIA_ROOT, scan_library

        root = media_root if media_root is not None else MEDIA_ROOT
        for show in scan_library(root, catalog_path):
            shows_by_id[show.id] = show

    if need_manga:
        from kostream.manga import MANGA_ROOT, load_manga_library

        mroot = manga_root if manga_root is not None else MANGA_ROOT
        for title in load_manga_library(mroot, manga_catalog_path):
            manga_by_id[title.id] = title

    kept: list[dict[str, Any]] = []
    removed = 0
    for row in items:
        if not is_open_request(row):
            kept.append(row)
            continue
        kind = normalize_kind(str(row.get("kind") or ""))
        media_id = str(row.get("media_id") or "").strip()
        if kind not in allow_kinds:
            kept.append(row)
            continue
        fulfilled = False
        if kind in show_kinds and media_id:
            show = shows_by_id.get(media_id)
            if show is not None and show_is_locally_complete(show):
                fulfilled = True
        elif kind in manga_kinds and media_id:
            manga = manga_by_id.get(media_id)
            if manga is not None and manga_is_locally_complete(manga):
                fulfilled = True
        if fulfilled:
            removed += 1
        else:
            kept.append(row)

    if removed:
        save_requests(kept, path)
    return removed


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_requests(path: Path | None = None) -> list[dict[str, Any]]:
    file_path = path or REQUESTS_FILE
    if not file_path.is_file():
        return []
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        items = raw.get("requests")
        if isinstance(items, list):
            return [r for r in items if isinstance(r, dict)]
    return []


def save_requests(items: list[dict[str, Any]], path: Path | None = None) -> None:
    file_path = path or REQUESTS_FILE
    payload = {"requests": items}
    atomic_write_json(file_path, payload, ensure_ascii=False)


def upsert_request(
    *,
    kind: str,
    media_id: str,
    title: str,
    path: Path | None = None,
    mal_id: int | None = None,
    poster_url: str | None = None,
    type_label: str | None = None,
    local_count: int | None = None,
    expected_count: int | None = None,
    requester_id: str | None = None,
    requester_username: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Insert or refresh a request. Returns (entry, created)."""
    media_id = (media_id or "").strip()
    if not media_id:
        raise ValueError("media_id required")
    kind_n = normalize_kind(kind)
    key = request_key(kind_n, media_id)
    now = _utc_now()
    items = load_requests(path)
    for existing in items:
        if existing.get("id") == key or (
            existing.get("kind") == kind_n and existing.get("media_id") == media_id
        ):
            was_fulfilled = bool(existing.get("fulfilled_at"))
            existing["id"] = key
            existing["kind"] = kind_n
            existing["media_id"] = media_id
            existing["title"] = title or existing.get("title") or media_id
            if mal_id is not None:
                existing["mal_id"] = mal_id
            if poster_url is not None:
                existing["poster_url"] = poster_url
            if type_label is not None:
                existing["type_label"] = type_label
            if local_count is not None:
                existing["local_count"] = int(local_count)
            if expected_count is not None:
                existing["expected_count"] = int(expected_count)
            existing["updated_at"] = now
            if not existing.get("created_at"):
                existing["created_at"] = now
            if was_fulfilled:
                existing["fulfilled_at"] = None
                existing["fulfilled_by"] = None
                if requester_id is not None:
                    existing["requester_id"] = requester_id
                if requester_username is not None:
                    existing["requester_username"] = requester_username
            elif not existing.get("requester_id") and requester_id is not None:
                existing["requester_id"] = requester_id
                if requester_username is not None:
                    existing["requester_username"] = requester_username
            save_requests(items, path)
            return existing, was_fulfilled

    entry: dict[str, Any] = {
        "id": key,
        "kind": kind_n,
        "media_id": media_id,
        "title": title or media_id,
        "created_at": now,
        "updated_at": now,
        "requester_id": requester_id,
        "requester_username": requester_username,
        "fulfilled_at": None,
        "fulfilled_by": None,
    }
    if mal_id is not None:
        entry["mal_id"] = mal_id
    if poster_url:
        entry["poster_url"] = poster_url
    if type_label:
        entry["type_label"] = type_label
    if local_count is not None:
        entry["local_count"] = int(local_count)
    if expected_count is not None:
        entry["expected_count"] = int(expected_count)
    items.append(entry)
    save_requests(items, path)
    return entry, True


def fulfill_request(
    request_id: str,
    *,
    fulfilled_by: str,
    path: Path | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """Mark an open request fulfilled.

    Returns ``(entry, newly_fulfilled)``. ``entry`` is None when not found.
    ``newly_fulfilled`` is True only when this call set ``fulfilled_at``.
    """
    rid = (request_id or "").strip()
    by = (fulfilled_by or "").strip()
    if not rid or not by:
        return None, False
    items = load_requests(path)
    now = _utc_now()
    for row in items:
        if row.get("id") != rid:
            continue
        if not is_open_request(row):
            return row, False
        row["fulfilled_at"] = now
        row["fulfilled_by"] = by
        row["updated_at"] = now
        save_requests(items, path)
        return row, True
    return None, False


def remove_request(request_id: str, path: Path | None = None) -> bool:
    rid = (request_id or "").strip()
    if not rid:
        return False
    items = load_requests(path)
    kept = [r for r in items if r.get("id") != rid]
    if len(kept) == len(items):
        # Also allow media_id-only delete when unique
        kept = [r for r in items if r.get("media_id") != rid]
        if len(kept) == len(items):
            return False
    save_requests(kept, path)
    return True


def group_requests(items: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    rows = items if items is not None else open_requests()
    grouped: dict[str, list[dict[str, Any]]] = {k: [] for k in KIND_LABELS}
    for row in rows:
        kind = normalize_kind(str(row.get("kind") or ""))
        grouped.setdefault(kind, []).append(row)
    for kind in grouped:
        grouped[kind].sort(
            key=lambda r: (str(r.get("title") or "").casefold(), str(r.get("id") or ""))
        )
    return grouped
