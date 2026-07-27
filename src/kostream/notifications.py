"""Per-user in-app notifications (JSON store under ``data/users/<id>/``)."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kostream.user_paths import USER_DATA_DIR, user_data_paths

TYPE_REQUEST_FULFILLED = "request_fulfilled"

DEFAULT_LIST_LIMIT = 30


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def notifications_path(user_id: str, base: Path | None = None) -> Path:
    """Return ``…/<user_id>/notifications.json``."""
    return user_data_paths(user_id, base or USER_DATA_DIR)["notifications"]


def load_notifications(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [n for n in raw if isinstance(n, dict)]
    if isinstance(raw, dict):
        items = raw.get("notifications")
        if isinstance(items, list):
            return [n for n in items if isinstance(n, dict)]
    return []


def save_notifications(items: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"notifications": items}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def unread_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for n in items if not n.get("read"))


def list_notifications(
    user_id: str,
    *,
    base: Path | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    """Return ``(recent_items newest-first, unread_count)`` for ``user_id``."""
    uid = (user_id or "").strip()
    if not uid:
        return [], 0
    items = load_notifications(notifications_path(uid, base))
    items_sorted = sorted(
        items,
        key=lambda n: (str(n.get("created_at") or ""), str(n.get("id") or "")),
        reverse=True,
    )
    lim = max(0, int(limit))
    recent = items_sorted[:lim] if lim else items_sorted
    return recent, unread_count(items)


def add_notification(
    user_id: str,
    *,
    type: str,
    title: str,
    body: str,
    href: str | None = None,
    base: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Append a notification for ``user_id``. Returns the new entry, or None if no user."""
    uid = (user_id or "").strip()
    if not uid:
        return None
    path = notifications_path(uid, base)
    items = load_notifications(path)
    entry: dict[str, Any] = {
        "id": secrets.token_hex(8),
        "type": (type or "").strip() or "info",
        "title": (title or "").strip() or "Notification",
        "body": (body or "").strip(),
        "href": (href or "").strip() or None,
        "created_at": _utc_now(),
        "read": False,
    }
    if extra:
        for key, value in extra.items():
            if key in entry:
                continue
            entry[key] = value
    items.append(entry)
    save_notifications(items, path)
    return entry


def mark_read(
    user_id: str,
    notification_ids: list[str] | None = None,
    *,
    base: Path | None = None,
    all: bool = False,
) -> int:
    """Mark notifications read. Returns how many flipped from unread → read."""
    uid = (user_id or "").strip()
    if not uid:
        return 0
    path = notifications_path(uid, base)
    items = load_notifications(path)
    if not items:
        return 0
    id_set: set[str] | None = None
    if not all:
        id_set = {str(i).strip() for i in (notification_ids or []) if str(i).strip()}
        if not id_set:
            return 0
    changed = 0
    for row in items:
        if row.get("read"):
            continue
        if id_set is not None and str(row.get("id") or "") not in id_set:
            continue
        row["read"] = True
        changed += 1
    if changed:
        save_notifications(items, path)
    return changed


def mark_all_read(user_id: str, *, base: Path | None = None) -> int:
    return mark_read(user_id, base=base, all=True)


def href_for_request(kind: str | None, media_id: str | None) -> str | None:
    """Build an in-app path for a fulfilled media request."""
    mid = (media_id or "").strip()
    if not mid:
        return None
    k = (kind or "").strip().casefold()
    if k in ("manga",):
        return f"/manga?open={mid}"
    if k in ("manhwa",):
        return f"/manhwa?open={mid}"
    # series / movie / special / unknown anime-like
    return f"/show/{mid}"


def notify_request_fulfilled(
    request_entry: dict[str, Any],
    *,
    base: Path | None = None,
) -> dict[str, Any] | None:
    """Notify the requester that their request was fulfilled."""
    requester_id = str(request_entry.get("requester_id") or "").strip()
    if not requester_id:
        return None
    title_name = str(request_entry.get("title") or request_entry.get("media_id") or "Your request")
    kind = str(request_entry.get("kind") or "")
    media_id = str(request_entry.get("media_id") or "")
    return add_notification(
        requester_id,
        type=TYPE_REQUEST_FULFILLED,
        title="Request available",
        body=f'"{title_name}" is now available.',
        href=href_for_request(kind, media_id),
        base=base,
        extra={
            "request_id": request_entry.get("id"),
            "media_id": media_id or None,
            "kind": kind or None,
        },
    )
