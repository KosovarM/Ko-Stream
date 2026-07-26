"""Local media helpers — prepare show folders and store uploaded episode files."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path

from kostream.catalog import CatalogEntry, load_catalog, save_catalog, upsert_entry
from kostream.models import VIDEO_EXTENSIONS, Episode, Show, is_local_file_episode

_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_FOLDER_LEN = 120


class LocalMediaError(Exception):
    """Invalid folder/upload request."""


def suggest_folder_name(show: Show, entry: CatalogEntry | None = None) -> str:
    if entry and entry.folder and entry.folder.strip():
        return _sanitize_folder_name(entry.folder)
    base = show.title or show.id
    season = None
    if show.episodes:
        season = show.episodes[0].season
    if season and season > 1 and "season" not in base.lower():
        base = f"{base} Season {season}"
    return _sanitize_folder_name(base)


def expected_episode_filename(episode: Episode, *, ext: str = ".mp4") -> str:
    suffix = ext if ext.startswith(".") else f".{ext}"
    return f"S{episode.season:02d}E{episode.number:02d}{suffix.lower()}"


def build_local_info(
    show: Show,
    media_root: Path,
    *,
    catalog_path: Path | None = None,
) -> dict:
    catalog = load_catalog(catalog_path)
    entry = catalog.get(show.id)
    folder_name = suggest_folder_name(show, entry)
    folder_path = (media_root / folder_name).resolve()
    root = media_root.resolve()
    exists = folder_path.is_dir()
    episodes = []
    for ep in show.episodes:
        expected = expected_episode_filename(ep)
        on_disk = False
        if exists:
            on_disk = (folder_path / expected).is_file() or is_local_file_episode(ep)
        episodes.append(
            {
                "episode_id": ep.id,
                "season": ep.season,
                "number": ep.number,
                "title": ep.title,
                "expected_filename": expected,
                "is_local": is_local_file_episode(ep) or on_disk,
            }
        )
    return {
        "show_id": show.id,
        "folder": folder_name,
        "folder_path": str(folder_path),
        "folder_exists": exists,
        "relative_path": f"media/shows/{folder_name}",
        "under_media_root": _is_under(folder_path, root),
        "episodes": episodes,
    }


def prepare_show_folder(
    show: Show,
    media_root: Path,
    *,
    catalog_path: Path | None = None,
    folder_name: str | None = None,
) -> dict:
    """Create media folder if needed and attach ``folder`` on the catalog entry."""
    media_root.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog(catalog_path)
    entry = catalog.get(show.id)
    name = _sanitize_folder_name(folder_name or suggest_folder_name(show, entry))
    folder_path = _safe_child_dir(media_root, name)
    folder_path.mkdir(parents=True, exist_ok=True)

    if entry:
        updated = CatalogEntry(
            id=entry.id,
            enabled=entry.enabled,
            source=entry.source,
            folder=name,
            jellyfin_id=entry.jellyfin_id,
            anilist_id=entry.anilist_id,
            mal_id=entry.mal_id,
            title=entry.title or show.title,
            added_at=entry.added_at,
        )
    else:
        updated = CatalogEntry(
            id=show.id,
            enabled=True,
            source="local",
            folder=name,
            mal_id=show.mal_id,
            anilist_id=show.anilist_id,
            title=show.title,
        )
    catalog = upsert_entry(catalog, updated)
    save_catalog(catalog, catalog_path)
    return build_local_info(show, media_root, catalog_path=catalog_path)


def save_episode_file(
    show: Show,
    episode: Episode,
    upload_name: str,
    data: bytes,
    media_root: Path,
    *,
    catalog_path: Path | None = None,
) -> dict:
    """Store an uploaded video as SxxExx.<ext> in the show folder."""
    if not data:
        raise LocalMediaError("Empty upload")
    ext = Path(upload_name).suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        raise LocalMediaError(
            f"Unsupported type {ext or '(none)'}. Use: {', '.join(sorted(VIDEO_EXTENSIONS))}"
        )

    info = prepare_show_folder(show, media_root, catalog_path=catalog_path)
    folder_path = Path(info["folder_path"])
    target_name = expected_episode_filename(episode, ext=ext)
    target = _safe_child_file(folder_path, target_name)
    target.write_bytes(data)
    return {
        "ok": True,
        "filename": target_name,
        "path": str(target),
        "folder": info["folder"],
        "episode_id": episode.id,
    }


def open_folder_in_os(folder_path: Path) -> bool:
    """Best-effort open folder in the desktop file manager (local server only)."""
    path = folder_path.resolve()
    if not path.is_dir():
        return False
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        if system == "Darwin":
            subprocess.run(["open", str(path)], check=False)
            return True
        subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except OSError:
        return False


def _sanitize_folder_name(name: str) -> str:
    cleaned = _INVALID_FOLDER_CHARS.sub("", (name or "").strip())
    cleaned = cleaned.replace(":", " -")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        raise LocalMediaError("Folder name is empty")
    if cleaned in (".", ".."):
        raise LocalMediaError("Invalid folder name")
    return cleaned[:_MAX_FOLDER_LEN]


def _safe_child_dir(root: Path, name: str) -> Path:
    root_res = root.resolve()
    child = (root_res / name).resolve()
    if not _is_under(child, root_res):
        raise LocalMediaError("Folder escapes media root")
    return child


def _safe_child_file(folder: Path, filename: str) -> Path:
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise LocalMediaError("Invalid filename")
    folder_res = folder.resolve()
    target = (folder_res / filename).resolve()
    if not _is_under(target, folder_res):
        raise LocalMediaError("File escapes show folder")
    return target


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
