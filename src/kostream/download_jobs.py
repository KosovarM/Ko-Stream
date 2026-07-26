"""Background jobs: download missing local episodes via external command.

``KOSTREAM_DOWNLOAD_CMD`` receives JSON on stdin (show + missing episodes +
destination folder). Ko-Stream does not resolve pirate sources — your script does
(when you have a legal URL source). Animdl's internal downloader is not vendored.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kostream.local_media import (
    LocalMediaError,
    expected_episode_filename,
    prepare_show_folder,
)
from kostream.models import Episode, Show, is_local_file_episode

DEFAULT_TIMEOUT = 60 * 60  # 1h for a batch

_lock = threading.Lock()
_jobs: dict[str, DownloadJob] = {}


@dataclass
class DownloadJob:
    show_id: str
    status: str = "idle"  # idle | running | done | error
    message: str = ""
    error: str | None = None
    missing: int = 0
    completed: int = 0
    folder: str | None = None
    folder_path: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "show_id": self.show_id,
            "status": self.status,
            "message": self.message,
            "error": self.error,
            "missing": self.missing,
            "completed": self.completed,
            "folder": self.folder,
            "folder_path": self.folder_path,
            "running": self.status == "running",
            "configured": bool(download_cmd()),
        }


def download_cmd() -> str | None:
    raw = os.environ.get("KOSTREAM_DOWNLOAD_CMD", "").strip()
    return raw or None


def download_configured() -> bool:
    return bool(download_cmd())


def get_download_job(show_id: str) -> DownloadJob:
    with _lock:
        return _jobs.get(show_id) or DownloadJob(
            show_id=show_id,
            status="idle",
            message="No download job yet.",
        )


def missing_episodes(show: Show) -> list[Episode]:
    return [ep for ep in show.episodes if not is_local_file_episode(ep)]


def build_download_payload(
    show: Show,
    episodes: list[Episode],
    *,
    folder: str,
    folder_path: Path,
) -> dict[str, Any]:
    return {
        "show_id": show.id,
        "title": show.title,
        "mal_id": show.mal_id,
        "folder": folder,
        "folder_path": str(folder_path),
        "episodes": [
            {
                "episode_id": ep.id,
                "season": ep.season,
                "number": ep.number,
                "title": ep.title,
                "expected_filename": expected_episode_filename(ep),
                "target_path": str(folder_path / expected_episode_filename(ep)),
            }
            for ep in episodes
        ],
    }


def start_download_missing(
    show: Show,
    media_root: Path,
    *,
    catalog_path: Path | None = None,
) -> DownloadJob:
    """Prepare folder and start external downloader for non-local episodes."""
    cmd = download_cmd()
    if not cmd:
        raise LocalMediaError(
            "Set KOSTREAM_DOWNLOAD_CMD to your downloader script "
            "(see scripts/download_missing.example.py)."
        )

    missing = missing_episodes(show)
    if not missing:
        job = DownloadJob(
            show_id=show.id,
            status="done",
            message="Nothing missing — all episodes are local.",
            missing=0,
            completed=0,
            finished_at=time.time(),
        )
        with _lock:
            _jobs[show.id] = job
        return job

    info = prepare_show_folder(show, media_root, catalog_path=catalog_path)
    folder_path = Path(info["folder_path"])
    payload = build_download_payload(
        show, missing, folder=info["folder"], folder_path=folder_path
    )

    with _lock:
        existing = _jobs.get(show.id)
        if existing and existing.status == "running":
            return existing
        job = DownloadJob(
            show_id=show.id,
            status="running",
            message=f"Downloading {len(missing)} missing episode(s)…",
            missing=len(missing),
            folder=info["folder"],
            folder_path=str(folder_path),
        )
        _jobs[show.id] = job

    def runner() -> None:
        try:
            result = _run_download_cmd(cmd, payload)
            with _lock:
                job.status = "done"
                job.message = result.get("message") or (
                    f"Downloader finished ({len(missing)} requested)."
                )
                job.completed = int(result.get("completed", 0))
                job.finished_at = time.time()
        except Exception as exc:  # noqa: BLE001 — surface any script failure
            with _lock:
                job.status = "error"
                job.error = str(exc)
                job.message = "Download failed."
                job.finished_at = time.time()

    threading.Thread(target=runner, daemon=True).start()
    return job


def _run_download_cmd(cmd: str, payload: dict[str, Any]) -> dict[str, Any]:
    argv = [a.strip('"') for a in shlex.split(cmd, posix=True)]
    if not argv:
        raise LocalMediaError("KOSTREAM_DOWNLOAD_CMD is empty")

    try:
        completed = subprocess.run(
            argv,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LocalMediaError(f"Downloader not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LocalMediaError("Downloader timed out") from exc

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        raise LocalMediaError(stderr or stdout or f"exit {completed.returncode}")

    if not stdout:
        return {"message": "Downloader exited 0.", "completed": 0}

    # Prefer last JSON object line if present.
    for line in reversed([ln.strip() for ln in stdout.splitlines() if ln.strip()]):
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {"message": stdout.splitlines()[-1], "completed": 0}
