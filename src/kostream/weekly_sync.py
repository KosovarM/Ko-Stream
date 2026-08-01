"""Sunday 08:00 local weekly sync chain (background thread).

Runs: Sync animes (each MAL-connected user) → Sync mangas (each) →
anime titles → chapter titles → AniSkip for catalog titles.

Disable with ``KOSTREAM_WEEKLY_SYNC=0``. Only one gunicorn worker holds the
lock file under ``data/weekly_sync.lock``.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
LOCK_PATH = DATA_DIR / "weekly_sync.lock"
LAST_RUN_PATH = DATA_DIR / "weekly_sync_last.txt"
TARGET_WEEKDAY = 6  # Sunday (datetime.weekday)
TARGET_HOUR = 8
TARGET_MINUTE = 0


def _env_enabled() -> bool:
    raw = (os.environ.get("KOSTREAM_WEEKLY_SYNC") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _next_sunday_0800(now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    days_ahead = (TARGET_WEEKDAY - now.weekday()) % 7
    candidate = now.replace(
        hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0
    ) + timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def _try_acquire_lock(path: Path = LOCK_PATH) -> Any | None:
    """Non-blocking exclusive lock. Returns open fd/handle or None."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(path, "a+", encoding="utf-8")
    try:
        if sys.platform == "win32":
            import msvcrt

            fd.seek(0)
            fd.write("0")
            fd.flush()
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.seek(0)
        fd.truncate()
        fd.write(str(os.getpid()))
        fd.flush()
        return fd
    except OSError:
        fd.close()
        return None


def _last_run_date(path: Path = LAST_RUN_PATH) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _write_last_run(day: str, path: Path = LAST_RUN_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(day + "\n", encoding="utf-8")


def build_weekly_starters(app: Any) -> list[Callable[[], Any]]:
    """Build ordered starter callables for the weekly chain."""
    from kostream.mal import MalConfig, is_connected
    from kostream.sync_jobs import (
        enqueue_sync,
        start_anime_sync,
        start_anime_title_sync,
        start_aniskip_sync,
        start_chapter_title_sync,
        start_manga_sync,
    )
    from kostream.user_paths import user_data_paths
    from kostream.users import load_users

    cfg = MalConfig.from_env()
    users_path = app.config["USERS_PATH"]
    connected = [u for u in load_users(users_path) if is_connected(u.id)]
    starters: list[Callable[[], Any]] = []

    if cfg:
        for user in connected:
            uid = user.id
            paths = user_data_paths(uid, app.config["USER_DATA_DIR"])

            def _anime(uid=uid, paths=paths):
                return start_anime_sync(
                    cfg,
                    app.config["CATALOG_PATH"],
                    user_id=uid,
                    media_root=app.config["MEDIA_ROOT"],
                    requests_path=app.config["REQUESTS_PATH"],
                    anime_index_path=app.config["ANIME_SYNC_INDEX_PATH"],
                    completed_path=paths["completed"],
                )

            def _manga(uid=uid):
                return start_manga_sync(
                    cfg,
                    user_id=uid,
                    manga_catalog_path=app.config["MANGA_CATALOG_PATH"],
                    manga_media_root=app.config["MANGA_ROOT"],
                    requests_path=app.config["REQUESTS_PATH"],
                    manga_index_path=app.config["MANGA_SYNC_INDEX_PATH"],
                )

            starters.append(_anime)
            starters.append(_manga)

    starters.append(
        lambda: start_anime_title_sync(
            app.config["CATALOG_PATH"],
            anime_index_path=app.config["ANIME_SYNC_INDEX_PATH"],
        )
    )
    starters.append(
        lambda: start_chapter_title_sync(
            manga_catalog_path=app.config["MANGA_CATALOG_PATH"],
            manga_media_root=app.config["MANGA_ROOT"],
            manga_index_path=app.config["MANGA_SYNC_INDEX_PATH"],
        )
    )
    starters.append(
        lambda: start_aniskip_sync(
            app.config["CATALOG_PATH"],
            media_root=app.config["MEDIA_ROOT"],
            anime_index_path=app.config["ANIME_SYNC_INDEX_PATH"],
        )
    )

    # First job starts (or queues); remaining always enqueue behind it.
    def chain() -> Any:
        if not starters:
            return None
        first, _queued = enqueue_sync(starters[0])
        for starter in starters[1:]:
            enqueue_sync(starter)
        return first

    return [chain]


def run_weekly_sync_now(app: Any) -> None:
    """Enqueue/start the full weekly chain once."""
    starters = build_weekly_starters(app)
    if not starters:
        return
    log.info("Weekly sync: starting Sunday chain (%d step builder(s))", len(starters))
    starters[0]()


def start_weekly_sync_scheduler(app: Any) -> None:
    """Daemon thread: sleep until next Sunday 08:00 local, then run chain."""
    if not _env_enabled():
        log.info("Weekly sync scheduler disabled (KOSTREAM_WEEKLY_SYNC=0)")
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    lock_fd = _try_acquire_lock()
    if lock_fd is None:
        log.info("Weekly sync scheduler: another worker holds the lock")
        return

    app_ref = app

    def loop() -> None:
        try:
            while True:
                now = datetime.now()
                target = _next_sunday_0800(now)
                sleep_s = max(5.0, (target - now).total_seconds())
                # Sleep in chunks so process shutdown is responsive.
                end = time.time() + sleep_s
                while time.time() < end:
                    time.sleep(min(60.0, end - time.time()))
                day = datetime.now().strftime("%Y-%m-%d")
                if _last_run_date() == day:
                    continue
                # Only fire if we are still on/after Sunday 08:00 window same day.
                now2 = datetime.now()
                if now2.weekday() != TARGET_WEEKDAY or now2.hour < TARGET_HOUR:
                    continue
                try:
                    with app_ref.app_context():
                        run_weekly_sync_now(app_ref)
                    _write_last_run(day)
                except Exception:
                    log.exception("Weekly sync chain failed")
        finally:
            try:
                lock_fd.close()
            except OSError:
                pass

    threading.Thread(target=loop, daemon=True, name="kostream-weekly-sync").start()
    log.info(
        "Weekly sync scheduler started (next Sunday %02d:%02d local)",
        TARGET_HOUR,
        TARGET_MINUTE,
    )
