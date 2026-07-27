"""Per-user local data file paths."""

from __future__ import annotations

from pathlib import Path

USER_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "users"


def user_data_paths(user_id: str, base: Path | None = None) -> dict[str, Path]:
    """Return per-user progress file paths under ``base/<user_id>/``."""
    root = (base or USER_DATA_DIR) / user_id
    return {
        "progress": root / "progress.json",
        "completed": root / "completed.json",
        "manga_completed": root / "manga_completed.json",
        "manga_page_progress": root / "manga_page_progress.json",
        "notifications": root / "notifications.json",
    }
