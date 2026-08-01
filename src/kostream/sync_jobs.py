"""Background MAL / MangaDex sync jobs so the UI is not blocked.

Five job kinds share one global lock (only one sync at a time):

- ``animes`` — animelist, anime progress reconcile, anime request clear, enrich
- ``mangas`` — mangalist + manga request clear
- ``anime_titles`` — episode titles only (Jikan/MAL cache)
- ``aniskip`` — AniSkip OP/ED skip times only
- ``chapter_titles`` — MangaDex chapter titles only

When a sync is already running, callers may ``enqueue_sync`` so the next job
starts automatically after the current one finishes.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from kostream.mal import (
    ENRICH_BATCH_SIZE,
    EPISODE_TITLE_BATCH_SIZE,
    EpisodeTitleSyncResult,
    MalConfig,
    MalError,
    enrich_catalog_mal_details,
    sync_animelist_to_catalog,
    sync_catalog_episode_titles,
    sync_mangalist_to_catalog,
)
from kostream.mangadex import (
    CHAPTER_TITLE_BATCH_SIZE,
    sync_catalog_chapter_titles,
)
from kostream.sync_index import (
    refresh_anime_index,
    refresh_manga_index,
    skipped_mal_ids,
)

JobKind = Literal["animes", "mangas", "anime_titles", "aniskip", "chapter_titles"]

_lock = threading.Lock()
_job: SyncJob | None = None
_queue: list[Callable[[], SyncJob]] = []


@dataclass
class SyncJob:
    status: str = "idle"  # idle | running | done | error
    kind: str = ""  # animes | mangas | anime_titles | aniskip | chapter_titles | ""
    phase: str = ""  # list | progress | enrich | manga | episode_titles | aniskip | chapter_titles | done
    synced: int = 0
    manga_synced: int = 0
    enriched: int = 0
    episode_titles: int = 0
    aniskip: int = 0
    chapter_titles: int = 0
    message: str = ""
    error: str | None = None
    queued: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "kind": self.kind,
            "phase": self.phase,
            "synced": self.synced,
            "manga_synced": self.manga_synced,
            "enriched": self.enriched,
            "episode_titles": self.episode_titles,
            "aniskip": self.aniskip,
            "chapter_titles": self.chapter_titles,
            "message": self.message,
            "error": self.error,
            "queued": self.queued,
            "running": self.status == "running",
        }


def get_sync_job() -> SyncJob:
    global _job
    with _lock:
        job = _job or SyncJob(status="idle", message="No sync yet.")
        job.queued = len(_queue)
        return job


def queue_depth() -> int:
    with _lock:
        return len(_queue)


def enqueue_sync(starter: Callable[[], SyncJob]) -> tuple[SyncJob, bool]:
    """Start ``starter`` now if idle; otherwise queue it.

    Returns ``(job, queued)`` where ``queued`` is True when the starter was
    appended behind the currently running job.
    """
    with _lock:
        busy = _job is not None and _job.status == "running"
        if busy:
            _queue.append(starter)
            assert _job is not None
            _job.queued = len(_queue)
            if "queued" not in (_job.message or "").casefold():
                _job.message = f"{_job.message} ({len(_queue)} queued)".strip()
            return _job, True
    return starter(), False


def _drain_queue() -> None:
    with _lock:
        if _job is not None and _job.status == "running":
            return
        if not _queue:
            return
        starter = _queue.pop(0)
    try:
        starter()
    except Exception:
        _drain_queue()


def _begin_job(kind: JobKind, phase: str, message: str) -> SyncJob | None:
    """Create a running job if none is active. Returns None when busy (caller gets current)."""
    global _job
    with _lock:
        if _job and _job.status == "running":
            return None
        job = SyncJob(
            status="running",
            kind=kind,
            phase=phase,
            message=message,
            queued=len(_queue),
        )
        _job = job
        return job


def _finish_ok(job: SyncJob, message: str) -> None:
    with _lock:
        job.status = "done"
        job.phase = "done"
        job.finished_at = time.time()
        job.message = message
        job.queued = len(_queue)
    _drain_queue()


def _finish_error(job: SyncJob, message: str, exc: BaseException | None = None) -> None:
    with _lock:
        job.status = "error"
        job.phase = "done"
        job.error = str(exc) if exc is not None else message
        job.finished_at = time.time()
        job.message = message
        job.queued = len(_queue)
    _drain_queue()


def start_anime_sync(
    cfg: MalConfig,
    catalog_path,
    *,
    user_id: str,
    media_root=None,
    requests_path=None,
    anime_index_path=None,
    completed_path=None,
) -> SyncJob:
    """Animelist + progress reconcile + anime request clear + metadata enrich."""
    job = _begin_job("animes", "list", "Syncing animelist…")
    if job is None:
        return get_sync_job()

    def runner() -> None:
        nonlocal job
        try:
            count = sync_animelist_to_catalog(
                cfg, catalog_path, user_id=user_id, enrich=False
            )
            catalog_count = 0
            try:
                from kostream.catalog import load_catalog

                catalog_count = sum(
                    1 for e in load_catalog(catalog_path).shows if e.mal_id
                )
            except (OSError, ValueError, TypeError):
                catalog_count = count
            catalog_only = max(0, catalog_count - count)
            list_label = (
                f"{count} from your MAL list"
                if catalog_only == 0
                else (
                    f"{count} from your MAL list · catalog {catalog_count}"
                    f" ({catalog_only} not on your list)"
                )
            )
            with _lock:
                job.synced = count
                job.phase = "progress"
                job.message = f"List synced ({list_label}). Reconciling watch progress…"

            skip_anime = skipped_mal_ids("anime_sync", index_path=anime_index_path)
            try:
                from kostream.library import MEDIA_ROOT, scan_library
                from kostream.watch_progress import reconcile_anime_progress

                root = media_root or MEDIA_ROOT
                for show in scan_library(root, catalog_path):
                    if show.mal_id and int(show.mal_id) not in skip_anime:
                        reconcile_anime_progress(
                            show,
                            completed_path=completed_path,
                            mal_cfg=cfg,
                            user_id=user_id,
                        )
            except (OSError, ValueError):
                pass

            try:
                from kostream.library import MEDIA_ROOT
                from kostream.requests_store import clear_fulfilled_requests

                cleared = clear_fulfilled_requests(
                    path=requests_path,
                    media_root=media_root or MEDIA_ROOT,
                    catalog_path=catalog_path,
                    scope="anime",
                )
                if cleared:
                    with _lock:
                        job.message = (
                            f"Synced {list_label}. "
                            f"Cleared {cleared} fulfilled request"
                            f"{'s' if cleared != 1 else ''}. "
                            "Fetching prequel/sequel metadata…"
                        )
            except (OSError, ValueError, TypeError):
                pass

            with _lock:
                job.phase = "enrich"
                if "Cleared" not in (job.message or ""):
                    job.message = (
                        f"Synced {list_label}. Fetching prequel/sequel metadata…"
                    )
            enriched = 0
            try:
                enriched = enrich_catalog_mal_details(
                    cfg,
                    catalog_path,
                    user_id=user_id,
                    limit=ENRICH_BATCH_SIZE,
                    skip_mal_ids=skip_anime,
                )
            except (MalError, TimeoutError, OSError) as exc:
                with _lock:
                    job.enriched = enriched
                try:
                    refresh_anime_index(
                        catalog_path=catalog_path,
                        media_root=media_root,
                        index_path=anime_index_path,
                    )
                except (OSError, ValueError):
                    pass
                _finish_ok(
                    job,
                    f"Animes synced: {list_label}. Metadata enrich partial ({enriched}): {exc}",
                )
                return

            with _lock:
                job.enriched = enriched
            try:
                from kostream.thumbnails import sync_anime_thumbnails_from_cache

                with _lock:
                    job.phase = "thumbnails"
                    job.message = (
                        f"Synced {list_label} · enriched {enriched}. "
                        "Caching posters…"
                    )
                thumbs = sync_anime_thumbnails_from_cache()
                with _lock:
                    if thumbs:
                        job.message = (
                            f"Synced {list_label} · enriched {enriched} · "
                            f"thumbnails {thumbs}."
                        )
            except (OSError, ValueError, TypeError):
                thumbs = 0
            try:
                refresh_anime_index(
                    catalog_path=catalog_path,
                    media_root=media_root,
                    index_path=anime_index_path,
                )
            except (OSError, ValueError):
                pass
            more_hint = (
                " Run Sync animes again later for more enrich batches if needed."
                if enriched >= ENRICH_BATCH_SIZE
                else ""
            )
            thumb_hint = f" · thumbnails {thumbs}" if thumbs else ""
            _finish_ok(
                job,
                f"Animes synced: {list_label} · enriched {enriched}{thumb_hint}.{more_hint}",
            )
        except (MalError, TimeoutError, OSError) as exc:
            _finish_error(job, f"Anime sync failed: {exc}", exc)

    threading.Thread(target=runner, daemon=True, name="mal-sync-animes").start()
    return job


def start_manga_sync(
    cfg: MalConfig,
    *,
    user_id: str,
    manga_catalog_path=None,
    manga_media_root=None,
    requests_path=None,
    manga_index_path=None,
) -> SyncJob:
    """Mangalist sync + manga request clear (no chapter titles)."""
    job = _begin_job("mangas", "manga", "Syncing mangalist…")
    if job is None:
        return get_sync_job()

    def runner() -> None:
        nonlocal job
        try:
            manga_count = sync_mangalist_to_catalog(
                cfg,
                user_id=user_id,
                manga_catalog_path=manga_catalog_path,
                manga_media_root=manga_media_root,
            )
            with _lock:
                job.manga_synced = manga_count
                job.message = f"Synced {manga_count} manga. Clearing fulfilled requests…"

            cleared = 0
            try:
                from kostream.requests_store import clear_fulfilled_requests

                cleared = clear_fulfilled_requests(
                    path=requests_path,
                    manga_root=manga_media_root,
                    manga_catalog_path=manga_catalog_path,
                    scope="manga",
                )
            except (OSError, ValueError, TypeError):
                pass

            try:
                from kostream.thumbnails import sync_manga_thumbnails_from_cache

                with _lock:
                    job.phase = "thumbnails"
                    job.message = f"Synced {manga_count} manga. Caching posters…"
                thumbs = sync_manga_thumbnails_from_cache()
            except (OSError, ValueError, TypeError):
                thumbs = 0

            try:
                refresh_manga_index(
                    manga_catalog_path=manga_catalog_path,
                    manga_media_root=manga_media_root,
                    index_path=manga_index_path,
                )
            except (OSError, ValueError):
                pass

            parts = [f"Mangas synced: {manga_count}"]
            if cleared:
                parts.append(
                    f"cleared {cleared} fulfilled request{'s' if cleared != 1 else ''}"
                )
            if thumbs:
                parts.append(f"thumbnails {thumbs}")
            _finish_ok(job, ". ".join(parts) + ".")
        except (MalError, TimeoutError, OSError) as exc:
            _finish_error(job, f"Manga sync failed: {exc}", exc)

    threading.Thread(target=runner, daemon=True, name="mal-sync-mangas").start()
    return job


def start_anime_title_sync(catalog_path, *, anime_index_path=None) -> SyncJob:
    """Fetch/refresh anime episode titles only."""
    job = _begin_job("anime_titles", "episode_titles", "Fetching episode titles…")
    if job is None:
        return get_sync_job()

    def runner() -> None:
        nonlocal job
        try:
            skip_titles = skipped_mal_ids("episode_titles", index_path=anime_index_path)
            raw_titles = sync_catalog_episode_titles(
                catalog_path,
                limit=EPISODE_TITLE_BATCH_SIZE,
                skip_mal_ids=skip_titles,
            )
            title_result = (
                raw_titles
                if isinstance(raw_titles, EpisodeTitleSyncResult)
                else EpisodeTitleSyncResult(
                    updated=int(raw_titles),
                    attempted=int(raw_titles),
                )
            )
            titles_updated = int(title_result)
            with _lock:
                job.episode_titles = titles_updated
            try:
                refresh_anime_index(
                    catalog_path=catalog_path,
                    index_path=anime_index_path,
                )
            except (OSError, ValueError):
                pass
            more_hint = (
                " Run Sync anime titles again later for more batches if needed."
                if title_result.remaining > 0
                or titles_updated >= EPISODE_TITLE_BATCH_SIZE
                else ""
            )
            if title_result.attempted:
                detail = (
                    f"Anime titles synced: {titles_updated} updated"
                    f", {title_result.failed} failed"
                    f", {title_result.skipped} skipped"
                    f" ({title_result.attempted} attempted)"
                )
            else:
                detail = (
                    f"Anime titles synced: {titles_updated} updated"
                    f", {title_result.skipped} skipped"
                )
            if title_result.remaining:
                detail += f" · {title_result.remaining} remaining"
            if title_result.failed:
                if getattr(title_result, "jikan_unavailable", False):
                    detail += (
                        " · Jikan unavailable — retry Sync anime titles later"
                    )
                elif title_result.last_error:
                    detail += f" · {title_result.last_error}"
            _finish_ok(job, f"{detail}.{more_hint}")
        except (TimeoutError, OSError) as exc:
            _finish_error(job, f"Anime title sync failed: {exc}", exc)

    threading.Thread(target=runner, daemon=True, name="mal-sync-anime-titles").start()
    return job


def start_aniskip_sync(
    catalog_path,
    *,
    media_root=None,
    anime_index_path=None,
) -> SyncJob:
    """Fetch AniSkip OP/ED skip times for catalog episodes (no title sync)."""
    job = _begin_job("aniskip", "aniskip", "Fetching AniSkip…")
    if job is None:
        return get_sync_job()

    def runner() -> None:
        nonlocal job
        try:
            from kostream.aniskip import ensure_skip_times_for_episodes
            from kostream.library import scan_library

            skip_ids = skipped_mal_ids("aniskip", index_path=anime_index_path)
            fetched = 0
            shows_touched = 0
            for show in scan_library(media_root, catalog_path):
                if not show.mal_id:
                    continue
                mid = int(show.mal_id)
                if mid in skip_ids:
                    continue
                nums = [ep.number for ep in show.episodes if ep.number > 0]
                if not nums:
                    continue
                n = ensure_skip_times_for_episodes(mid, nums, network=True)
                if n:
                    fetched += n
                    shows_touched += 1
                with _lock:
                    job.aniskip = fetched
                    job.message = (
                        f"AniSkip: {fetched} episode fetch(es)"
                        f" across {shows_touched} title(s)…"
                    )
            with _lock:
                job.aniskip = fetched
            try:
                refresh_anime_index(
                    catalog_path=catalog_path,
                    media_root=media_root,
                    index_path=anime_index_path,
                )
            except (OSError, ValueError):
                pass
            _finish_ok(
                job,
                f"AniSkip synced: {fetched} episode fetch(es)"
                f" across {shows_touched} title(s).",
            )
        except (TimeoutError, OSError, ValueError, TypeError) as exc:
            _finish_error(job, f"AniSkip sync failed: {exc}", exc)

    threading.Thread(target=runner, daemon=True, name="mal-sync-aniskip").start()
    return job


def start_chapter_title_sync(
    *,
    manga_catalog_path=None,
    manga_media_root=None,
    manga_index_path=None,
) -> SyncJob:
    """Fetch MangaDex chapter titles only (metadata, no images)."""
    job = _begin_job("chapter_titles", "chapter_titles", "Fetching chapter titles…")
    if job is None:
        return get_sync_job()

    def runner() -> None:
        nonlocal job
        try:
            skip_chapters = skipped_mal_ids("chapter_titles", index_path=manga_index_path)
            chapter_result = sync_catalog_chapter_titles(
                manga_catalog_path,
                manga_media_root=manga_media_root,
                limit=CHAPTER_TITLE_BATCH_SIZE,
                skip_mal_ids=skip_chapters,
            )
            with _lock:
                job.chapter_titles = chapter_result.updated
            try:
                refresh_manga_index(
                    manga_catalog_path=manga_catalog_path,
                    manga_media_root=manga_media_root,
                    index_path=manga_index_path,
                )
            except (OSError, ValueError):
                pass
            more_hint = (
                " Run Sync chapter titles again later for more batches if needed."
                if chapter_result.updated >= CHAPTER_TITLE_BATCH_SIZE
                or (
                    chapter_result.attempted > 0
                    and chapter_result.updated < chapter_result.attempted
                )
                else ""
            )
            chapter_note = f"chapter titles {chapter_result.updated}"
            if (
                chapter_result.attempted
                and chapter_result.updated == 0
                and (chapter_result.failed or chapter_result.unresolved)
            ):
                bits = []
                if chapter_result.unresolved:
                    bits.append(f"{chapter_result.unresolved} unresolved")
                if chapter_result.failed:
                    bits.append(f"{chapter_result.failed} failed")
                chapter_note = (
                    f"chapter titles 0/{chapter_result.attempted} "
                    f"({', '.join(bits)}"
                    + (
                        f": {chapter_result.last_error}"
                        if chapter_result.last_error
                        else ""
                    )
                    + ")"
                )
            _finish_ok(job, f"Chapter titles synced: {chapter_note}.{more_hint}")
        except (TimeoutError, OSError) as exc:
            _finish_error(job, f"Chapter title sync failed: {exc}", exc)

    threading.Thread(target=runner, daemon=True, name="mal-sync-chapter-titles").start()
    return job
