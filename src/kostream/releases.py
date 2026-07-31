"""Product changelog / Releases page (features we ship, not media calendar)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kostream.jsonio import atomic_write_json
from kostream.notifications import (
    add_notification,
    load_notifications,
    notifications_path,
    save_notifications,
)
from kostream.users import USERS_FILE, load_users

RELEASES_FILE = Path(__file__).resolve().parents[2] / "data" / "releases.json"
TYPE_PRODUCT_UPDATE = "product_update"
HREF_RELEASES = "/releases"
NOTIFY_TITLE = "New update released"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_releases(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or RELEASES_FILE
    if not target.is_file():
        return []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("releases") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    return [r for r in items if isinstance(r, dict)]


def save_releases(items: list[dict[str, Any]], path: Path | None = None) -> None:
    atomic_write_json(path or RELEASES_FILE, {"releases": items}, ensure_ascii=False)


def sort_releases(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest date first (``date`` is DD.MM.YYYY)."""

    def key(row: dict[str, Any]) -> tuple:
        d = str(row.get("date") or "")
        parts = d.split(".")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            day, month, year = (int(parts[0]), int(parts[1]), int(parts[2]))
            return (year, month, day, str(row.get("id") or ""))
        return (0, 0, 0, str(row.get("id") or ""))

    return sorted(items, key=key, reverse=True)


def release_title(date_str: str) -> str:
    return f"Update - {date_str}"


def remove_undismissed_update_notifications(
    *,
    users_path: Path | None = None,
    base: Path | None = None,
) -> int:
    """Remove previous undismissed product-update notifications for all users."""
    removed = 0
    for user in load_users(users_path or USERS_FILE):
        path = notifications_path(user.id, base)
        items = load_notifications(path)
        if not items:
            continue
        kept: list[dict[str, Any]] = []
        changed = False
        for row in items:
            is_update = (
                str(row.get("type") or "") == TYPE_PRODUCT_UPDATE
                or str(row.get("title") or "") == NOTIFY_TITLE
            )
            if is_update and not row.get("dismissed"):
                changed = True
                removed += 1
                continue
            kept.append(row)
        if changed:
            save_notifications(kept, path)
    return removed


def notify_all_users_new_release(
    *,
    date_str: str,
    users_path: Path | None = None,
    base: Path | None = None,
) -> int:
    """Clear prior update notifications, then notify every account."""
    remove_undismissed_update_notifications(users_path=users_path, base=base)
    count = 0
    body = release_title(date_str)
    for user in load_users(users_path or USERS_FILE):
        note = add_notification(
            user.id,
            type=TYPE_PRODUCT_UPDATE,
            title=NOTIFY_TITLE,
            body=body,
            href=HREF_RELEASES,
            base=base,
        )
        if note is not None:
            count += 1
    return count


def upsert_release(
    entry: dict[str, Any],
    *,
    path: Path | None = None,
    notify: bool = False,
    users_path: Path | None = None,
    base: Path | None = None,
) -> dict[str, Any]:
    """Insert or replace a release by ``id`` (defaults to date). Optionally notify."""
    items = load_releases(path)
    date_str = str(entry.get("date") or "").strip()
    rid = str(entry.get("id") or date_str).strip() or date_str
    entry = dict(entry)
    entry["id"] = rid
    entry["date"] = date_str
    entry["title"] = entry.get("title") or release_title(date_str)
    entry.setdefault("updated_at", _utc_now())
    existing = next((r for r in items if str(r.get("id") or "") == rid), None)
    changed = existing is None or (
        existing.get("sections") != entry.get("sections")
        or existing.get("title") != entry.get("title")
        or existing.get("date") != entry.get("date")
    )
    needs_notify = notify and date_str and (changed or not (existing or {}).get("notified_at"))
    rest = [r for r in items if str(r.get("id") or "") != rid]
    if needs_notify:
        entry["notified_at"] = _utc_now()
    elif existing and existing.get("notified_at"):
        entry["notified_at"] = existing.get("notified_at")
    rest.append(entry)
    save_releases(sort_releases(rest), path)
    if needs_notify:
        notify_all_users_new_release(
            date_str=date_str, users_path=users_path, base=base
        )
    return entry


PATCH_2026_07_31: dict[str, Any] = {
    "id": "31.07.2026",
    "date": "31.07.2026",
    "title": "Update - 31.07.2026",
    "sections": {
        "general": [
            "Admin: delete user (with MAL disconnect) and online activity indicator",
            "Admin accounts panel layout and light-theme button polish",
            "Notifications: dismiss individual items; product Releases page under Catalog",
            "Releases changelog with per-update General / Anime / Manga sections",
        ],
        "anime": [
            "Tag rename: Stream only (was Test stream)",
            "Search pagination: First / Last plus nearby page buttons",
            "Recently added reflects newly added local episodes",
            "Player: fullscreen control top-right; light theme keeps subtitle cue colors readable",
            "AniSkip: cache OP/ED on sync/add; Skip Opening / Skip Ending on the player",
        ],
        "manga": [
            "Home: New Chapter releases row after Recently added",
            "Notify readers when a completed title gains a new chapter",
            "Still-publishing titles stay Reading at 100% (not auto-Completed)",
            "Chapter list shows known-but-unavailable chapters; hide Request missing when all known are local",
            "Vertical reader: next chapter at end; auto-complete only on last page; chrome-hidden expands stage",
        ],
    },
}


def seed_patch_release(
    *,
    path: Path | None = None,
    notify: bool = True,
    users_path: Path | None = None,
    base: Path | None = None,
) -> dict[str, Any]:
    """Seed/update the 31.07.2026 product release entry."""
    return upsert_release(
        PATCH_2026_07_31,
        path=path,
        notify=notify,
        users_path=users_path,
        base=base,
    )
