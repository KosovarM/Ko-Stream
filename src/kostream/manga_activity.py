"""Track manga/manhwa chapter growth for home row + completed-title notifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kostream.jsonio import atomic_write_json
from kostream.manga import MangaTitle
from kostream.manga_progress import is_currently_publishing, manga_reading_status
from kostream.notifications import add_notification
from kostream.user_paths import USER_DATA_DIR, user_data_paths
from kostream.users import USERS_FILE, load_users

ACTIVITY_FILE = Path(__file__).resolve().parents[2] / "data" / "manga_chapter_activity.json"
TYPE_NEW_CHAPTER = "manga_new_chapter"


def load_activity(path: Path | None = None) -> dict[str, Any]:
    target = path or ACTIVITY_FILE
    if not target.is_file():
        return {"titles": {}}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"titles": {}}
    if not isinstance(raw, dict):
        return {"titles": {}}
    titles = raw.get("titles")
    if not isinstance(titles, dict):
        raw["titles"] = {}
    return raw


def save_activity(data: dict[str, Any], path: Path | None = None) -> None:
    atomic_write_json(path or ACTIVITY_FILE, data, ensure_ascii=False)


def _href_for(title: MangaTitle) -> str:
    if title.is_manhwa:
        return f"/manhwa?open={title.id}"
    return f"/manga?open={title.id}"


def sync_chapter_activity(
    titles: list[MangaTitle],
    *,
    path: Path | None = None,
    users_path: Path | None = None,
    user_data_base: Path | None = None,
    notify: bool = True,
) -> list[dict[str, Any]]:
    """Update stored chapter counts; notify users who had completed titles that grew.

    Returns list of growth events ``{id, title, old, new}``.
    """
    data = load_activity(path)
    store: dict[str, Any] = data.setdefault("titles", {})
    events: list[dict[str, Any]] = []
    for title in titles:
        local_n = int(title.chapter_count or 0)
        if local_n <= 0 and not title.added_at:
            continue
        prev = store.get(title.id) if isinstance(store.get(title.id), dict) else {}
        old_n = int(prev.get("chapter_count") or 0)
        mtime = float(title.latest_chapter_mtime or 0.0)
        entry = {
            "chapter_count": max(old_n, local_n),
            "latest_mtime": mtime,
            "title": title.title,
            "kind": "manhwa" if title.is_manhwa else "manga",
            "added_at": title.added_at,
        }
        grew = local_n > old_n > 0
        if grew:
            entry["chapter_count"] = local_n
            events.append(
                {
                    "id": title.id,
                    "title": title.title,
                    "old": old_n,
                    "new": local_n,
                    "kind": entry["kind"],
                    "href": _href_for(title),
                }
            )
        elif local_n > 0:
            entry["chapter_count"] = local_n
        store[title.id] = entry

    save_activity(data, path)

    if notify and events:
        _notify_completed_readers(
            events,
            titles,
            users_path=users_path,
            user_data_base=user_data_base,
        )
    return events


def _notify_completed_readers(
    events: list[dict[str, Any]],
    titles: list[MangaTitle],
    *,
    users_path: Path | None = None,
    user_data_base: Path | None = None,
) -> None:
    by_id = {t.id: t for t in titles}
    base = user_data_base or USER_DATA_DIR
    users = load_users(users_path or USERS_FILE)
    for event in events:
        title = by_id.get(event["id"])
        if title is None:
            continue
        for user in users:
            paths = user_data_paths(user.id, base)
            completed = {}
            try:
                from kostream.manga_progress import load_manga_completed

                completed = load_manga_completed(paths["manga_completed"])
            except OSError:
                completed = {}
            # Only ping users who finished the title (local completed status).
            if manga_reading_status(title, completed) != "completed":
                continue
            if is_currently_publishing(title):
                # Still publishing + previously at 100% may still be "reading"
                # after status fix; if marked completed explicitly, still notify.
                pass
            add_notification(
                user.id,
                type=TYPE_NEW_CHAPTER,
                title="New chapter available",
                body=f'"{title.title}" has a new chapter.',
                href=event["href"],
                base=base,
                extra={"media_id": title.id, "kind": event["kind"]},
            )


def recently_updated_manga(
    titles: list[MangaTitle],
    *,
    limit: int = 12,
    activity_path: Path | None = None,
) -> list[MangaTitle]:
    """Titles newly added or with recent chapter activity (local mtime / catalog)."""
    from datetime import datetime

    activity = load_activity(activity_path)
    store = activity.get("titles") or {}

    def score(t: MangaTitle) -> float:
        best = float(t.latest_chapter_mtime or 0.0)
        added = (t.added_at or "").strip()
        if added:
            try:
                # Support ...Z and offset ISO
                iso = added.replace("Z", "+00:00")
                best = max(best, datetime.fromisoformat(iso).timestamp())
            except ValueError:
                pass
        row = store.get(t.id) if isinstance(store, dict) else None
        if isinstance(row, dict):
            try:
                best = max(best, float(row.get("latest_mtime") or 0.0))
            except (TypeError, ValueError):
                pass
        return best

    ranked = [t for t in titles if score(t) > 0]
    ranked.sort(key=score, reverse=True)
    return ranked[:limit]
