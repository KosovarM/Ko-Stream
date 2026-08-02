"""Local media helpers — prepare show folders and store uploaded episode files."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any

from kostream.catalog import CatalogEntry, load_catalog, save_catalog, upsert_entry
from kostream.local_registry import mark_local
from kostream.models import (
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    Episode,
    Show,
    is_local_file_episode,
)
from kostream.requests_store import show_local_counts

_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_FOLDER_LEN = 120
_SUB_LANG_TOKEN = re.compile(r"^[a-z]{2,3}$")


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
            stem = f"S{ep.season:02d}E{ep.number:02d}"
            on_disk = any(
                (folder_path / f"{stem}{ext}").is_file() for ext in VIDEO_EXTENSIONS
            ) or is_local_file_episode(ep)
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
    catalog = load_catalog(catalog_path)
    entry = catalog.get(show.id)
    name = _sanitize_folder_name(folder_name or suggest_folder_name(show, entry))
    folder_path = _ensure_show_dir(media_root, name)

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
    info = build_local_info(show, media_root, catalog_path=catalog_path)
    # Prefer the directory we actually created — avoid stale catalog/title mismatch.
    info["folder"] = name
    info["folder_path"] = str(folder_path)
    info["folder_exists"] = folder_path.is_dir()
    info["under_media_root"] = _is_under(folder_path, media_root.resolve())
    return info


def list_incomplete_shows(
    shows: list[Show],
    media_root: Path,
    *,
    catalog_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Catalog shows that still have at least one missing local episode."""
    rows: list[dict[str, Any]] = []
    for show in shows:
        local_info = build_local_info(show, media_root, catalog_path=catalog_path)
        local_count, expected = show_local_counts(show, local_info)
        if expected <= 0 or local_count >= expected:
            continue
        missing = [ep for ep in local_info["episodes"] if not ep.get("is_local")]
        if not missing:
            continue
        rows.append(
            {
                "id": show.id,
                "title": show.title,
                "local_count": local_count,
                "expected_count": expected,
                "missing_count": len(missing),
            }
        )
    rows.sort(key=lambda row: str(row.get("title") or "").casefold())
    return rows


