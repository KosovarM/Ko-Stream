"""Local manga chapter completion + helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from kostream.jsonio import atomic_write_json
from kostream.manga import MangaChapter, MangaTitle

MANGA_COMPLETED_FILE = Path(__file__).resolve().parents[2] / "data" / "manga_completed.json"
MANGA_PAGE_PROGRESS_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "manga_page_progress.json"
)

MangaReadingStatus = Literal["reading", "completed", "new"]


def sorted_chapters(manga: MangaTitle) -> list[MangaChapter]:
    return [c for c in manga.chapters if getattr(c, "available", True)]


def chapter_position(manga: MangaTitle, chapter_id: str) -> int:
    for idx, ch in enumerate(sorted_chapters(manga), start=1):
        if ch.id == chapter_id:
            return idx
    return 0


def load_manga_completed(path: Path | None = None) -> dict[str, int]:
    """Map manga_id → highest chapter position marked read (1-based)."""
    file_path = path or MANGA_COMPLETED_FILE
    if not file_path.exists():
        return {}
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return {str(k): int(v) for k, v in raw.items() if str(v).isdigit() or isinstance(v, int)}


def save_manga_completed(path: Path, data: dict[str, int]) -> None:
    atomic_write_json(path, data)


def load_manga_page_progress(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Map manga_id → {last_chapter_id, pages: {chapter_id: page_index}}."""
    file_path = path or MANGA_PAGE_PROGRESS_FILE
    if not file_path.exists():
        return {}
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for manga_id, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        pages_raw = entry.get("pages") or {}
        pages: dict[str, int] = {}
        if isinstance(pages_raw, dict):
            for ch_id, page in pages_raw.items():
                try:
                    idx = int(page)
                except (TypeError, ValueError):
                    continue
                if idx >= 0:
                    pages[str(ch_id)] = idx
        last = entry.get("last_chapter_id")
        out[str(manga_id)] = {
            "last_chapter_id": str(last) if last else None,
            "pages": pages,
        }
    return out


