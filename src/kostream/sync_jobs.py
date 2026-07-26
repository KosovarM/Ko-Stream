"""Background MAL sync / enrich jobs so the UI is not blocked."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from kostream.mal import (
    ENRICH_BATCH_SIZE,
    MalConfig,
    MalError,
    enrich_catalog_mal_details,
    sync_animelist_to_catalog,
)

_lock = threading.Lock()
_job: SyncJob | None = None


@dataclass
class SyncJob:
    status: str = "idle"  # idle | running | done | error
    phase: str = ""  # list | enrich | done
    synced: int = 0
    enriched: int = 0
    message: str = ""
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "phase": self.phase,
            "synced": self.synced,
            "enriched": self.enriched,
            "message": self.message,
            "error": self.error,
            "running": self.status == "running",
        }


def get_sync_job() -> SyncJob:
    global _job
    with _lock:
        return _job or SyncJob(status="idle", message="No sync yet.")


def start_mal_sync(cfg: MalConfig, catalog_path) -> SyncJob:
    """Start list sync + background enrich. Returns current job (may already be running)."""
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
                job.phase = "enrich"
                job.message = (
                    f"List synced ({count} anime). Fetching prequel/sequel metadata…"
                )
            enriched = 0
            try:
                enriched = enrich_catalog_mal_details(
                    cfg, catalog_path, limit=ENRICH_BATCH_SIZE
                )
            except (MalError, TimeoutError, OSError) as exc:
                with _lock:
                    job.enriched = enriched
                    job.status = "done"
                    job.phase = "done"
                    job.finished_at = time.time()
                    job.message = (
                        f"Synced {count} anime. Metadata enrich partial "
                        f"({enriched}): {exc}"
                    )
                return
            with _lock:
                job.enriched = enriched
                job.status = "done"
                job.phase = "done"
                job.finished_at = time.time()
                job.message = (
                    f"Synced {count} anime · enriched {enriched} titles with relations. "
                    "Run Sync again later for more batches if needed."
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
