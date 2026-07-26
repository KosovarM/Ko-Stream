"""High-level: fetch an explicit stream URL into the show library folder."""

from __future__ import annotations

from pathlib import Path

from kostream.local_media import (
    LocalMediaError,
    expected_episode_filename,
    prepare_show_folder,
)
from kostream.local_registry import mark_local
from kostream.models import Episode, Show
from kostream.stream_fetch import StreamFetchError, fetch_stream_to_file, validate_stream_url


def fetch_episode_from_url(
    show: Show,
    episode: Episode,
    url: str,
    media_root: Path,
    *,
    catalog_path: Path | None = None,
    registry_path: Path | None = None,
) -> dict:
    """Download ``url`` to SxxExx.mp4 under the show folder and register it."""
    try:
        cleaned = validate_stream_url(url)
    except StreamFetchError as exc:
        raise LocalMediaError(str(exc)) from exc

    info = prepare_show_folder(show, media_root, catalog_path=catalog_path)
    folder = Path(info["folder_path"])
    filename = expected_episode_filename(episode, ext=".mp4")
    dest = folder / filename

    try:
        fetch_stream_to_file(cleaned, dest)
    except StreamFetchError as exc:
        raise LocalMediaError(str(exc)) from exc

    entry = mark_local(
        show.id,
        episode.id,
        path=str(dest),
        filename=filename,
        source_url=cleaned,
        registry_path=registry_path,
    )
    return {
        "ok": True,
        "filename": filename,
        "path": str(dest),
        "folder": info["folder"],
        "episode_id": episode.id,
        "registry": entry,
    }