def list_missing_episodes(
    show: Show,
    media_root: Path,
    *,
    catalog_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return episode slots that are not yet available as local files."""
    info = build_local_info(show, media_root, catalog_path=catalog_path)
    return [ep for ep in info["episodes"] if not ep.get("is_local")]


def episode_already_on_disk(
    show: Show,
    episode: Episode,
    media_root: Path,
    *,
    catalog_path: Path | None = None,
) -> bool:
    """True when the episode is local or any SxxExx video already exists."""
    info = build_local_info(show, media_root, catalog_path=catalog_path)
    for ep in info["episodes"]:
        if ep.get("episode_id") == episode.id and ep.get("is_local"):
            return True
    folder_name = info.get("folder") or suggest_folder_name(show)
    folder_path = media_root / folder_name
    if not folder_path.is_dir():
        return False
    stem = f"S{episode.season:02d}E{episode.number:02d}"
    for ext in VIDEO_EXTENSIONS:
        if (folder_path / f"{stem}{ext}").is_file():
            return True
    return False


def expected_subtitle_filename(episode: Episode, upload_name: str) -> str:
    """Map an uploaded subtitle name to ``SxxExx[.lang].vtt``."""
    name = Path(upload_name).name
    ext = Path(name).suffix.lower()
    if ext not in SUBTITLE_EXTENSIONS:
        raise LocalMediaError(
            f"Unsupported subtitle type {ext or '(none)'}. Use: {', '.join(sorted(SUBTITLE_EXTENSIONS))}"
        )
    stem = f"S{episode.season:02d}E{episode.number:02d}"
    base = Path(name).stem
    token = ""
    if "." in base:
        maybe = base.rsplit(".", 1)[-1].casefold()
        if _SUB_LANG_TOKEN.match(maybe):
            token = maybe
    return f"{stem}.{token}{ext}" if token else f"{stem}{ext}"


def save_episode_file(
    show: Show,
    episode: Episode,
    upload_name: str,
    data: bytes,
    media_root: Path,
    *,
    catalog_path: Path | None = None,
    require_missing: bool = False,
) -> dict:
    """Store an uploaded video as SxxExx.<ext> in the show folder."""
    if not data:
        raise LocalMediaError("Empty upload")
    ext = Path(upload_name).suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        raise LocalMediaError(
            f"Unsupported type {ext or '(none)'}. Use: {', '.join(sorted(VIDEO_EXTENSIONS))}"
        )

    if require_missing and episode_already_on_disk(
        show, episode, media_root, catalog_path=catalog_path
    ):
        raise LocalMediaError("Episode is already available")

    info = prepare_show_folder(show, media_root, catalog_path=catalog_path)
    # Re-ensure under anime root (first upload for a title must create the folder).
    folder_path = _ensure_show_dir(media_root, str(info["folder"]))
    target_name = expected_episode_filename(episode, ext=ext)
    target = _safe_child_file(folder_path, target_name)
    if require_missing and target.is_file():
        raise LocalMediaError("Episode file already exists")
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise LocalMediaError(f"Could not write episode file: {exc}") from exc
    entry = mark_local(
        show.id,
        episode.id,
        path=str(target),
        filename=target_name,
        source_url=None,
    )
    return {
        "ok": True,
        "filename": target_name,
        "path": str(target),
        "folder": info["folder"],
        "episode_id": episode.id,
        "registry": entry,
        "registry_updated": True,
    }


def save_subtitle_file(
    show: Show,
    episode: Episode,
    upload_name: str,
    data: bytes,
    media_root: Path,
    *,
    catalog_path: Path | None = None,
) -> dict:
    """Store an optional WebVTT sidecar next to the episode video."""
    if not data:
        raise LocalMediaError("Empty subtitle upload")
    target_name = expected_subtitle_filename(episode, upload_name)
    info = prepare_show_folder(show, media_root, catalog_path=catalog_path)
    folder_path = _ensure_show_dir(media_root, str(info["folder"]))
    target = _safe_child_file(folder_path, target_name)
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise LocalMediaError(f"Could not write subtitle file: {exc}") from exc
    return {
        "ok": True,
        "filename": target_name,
        "path": str(target),
        "folder": info["folder"],
        "episode_id": episode.id,
    }


_SXXEXX = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})")
_EP_ONLY = re.compile(r"(?:^|[^\d])(?:[Ee](?:p(?:isode)?)?[\s._-]*)(\d{1,3})(?:[^\d]|$)")


def parse_episode_slot_from_filename(name: str) -> tuple[int, int] | None:
    """Return ``(season, episode)`` guessed from a video filename, if any."""
    stem = Path(name).stem
    m = _SXXEXX.search(stem) or _SXXEXX.search(name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = _EP_ONLY.search(stem)
    if m2:
        return 1, int(m2.group(1))
    return None


def save_bulk_episode_files(
    show: Show,
    files: list[tuple[str, bytes]],
    media_root: Path,
    *,
    catalog_path: Path | None = None,
    subtitles: list[tuple[str, bytes]] | None = None,
) -> dict[str, Any]:
    """Upload many episode videos (+ optional .vtt) for one show.

    Videos are matched to missing slots by ``SxxExx`` / ``E##`` in the filename,
    then remaining files fill remaining missing episodes in order.
    """
    if not files:
        raise LocalMediaError("No video files provided")
    missing = list_missing_episodes(show, media_root, catalog_path=catalog_path)
    if not missing:
        raise LocalMediaError("No missing episodes for this title")
    by_id = {ep.id: ep for ep in show.episodes}
    missing_eps = [by_id[m["episode_id"]] for m in missing if m.get("episode_id") in by_id]
    remaining = list(missing_eps)
    uploaded: list[dict[str, Any]] = []
    errors: list[str] = []

    # Pair subtitles by stem when possible
    sub_by_stem: dict[str, tuple[str, bytes]] = {}
    for sub_name, sub_data in subtitles or []:
        stem = Path(sub_name).stem
        # Strip language token for matching: S01E01.en → S01E01
        if "." in stem:
            maybe = stem.rsplit(".", 1)[0]
            sub_by_stem[maybe.casefold()] = (sub_name, sub_data)
        sub_by_stem[stem.casefold()] = (sub_name, sub_data)

    claimed: set[str] = set()
    deferred: list[tuple[str, bytes]] = []

    for upload_name, data in files:
        slot = parse_episode_slot_from_filename(upload_name)
        episode = None
        if slot:
            season, number = slot
            episode = next(
                (
                    ep
                    for ep in remaining
                    if ep.season == season and ep.number == number and ep.id not in claimed
                ),
                None,
            )
        if episode is None:
            deferred.append((upload_name, data))
            continue
        try:
            result = save_episode_file(
                show,
                episode,
                upload_name,
                data,
                media_root,
                catalog_path=catalog_path,
                require_missing=True,
            )
            stem = Path(result["filename"]).stem
            sub_result = None
            pair = sub_by_stem.get(stem.casefold()) or sub_by_stem.get(Path(upload_name).stem.casefold())
            if pair:
                sub_result = save_subtitle_file(
                    show, episode, pair[0], pair[1], media_root, catalog_path=catalog_path
                )
            claimed.add(episode.id)
            remaining = [ep for ep in remaining if ep.id not in claimed]
            uploaded.append({**result, "subtitle": sub_result})
        except LocalMediaError as exc:
            errors.append(f"{upload_name}: {exc}")

    for upload_name, data in deferred:
        if not remaining:
            errors.append(f"{upload_name}: no missing episode slot left")
            continue
        episode = remaining[0]
        try:
            result = save_episode_file(
                show,
                episode,
                upload_name,
                data,
                media_root,
                catalog_path=catalog_path,
                require_missing=True,
            )
            stem = Path(result["filename"]).stem
            sub_result = None
            pair = sub_by_stem.get(stem.casefold()) or sub_by_stem.get(Path(upload_name).stem.casefold())
            if pair:
                sub_result = save_subtitle_file(
                    show, episode, pair[0], pair[1], media_root, catalog_path=catalog_path
                )
            claimed.add(episode.id)
            remaining = [ep for ep in remaining if ep.id not in claimed]
            uploaded.append({**result, "subtitle": sub_result})
        except LocalMediaError as exc:
            errors.append(f"{upload_name}: {exc}")

    if not uploaded and errors:
        raise LocalMediaError(errors[0])
    return {
        "ok": True,
        "uploaded": uploaded,
        "uploaded_count": len(uploaded),
        "errors": errors,
        "remaining_missing": len(remaining),
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


def _ensure_show_dir(media_root: Path, folder_name: str) -> Path:
    """Resolve a path-safe show folder under ``media_root`` and create it."""
    name = _sanitize_folder_name(folder_name)
    try:
        media_root.mkdir(parents=True, exist_ok=True)
        folder_path = _safe_child_dir(media_root, name)
        folder_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LocalMediaError(f"Could not create show folder: {exc}") from exc
    return folder_path


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
