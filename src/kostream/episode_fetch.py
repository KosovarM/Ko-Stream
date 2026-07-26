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
from kostream.stream_fetch import (
    StreamFetchError,
    fetch_stream_to_file,
    resolve_fetch_source,
)


def fetch_episode_from_url(
    show: Show,
    episode: Episode,
    url: str,
    media_root: Path,
    *,
    catalog_path: Path | None = None,
    registry_path: Path | None = None,
) -> dict:
    """Copy/download ``url`` to SxxExx.mp4 under the show folder and register it."""
    try:
        kind, source = resolve_fetch_source(url)
    except StreamFetchError as exc:
        raise LocalMediaError(str(exc)) from exc

    info = prepare_show_folder(show, media_root, catalog_path=catalog_path)
    folder = Path(info["folder_path"])
    filename = expected_episode_filename(episode, ext=".mp4")
    dest = folder / filename

    source_label = str(source)
    try:
        fetch_stream_to_file(url, dest)
    except StreamFetchError as exc:
        raise LocalMediaError(str(exc)) from exc

    entry = mark_local(
        show.id,
        episode.id,
        path=str(dest),
        filename=filename,
        source_url=source_label if kind == "http" else f"file://{source}",
        registry_path=registry_path,
    )
    return {
        "ok": True,
        "filename": filename,
        "path": str(dest),
        "folder": info["folder"],
        "episode_id": episode.id,
        "source_kind": kind,
        "registry": entry,
        "registry_updated": True,
    }
