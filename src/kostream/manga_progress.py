"""Local manga chapter completion + helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from kostream.manga import MangaChapter, MangaTitle

MANGA_COMPLETED_FILE = Path(__file__).resolve().parents[2] / "data" / "manga_completed.json"

MangaReadingStatus = Literal["reading", "completed", "new"]


def sorted_chapters(manga: MangaTitle) -> list[MangaChapter]:
    return list(manga.chapters)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


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
    """Classify as reading | completed | new."""
    if manga.list_status == "completed":
        return "completed"
    read = chapters_read_count(manga, completed)
    total = total_chapters_target(manga)
    if total and read >= total:
        return "completed"
    if read >= 1:
        return "reading"
    return "new"


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


def mark_chapter_read(
    manga: MangaTitle,
    chapter_id: str,
    path: Path | None = None,
) -> int:
    """Record chapter as read locally; returns new chapters-read count."""
    pos = chapter_position(manga, chapter_id)
    if not pos:
        return effective_chapters_read(manga)
    return mark_chapters_read_through(manga, pos, path)


def mark_chapters_read_through(
    manga: MangaTitle,
    through: int,
    path: Path | None = None,
) -> int:
    """Mark chapters 1..through as read locally; returns new chapters-read count.

    Progress is cumulative (highest 1-based position), matching MAL
    ``num_chapters_read``. Already-read chapters in the range are no-ops.
    """
    through = max(0, int(through))
    if through <= 0:
        return effective_chapters_read(manga)
    file_path = path or MANGA_COMPLETED_FILE
    data = load_manga_completed(file_path)
    data[manga.id] = max(data.get(manga.id, 0), through)
    save_manga_completed(file_path, data)
    manga.num_chapters_read = max(manga.num_chapters_read, through)
    return data[manga.id]


def mark_manga_completed(
    manga: MangaTitle,
    path: Path | None = None,
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

