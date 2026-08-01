"""Sync skip index — track fully-synced anime/manga to avoid redundant work."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from kostream.jsonio import atomic_write_json
from kostream.models import Show

SYNC_INDEX_DIR = Path(__file__).resolve().parents[2] / "data" / "sync_index"
ANIME_INDEX_FILE = SYNC_INDEX_DIR / "animes.json"
MANGA_INDEX_FILE = SYNC_INDEX_DIR / "mangas.json"

AnimeSection = Literal["anime_sync", "episode_titles", "aniskip"]
MangaSection = Literal["manga_sync", "chapter_titles"]
IndexSection = AnimeSection | MangaSection

_SKIP_FIELD = {
    "anime_sync": "skip_anime_sync",
    "episode_titles": "skip_episode_titles",
    "aniskip": "skip_aniskip",
    "manga_sync": "skip_manga_sync",
    "chapter_titles": "skip_chapter_titles",
}

_HINT_FIELD = {
    "anime_sync": "anime_sync_hint",
    "episode_titles": "episode_titles_hint",
    "aniskip": "aniskip_hint",
    "manga_sync": "manga_sync_hint",
    "chapter_titles": "chapter_titles_hint",
}


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load_index(path: Path | None) -> dict[str, dict[str, Any]]:
    file_path = path or ANIME_INDEX_FILE
    if not file_path.exists():
        return {}
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(entries, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in entries.items():
        if isinstance(value, dict):
            out[str(key)] = dict(value)
    return out


def _save_index(path: Path | None, entries: dict[str, dict[str, Any]]) -> None:
    file_path = path or ANIME_INDEX_FILE
    payload = {"entries": entries}
    atomic_write_json(file_path, payload)


def load_anime_index(path: Path | None = None) -> dict[str, dict[str, Any]]:
    return _load_index(path or ANIME_INDEX_FILE)


def load_manga_index(path: Path | None = None) -> dict[str, dict[str, Any]]:
    return _load_index(path or MANGA_INDEX_FILE)


def save_anime_index(entries: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    _save_index(path or ANIME_INDEX_FILE, entries)


def save_manga_index(entries: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    _save_index(path or MANGA_INDEX_FILE, entries)


def should_skip(mal_id: int, section: IndexSection, *, index_path: Path | None = None) -> bool:
    """True when the index marks this mal_id as checked (skip sync). Missing file → False."""
    if section in ("anime_sync", "episode_titles", "aniskip"):
        entries = load_anime_index(index_path)
    else:
        entries = load_manga_index(index_path)
    rec = entries.get(str(int(mal_id))) or {}
    return bool(rec.get(_SKIP_FIELD[section]))


def skipped_mal_ids(section: IndexSection, *, index_path: Path | None = None) -> set[int]:
    if section in ("anime_sync", "episode_titles", "aniskip"):
        entries = load_anime_index(index_path)
    else:
        entries = load_manga_index(index_path)
    out: set[int] = set()
    field = _SKIP_FIELD[section]
    for key, rec in entries.items():
        if rec.get(field):
            try:
                out.add(int(key))
            except ValueError:
                continue
    return out


def set_skip(
    mal_id: int,
    section: IndexSection,
    skip: bool,
    *,
    index_path: Path | None = None,
) -> None:
    set_skip_bulk([mal_id], section, skip, index_path=index_path)


def set_skip_bulk(
    mal_ids: list[int],
    section: IndexSection,
    skip: bool,
    *,
    index_path: Path | None = None,
) -> int:
    """Update skip flags for many mal_ids in one read/write. Returns count updated."""
    if section in ("anime_sync", "episode_titles", "aniskip"):
        entries = load_anime_index(index_path)
        save = save_anime_index
    else:
        entries = load_manga_index(index_path)
        save = save_manga_index
    field = _SKIP_FIELD[section]
    now = _now_iso()
    skip_val = bool(skip)
    for mal_id in mal_ids:
        key = str(int(mal_id))
        rec = entries.setdefault(key, {})
        rec[field] = skip_val
        rec["updated_at"] = now
    if mal_ids:
        save(entries, index_path)
    return len(mal_ids)


def anime_sync_status(show: Show, mal_id: int) -> tuple[bool, str]:
    """Return (is_complete, hint) for anime list/progress/enrich sync."""
    from kostream.mal import _cache_needs_enrichment, load_cached_anime
    from kostream.requests_store import show_is_locally_complete, show_local_counts
    from kostream.watch_progress import is_currently_airing

    if is_currently_airing(show):
        return False, "Currently airing"
    if not show_is_locally_complete(show):
        local, expected = show_local_counts(show)
        if expected > 0:
            return False, f"Missing episodes ({local}/{expected})"
        return False, "Missing episodes"
    cached = load_cached_anime(mal_id)
    if not cached or not cached.genres:
        return False, "Missing metadata"
    if _cache_needs_enrichment(mal_id):
        return False, "Missing metadata"
    return True, "Complete"


def episode_titles_status(mal_id: int) -> tuple[bool, str]:
    from kostream.mal import episode_titles_need_fetch, load_cached_anime

    if not load_cached_anime(mal_id):
        return False, "No cache"
    if episode_titles_need_fetch(mal_id):
        return False, "Titles missing"
    return True, "Complete"


def aniskip_status(show: Show, mal_id: int) -> tuple[bool, str]:
    """Complete when every local episode number has an AniSkip cache row (may be empty)."""
    from kostream.aniskip import load_skip_times

    nums = [ep.number for ep in show.episodes if ep.number > 0]
    if not nums:
        return False, "No episodes"
    have = sum(1 for n in nums if load_skip_times(mal_id, n) is not None)
    if have < len(nums):
        return False, f"Missing skip cache ({have}/{len(nums)})"
    return True, "Complete"


def manga_sync_status(manga, mal_id: int) -> tuple[bool, str]:  # noqa: ANN001
    from kostream.mal import load_cached_manga
    from kostream.manga_progress import is_currently_publishing
    from kostream.requests_store import manga_is_locally_complete, manga_local_counts

    if is_currently_publishing(manga):
        return False, "Currently publishing"
    if not manga_is_locally_complete(manga):
        local, expected = manga_local_counts(manga)
        if expected > 0:
            return False, f"Missing chapters ({local}/{expected})"
        return False, "Missing chapters"
    cached = load_cached_manga(mal_id)
    if not cached or not cached.genres:
        return False, "Missing metadata"
    return True, "Complete"


def chapter_titles_status(mal_id: int, local_keys: set[str] | frozenset[str] | None) -> tuple[bool, str]:
    from kostream.mangadex import chapter_titles_need_fetch

    if chapter_titles_need_fetch(mal_id, local_keys=local_keys):
        return False, "Titles missing"
    return True, "Complete"


def refresh_anime_index(
    *,
    catalog_path: Path | None = None,
    media_root: Path | None = None,
    index_path: Path | None = None,
) -> int:
    """Recompute skip flags from library state. Returns number of entries updated."""
    from kostream.catalog import load_catalog
    from kostream.library import MEDIA_ROOT, scan_library

    catalog = load_catalog(catalog_path)
    root = media_root or MEDIA_ROOT
    shows = scan_library(root, catalog_path)
    show_by_mal = {int(s.mal_id): s for s in shows if s.mal_id}

    entries = load_anime_index(index_path)
    updated = 0
    for entry in catalog.shows:
        if not entry.mal_id:
            continue
        mid = int(entry.mal_id)
        key = str(mid)
        rec = entries.setdefault(key, {})
        show = show_by_mal.get(mid)
        title = (entry.title or (show.title if show else None) or f"MAL {mid}").strip()
        rec["title"] = title

        if show:
            complete, hint = anime_sync_status(show, mid)
        else:
            complete, hint = False, "No local media"
        rec["skip_anime_sync"] = complete
        rec[_HINT_FIELD["anime_sync"]] = hint

        if show and show.has_local_files:
            et_complete, et_hint = episode_titles_status(mid)
        else:
            et_complete, et_hint = False, "No local media"
        rec["skip_episode_titles"] = et_complete
        rec[_HINT_FIELD["episode_titles"]] = et_hint

        if show and show.has_local_files:
            as_complete, as_hint = aniskip_status(show, mid)
        else:
            as_complete, as_hint = False, "No local media"
        rec["skip_aniskip"] = as_complete
        rec[_HINT_FIELD["aniskip"]] = as_hint

        rec["updated_at"] = _now_iso()
        updated += 1

    save_anime_index(entries, index_path)
    return updated


def refresh_manga_index(
    *,
    manga_catalog_path: Path | None = None,
    manga_media_root: Path | None = None,
    index_path: Path | None = None,
) -> int:
    from kostream.manga import MANGA_ROOT, scan_manga_library
    from kostream.manga_catalog import load_manga_catalog, match_local_folder
    from kostream.mangadex import _local_chapter_keys

    catalog = load_manga_catalog(manga_catalog_path)
    media_root = manga_media_root or MANGA_ROOT
    local = scan_manga_library(media_root)
    local_by_folder = {t.folder: t for t in local if t.chapters}

    entries = load_manga_index(index_path)
    updated = 0
    for entry in catalog.titles:
        if not entry.mal_id:
            continue
        mid = int(entry.mal_id)
        key = str(mid)
        rec = entries.setdefault(key, {})
        folder = entry.folder
        local_title = local_by_folder.get(folder) if folder else None
        if local_title is None and entry.title:
            matched = match_local_folder(media_root, entry.title)
            if matched:
                local_title = local_by_folder.get(matched)
        title = (entry.title or (local_title.title if local_title else None) or f"MAL {mid}").strip()
        rec["title"] = title

        if local_title:
            ms_complete, ms_hint = manga_sync_status(local_title, mid)
            local_keys = _local_chapter_keys(local_title)
            ct_complete, ct_hint = chapter_titles_status(mid, local_keys)
        else:
            ms_complete, ms_hint = False, "No local chapters"
            ct_complete, ct_hint = False, "No local chapters"

        rec["skip_manga_sync"] = ms_complete
        rec[_HINT_FIELD["manga_sync"]] = ms_hint
        rec["skip_chapter_titles"] = ct_complete
        rec[_HINT_FIELD["chapter_titles"]] = ct_hint
        rec["updated_at"] = _now_iso()
        updated += 1

    save_manga_index(entries, index_path)
    return updated


def list_index_entries(
    section: IndexSection,
    *,
    catalog_path: Path | None = None,
    media_root: Path | None = None,
    manga_catalog_path: Path | None = None,
    manga_media_root: Path | None = None,
    anime_index_path: Path | None = None,
    manga_index_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Entries for UI: live hints, stored skip flags; checked first, then title."""
    skip_field = _SKIP_FIELD[section]
    rows: list[dict[str, Any]] = []

    if section in ("anime_sync", "episode_titles", "aniskip"):
        from kostream.catalog import load_catalog
        from kostream.library import MEDIA_ROOT, scan_library

        catalog = load_catalog(catalog_path)
        root = media_root or MEDIA_ROOT
        shows = scan_library(root, catalog_path)
        show_by_mal = {int(s.mal_id): s for s in shows if s.mal_id}
        entries = load_anime_index(anime_index_path)

        for entry in catalog.shows:
            if not entry.mal_id:
                continue
            mid = int(entry.mal_id)
            rec = entries.get(str(mid), {})
            show = show_by_mal.get(mid)
            title = (entry.title or (show.title if show else None) or f"MAL {mid}").strip()
            if section == "anime_sync":
                if show:
                    _, hint = anime_sync_status(show, mid)
                else:
                    hint = "No local media"
            elif section == "aniskip":
                if show and show.has_local_files:
                    _, hint = aniskip_status(show, mid)
                else:
                    hint = "No local media"
            elif show and show.has_local_files:
                _, hint = episode_titles_status(mid)
            else:
                hint = "No local media"
            rows.append(
                {
                    "mal_id": mid,
                    "title": title,
                    "skip": bool(rec.get(skip_field)),
                    "hint": hint,
                }
            )
    else:
        from kostream.manga import MANGA_ROOT, scan_manga_library
        from kostream.manga_catalog import load_manga_catalog, match_local_folder
        from kostream.mangadex import _local_chapter_keys

        catalog = load_manga_catalog(manga_catalog_path)
        media_root = manga_media_root or MANGA_ROOT
        local = scan_manga_library(media_root)
        local_by_folder = {t.folder: t for t in local if t.chapters}
        entries = load_manga_index(manga_index_path)

        for entry in catalog.titles:
            if not entry.mal_id:
                continue
            mid = int(entry.mal_id)
            rec = entries.get(str(mid), {})
            folder = entry.folder
            local_title = local_by_folder.get(folder) if folder else None
            if local_title is None and entry.title:
                matched = match_local_folder(media_root, entry.title)
                if matched:
                    local_title = local_by_folder.get(matched)
            title = (
                entry.title
                or (local_title.title if local_title else None)
                or f"MAL {mid}"
            ).strip()
            if local_title:
                if section == "manga_sync":
                    _, hint = manga_sync_status(local_title, mid)
                else:
                    local_keys = _local_chapter_keys(local_title)
                    _, hint = chapter_titles_status(mid, local_keys)
            else:
                hint = "No local chapters"
            rows.append(
                {
                    "mal_id": mid,
                    "title": title,
                    "skip": bool(rec.get(skip_field)),
                    "hint": hint,
                }
            )

    rows.sort(key=lambda r: (not r["skip"], (r["title"] or "").casefold()))
    return rows
