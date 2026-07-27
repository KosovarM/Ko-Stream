"""One-time accounts migration: per-user progress + MAL list-state split."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kostream.user_paths import user_data_paths
from kostream.users import USERS_FILE, load_users

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

LEGACY_PROGRESS_FILES = (
    ("progress.json", "progress"),
    ("completed.json", "completed"),
    ("manga_completed.json", "manga_completed"),
    ("manga_page_progress.json", "manga_page_progress"),
)

ANIME_LIST_KEYS = ("list_status", "num_episodes_watched", "score")
MANGA_LIST_KEYS = ("list_status", "num_volumes_read", "num_chapters_read", "score")


class MigrateError(Exception):
    """Accounts migration failed."""


def accounts_migrated_marker(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / ".accounts_migrated"


def find_master_user(users_path: Path | None = None):
    users = load_users(users_path or USERS_FILE)
    if not users:
        raise MigrateError(
            "No users found. Bootstrap the master account first:\n"
            "  ko-stream accounts bootstrap --username <name> --password <pw>"
        )
    masters = [u for u in users if u.role == "master"]
    if not masters:
        raise MigrateError("No master account found in users.json.")
    if len(masters) > 1:
        raise MigrateError("Multiple master accounts found; fix users.json first.")
    return masters[0]


def _move_if_needed(src: Path, dest: Path) -> bool:
    """Move src → dest when src exists and dest does not. Returns True if moved."""
    if not src.is_file():
        return False
    if dest.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True


def _extract_anime_list_fields(cache_dir: Path, user_id: str) -> int:
    """Pull personal list fields from shared anime cache into overlay. Returns count."""
    from kostream import mal as mal_mod

    if not cache_dir.is_dir():
        return 0
    state = mal_mod.load_anime_list_state(user_id)
    changed = 0
    for path in sorted(cache_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        mal_id = data.get("mal_id")
        if mal_id is None:
            try:
                mal_id = int(path.stem)
            except ValueError:
                continue
        key = str(int(mal_id))
        row: dict[str, Any] = dict(state.get(key) or {})
        extracted = False
        for field in ANIME_LIST_KEYS:
            if field in data:
                row[field] = data.pop(field)
                extracted = True
        if not extracted:
            continue
        row.setdefault("list_status", "plan_to_watch")
        row.setdefault("num_episodes_watched", 0)
        row.setdefault("score", 0)
        state[key] = row
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        changed += 1
    if changed:
        mal_mod.save_anime_list_state(user_id, state)
    return changed


def _extract_manga_list_fields(cache_dir: Path, user_id: str) -> int:
    from kostream import mal as mal_mod

    if not cache_dir.is_dir():
        return 0
    state = mal_mod.load_manga_list_state(user_id)
    changed = 0
    for path in sorted(cache_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        mal_id = data.get("mal_id")
        if mal_id is None:
            try:
                mal_id = int(path.stem)
            except ValueError:
                continue
        key = str(int(mal_id))
        row: dict[str, Any] = dict(state.get(key) or {})
        extracted = False
        for field in MANGA_LIST_KEYS:
            if field in data:
                row[field] = data.pop(field)
                extracted = True
        if not extracted:
            continue
        row.setdefault("list_status", "plan_to_read")
        row.setdefault("num_volumes_read", 0)
        row.setdefault("num_chapters_read", 0)
        row.setdefault("score", 0)
        state[key] = row
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        changed += 1
    if changed:
        mal_mod.save_manga_list_state(user_id, state)
    return changed


def migrate_accounts(
    *,
    data_dir: Path | None = None,
    users_path: Path | None = None,
    mal_data_dir: Path | None = None,
    user_data_dir: Path | None = None,
    anime_cache_dir: Path | None = None,
    manga_cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Migrate legacy global progress/MAL tokens and split list-state from cache.

    Idempotent: if ``.accounts_migrated`` exists, returns immediately.
    """
    from kostream import mal as mal_mod

    root = data_dir or DATA_DIR
    marker = accounts_migrated_marker(root)
    if marker.is_file():
        return {"ok": True, "already_migrated": True, "message": "Accounts already migrated."}

    users_file = users_path or (root / "users.json")
    master = find_master_user(users_file)
    master_id = master.id

    mal_root = mal_data_dir or (root / "mal")
    users_root = user_data_dir or (root / "users")
    anime_cache = anime_cache_dir or (mal_root / "cache")
    manga_cache = manga_cache_dir or (mal_root / "manga_cache")

    prev = {
        "MAL_DATA_DIR": mal_mod.MAL_DATA_DIR,
    }
    mal_mod.MAL_DATA_DIR = mal_root

    summary: dict[str, Any] = {
        "ok": True,
        "already_migrated": False,
        "master_id": master_id,
        "moved_progress": [],
        "moved_mal": [],
        "anime_list_extracted": 0,
        "manga_list_extracted": 0,
    }

    try:
        dest_paths = user_data_paths(master_id, users_root)
        for filename, key in LEGACY_PROGRESS_FILES:
            if _move_if_needed(root / filename, dest_paths[key]):
                summary["moved_progress"].append(filename)

        mal_moves = [
            (mal_root / "tokens.json", mal_mod.token_path(master_id)),
            (mal_root / "pending_oauth.json", mal_mod.pending_oauth_path(master_id)),
            (mal_root / "last_sync.json", mal_mod.last_sync_path(master_id)),
        ]
        for src, dest in mal_moves:
            if _move_if_needed(src, dest):
                summary["moved_mal"].append(src.name)

        summary["anime_list_extracted"] = _extract_anime_list_fields(anime_cache, master_id)
        summary["manga_list_extracted"] = _extract_manga_list_fields(manga_cache, master_id)

        marker.parent.mkdir(parents=True, exist_ok=True)
        stamp = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        marker.write_text(
            json.dumps({"migrated_at": stamp, "master_id": master_id}, indent=2) + "\n",
            encoding="utf-8",
        )
        summary["message"] = (
            f"Migrated accounts for master {master.username} ({master_id}). "
            f"Anime list rows: {summary['anime_list_extracted']}; "
            f"manga list rows: {summary['manga_list_extracted']}."
        )
        return summary
    finally:
        for key, value in prev.items():
            setattr(mal_mod, key, value)
