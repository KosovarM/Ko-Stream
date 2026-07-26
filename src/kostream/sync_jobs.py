"""Background MAL sync / enrich jobs so the UI is not blocked."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from kostream.mal import (
    ENRICH_BATCH_SIZE,
    EPISODE_TITLE_BATCH_SIZE,
    MalConfig,
    MalError,
    enrich_catalog_mal_details,
    sync_animelist_to_catalog,
    sync_catalog_episode_titles,
    sync_mangalist_to_catalog,
)

_lock = threading.Lock()
_job: SyncJob | None = None


@dataclass
class SyncJob:
    status: str = "idle"  # idle | running | done | error
    phase: str = ""  # list | manga | enrich | episode_titles | done
    synced: int = 0
    manga_synced: int = 0
    enriched: int = 0
    episode_titles: int = 0
    message: str = ""
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "phase": self.phase,
            "synced": self.synced,
            "manga_synced": self.manga_synced,
            "enriched": self.enriched,
            "episode_titles": self.episode_titles,
            "message": self.message,
            "error": self.error,
            "running": self.status == "running",
        }


def get_sync_job() -> SyncJob:
    global _job
    with _lock:
        return _job or SyncJob(status="idle", message="No sync yet.")


def start_mal_sync(
    cfg: MalConfig,
    catalog_path,
    *,
    manga_catalog_path=None,
    manga_media_root=None,
) -> SyncJob:
    """Start anime + manga list sync + background enrich + episode titles."""
    global _job
    with _lock:
        if _job and _job.status == "running":
            return _job
        job = SyncJob(status="running", phase="list", message="Syncing animelist…")
        _job = job

    def runner() -> None:
        nonlocal job
        try:
            count = sync_animelist_to_catalog(cfg, catalog_path, enrich=False)
            with _lock:
                job.synced = count
                job.phase = "manga"
                job.message = f"List synced ({count} anime). Syncing mangalist…"
            manga_count = 0
            try:
                manga_count = sync_mangalist_to_catalog(
                    cfg,
                    manga_catalog_path=manga_catalog_path,
                    manga_media_root=manga_media_root,
                )
            except (MalError, TimeoutError, OSError) as exc:
                with _lock:
                    job.manga_synced = 0
                    job.phase = "enrich"
                    job.message = (
                        f"List synced ({count} anime). Manga sync failed ({exc}); "
                        "fetching prequel/sequel metadata…"
                    )
            else:
                with _lock:
                    job.manga_synced = manga_count
                    job.phase = "enrich"
                    job.message = (
                        f"Synced {count} anime · {manga_count} manga. "
                        "Fetching prequel/sequel metadata…"
                    )
            enriched = 0
            try:
                enriched = enrich_catalog_mal_details(
                    cfg, catalog_path, limit=ENRICH_BATCH_SIZE
                )
            except (MalError, TimeoutError, OSError) as exc:
                with _lock:
                    job.enriched = enriched
                    job.phase = "episode_titles"
                    job.message = (
                        f"Synced {count} anime · {manga_count} manga. "
                        f"Metadata enrich partial ({enriched}): {exc}. "
                        "Fetching episode titles…"
                    )
            else:
                with _lock:
                    job.enriched = enriched
                    job.phase = "episode_titles"
                    job.message = (
                        f"Synced {count} anime · {manga_count} manga · "
                        f"enriched {enriched}. Fetching episode titles…"
                    )

            titles_updated = 0
            try:
                titles_updated = sync_catalog_episode_titles(
                    catalog_path, limit=EPISODE_TITLE_BATCH_SIZE
                )
            except (TimeoutError, OSError) as exc:
                with _lock:
                    job.episode_titles = titles_updated
                    job.status = "done"
                    job.phase = "done"
                    job.finished_at = time.time()
                    job.message = (
                        f"Synced {count} anime · {manga_count} manga · "
                        f"enriched {enriched}. Episode titles partial "
                        f"({titles_updated}): {exc}"
                    )
                return

            with _lock:
                job.episode_titles = titles_updated
                job.status = "done"
                job.phase = "done"
                job.finished_at = time.time()
                more_hint = (
                    " Run Sync again later for more batches if needed."
                    if enriched >= ENRICH_BATCH_SIZE
                    or titles_updated >= EPISODE_TITLE_BATCH_SIZE
                    else ""
                )
                job.message = (
                    f"Synced {count} anime · {manga_count} manga · "
                    f"enriched {enriched} · episode titles {titles_updated}."
                    f"{more_hint}"
                )
        except (MalError, TimeoutError, OSError) as exc:
            with _lock:
                job.status = "error"
                job.phase = "done"
                job.error = str(exc)
                job.finished_at = time.time()
                job.message = f"Sync failed: {exc}"

    threading.Thread(target=runner, daemon=True, name="mal-sync").start()
    return job