def save_manga_page_progress(path: Path, data: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(path, data)


def get_chapter_page_index(
    manga_id: str,
    chapter_id: str,
    path: Path | None = None,
) -> int | None:
    """Return saved 0-based page index for a chapter, or None."""
    entry = load_manga_page_progress(path).get(str(manga_id))
    if not entry:
        return None
    pages = entry.get("pages") or {}
    if chapter_id not in pages:
        return None
    return int(pages[chapter_id])


def set_chapter_page_index(
    manga_id: str,
    chapter_id: str,
    page_index: int,
    path: Path | None = None,
) -> int:
    """Persist 0-based page index; updates last_chapter_id. Returns clamped index."""
    page_index = max(0, int(page_index))
    file_path = path or MANGA_PAGE_PROGRESS_FILE
    data = load_manga_page_progress(file_path)
    entry = data.setdefault(
        str(manga_id),
        {"last_chapter_id": None, "pages": {}},
    )
    pages = entry.setdefault("pages", {})
    pages[str(chapter_id)] = page_index
    entry["last_chapter_id"] = str(chapter_id)
    save_manga_page_progress(file_path, data)
    return page_index


def clear_chapter_page_index(
    manga_id: str,
    chapter_id: str,
    path: Path | None = None,
) -> None:
    """Remove saved page for one chapter (e.g. after marking read)."""
    file_path = path or MANGA_PAGE_PROGRESS_FILE
    data = load_manga_page_progress(file_path)
    entry = data.get(str(manga_id))
    if not entry:
        return
    pages = entry.get("pages") or {}
    if str(chapter_id) not in pages:
        return
    pages.pop(str(chapter_id), None)
    if entry.get("last_chapter_id") == str(chapter_id):
        entry["last_chapter_id"] = None
    if not pages and not entry.get("last_chapter_id"):
        data.pop(str(manga_id), None)
    save_manga_page_progress(file_path, data)


def clear_page_progress_through(
    manga: MangaTitle,
    through: int,
    path: Path | None = None,
) -> None:
    """Clear page bookmarks for chapters 1..through (after mark-read)."""
    through = max(0, int(through))
    if through <= 0 or not manga.chapters:
        return
    file_path = path or MANGA_PAGE_PROGRESS_FILE
    data = load_manga_page_progress(file_path)
    entry = data.get(manga.id)
    if not entry:
        return
    pages = entry.get("pages") or {}
    changed = False
    for idx, ch in enumerate(sorted_chapters(manga), start=1):
        if idx <= through and ch.id in pages:
            pages.pop(ch.id, None)
            changed = True
            if entry.get("last_chapter_id") == ch.id:
                entry["last_chapter_id"] = None
    if not changed:
        return
    if not pages and not entry.get("last_chapter_id"):
        data.pop(manga.id, None)
    save_manga_page_progress(file_path, data)


def resume_point(
    manga_id: str,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Last chapter + page for Continue, or None."""
    entry = load_manga_page_progress(path).get(str(manga_id))
    if not entry:
        return None
    chapter_id = entry.get("last_chapter_id")
    if not chapter_id:
        return None
    pages = entry.get("pages") or {}
    page_index = int(pages.get(chapter_id, 0))
    return {"chapter_id": str(chapter_id), "page_index": page_index}

def effective_chapters_read(
    manga: MangaTitle,
    completed: dict[str, int] | None = None,
    mal_chapters_read: int = 0,
) -> int:
    local = (completed or {}).get(manga.id, 0)
    return max(local, mal_chapters_read, 0)


def chapters_read_count(
    manga: MangaTitle,
    completed: dict[str, int] | None = None,
) -> int:
    """Highest chapters-read from local progress or MAL."""
    return effective_chapters_read(manga, completed, manga.num_chapters_read)


def total_chapters_target(manga: MangaTitle) -> int:
    """Prefer local chapter count; fall back to MAL chapter total."""
    return max(manga.chapter_count, manga.num_chapters_mal, 0)


def manga_reading_status(
    manga: MangaTitle,
    completed: dict[str, int] | None = None,
) -> MangaReadingStatus:
    """Classify as reading | completed | new.

    Still-publishing titles stay ``reading`` at 100% so more chapters can arrive.
    Explicit MAL/local ``list_status == completed`` still counts as completed.
    """
    if manga.list_status == "completed":
        return "completed"
    read = chapters_read_count(manga, completed)
    total = total_chapters_target(manga)
    if total and read >= total:
        if is_currently_publishing(manga):
            return "reading"
        return "completed"
    if read >= 1 or manga.list_status in {"reading", "on_hold"}:
        return "reading"
    return "new"


def manga_complete_list_status(manga: MangaTitle, chapters_read: int) -> str:
    """MAL/local list status after marking chapters read through ``chapters_read``."""
    total = total_chapters_target(manga)
    if total and chapters_read >= total and not is_currently_publishing(manga):
        return "completed"
    return "reading"


def chapter_completed(
    manga: MangaTitle,
    chapter_id: str,
    completed: dict[str, int] | None = None,
    mal_chapters_read: int = 0,
) -> bool:
    pos = chapter_position(manga, chapter_id)
    if not pos:
        return False
    return pos <= effective_chapters_read(manga, completed, mal_chapters_read)


def next_unread_chapter(
    manga: MangaTitle,
    completed: dict[str, int] | None = None,
    mal_chapters_read: int = 0,
) -> MangaChapter | None:
    """First chapter in order that is not marked read (anime Continue semantics)."""
    for ch in sorted_chapters(manga):
        if not chapter_completed(manga, ch.id, completed, mal_chapters_read):
            return ch
    return None


def mark_chapter_read(
    manga: MangaTitle,
    chapter_id: str,
    path: Path | None = None,
    page_path: Path | None = None,
) -> int:
    """Record chapter as read locally; returns new chapters-read count."""
    pos = chapter_position(manga, chapter_id)
    if not pos:
        return effective_chapters_read(manga)
    return mark_chapters_read_through(manga, pos, path, page_path)


def mark_chapters_read_through(
    manga: MangaTitle,
    through: int,
    path: Path | None = None,
    page_path: Path | None = None,
) -> int:
    """Mark chapters 1..through as read locally; returns new chapters-read count.

    Progress is cumulative (highest 1-based position), matching MAL
    ``num_chapters_read``. Already-read chapters in the range are no-ops.
    Clears in-chapter page bookmarks for chapters now marked read.
    """
    through = max(0, int(through))
    if through <= 0:
        return effective_chapters_read(manga)
    file_path = path or MANGA_COMPLETED_FILE
    data = load_manga_completed(file_path)
    data[manga.id] = max(data.get(manga.id, 0), through)
    save_manga_completed(file_path, data)
    manga.num_chapters_read = max(manga.num_chapters_read, through)
    clear_page_progress_through(manga, through, page_path)
    return data[manga.id]


def unmark_chapter_read(
    manga: MangaTitle,
    chapter_id: str,
    path: Path | None = None,
) -> int:
    """Undo a single chapter complete: set local chapters-read to position − 1."""
    pos = chapter_position(manga, chapter_id)
    if not pos:
        return effective_chapters_read(manga, load_manga_completed(path or MANGA_COMPLETED_FILE))
    file_path = path or MANGA_COMPLETED_FILE
    data = load_manga_completed(file_path)
    new_count = max(0, pos - 1)
    if new_count > 0:
        data[manga.id] = new_count
    else:
        data.pop(manga.id, None)
    save_manga_completed(file_path, data)
    manga.num_chapters_read = new_count
    total = total_chapters_target(manga)
    if manga.list_status == "completed" and (not total or new_count < total):
        manga.list_status = "reading"
    return new_count


def mark_manga_completed(
    manga: MangaTitle,
    path: Path | None = None,
    page_path: Path | None = None,
) -> int:
    """Mark the whole title complete locally; returns chapters-read count."""
    total = total_chapters_target(manga)
    if not total:
        total = max(chapters_read_count(manga), 1)
    file_path = path or MANGA_COMPLETED_FILE
    data = load_manga_completed(file_path)
    data[manga.id] = max(data.get(manga.id, 0), total)
    save_manga_completed(file_path, data)
    manga.num_chapters_read = max(manga.num_chapters_read, total)
    manga.list_status = "completed"
    clear_page_progress_through(manga, total, page_path)
    return data[manga.id]


def is_currently_publishing(manga: MangaTitle) -> bool:
    status = (manga.manga_status or "").strip().lower()
    return status in {"currently_publishing", "publishing"}


def filter_currently_publishing(titles: list[MangaTitle]) -> list[MangaTitle]:
    publishing = [t for t in titles if is_currently_publishing(t)]
    return sorted(publishing, key=lambda t: t.title.casefold())


def filter_currently_reading(
    titles: list[MangaTitle],
    completed: dict[str, int] | None = None,
) -> list[MangaTitle]:
    reading = [
        t for t in titles if manga_reading_status(t, completed) == "reading"
    ]
    return sorted(reading, key=lambda t: t.title.casefold())

