"""Catalog manga chapter upload helpers (images / zip / cbz)."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any

from kostream.manga import (
    CBZ_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MangaTitle,
    _chapter_number_from_stem,
    clear_manga_scan_cache,
)
from kostream.manga_catalog import (
    MangaCatalogEntry,
    load_manga_catalog,
    save_manga_catalog,
    upsert_manga_entry,
)
from kostream.mangadex import load_cached_known_chapters, normalize_chapter_key

_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_FOLDER_LEN = 120


class MangaUploadError(Exception):
    """Invalid manga upload request."""


def _sanitize_folder_name(name: str) -> str:
    cleaned = _INVALID_FOLDER_CHARS.sub("", (name or "").strip())
    cleaned = cleaned.replace(":", " -")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        raise MangaUploadError("Folder name is empty")
    if cleaned in (".", ".."):
        raise MangaUploadError("Invalid folder name")
    return cleaned[:_MAX_FOLDER_LEN]


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _ensure_title_dir(manga_root: Path, folder_name: str) -> Path:
    name = _sanitize_folder_name(folder_name)
    manga_root.mkdir(parents=True, exist_ok=True)
    folder = (manga_root.resolve() / name).resolve()
    if not _is_under(folder, manga_root.resolve()) and folder != manga_root.resolve():
        raise MangaUploadError("Folder escapes manga root")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def prepare_manga_folder(
    manga: MangaTitle,
    manga_root: Path,
    *,
    catalog_path: Path | None = None,
) -> str:
    """Ensure a title folder exists and is linked on the manga catalog entry."""
    catalog = load_manga_catalog(catalog_path)
    entry = catalog.get(manga.id)
    folder = (entry.folder if entry and entry.folder else None) or manga.folder or manga.title
    name = _sanitize_folder_name(folder)
    _ensure_title_dir(manga_root, name)
    if entry:
        updated = MangaCatalogEntry(
            id=entry.id,
            enabled=entry.enabled,
            source=entry.source,
            folder=name,
            mal_id=entry.mal_id or manga.mal_id,
            title=entry.title or manga.title,
            media_type=entry.media_type or manga.media_type,
            mangadex_id=entry.mangadex_id,
            added_at=entry.added_at,
        )
    else:
        updated = MangaCatalogEntry(
            id=manga.id,
            enabled=True,
            source=manga.source or "local",
            folder=name,
            mal_id=manga.mal_id,
            title=manga.title,
            media_type=manga.media_type,
        )
    catalog = upsert_manga_entry(catalog, updated)
    save_manga_catalog(catalog, catalog_path)
    return name


def _local_chapter_keys(manga: MangaTitle) -> set[str]:
    keys: set[str] = set()
    for ch in manga.chapters:
        if not ch.available:
            continue
        stem = ch.relative if ch.relative not in (".", "") else ch.title
        num = _chapter_number_from_stem(stem) or _chapter_number_from_stem(ch.title)
        key = normalize_chapter_key(num) if num else None
        if key:
            keys.add(key)
    return keys


def list_missing_chapters(manga: MangaTitle) -> list[dict[str, Any]]:
    """Known-but-unavailable chapter slots for upload dropdown."""
    local = _local_chapter_keys(manga)
    missing: list[dict[str, Any]] = []
    known: list[str] = []
    if manga.mal_id:
        known = list(load_cached_known_chapters(manga.mal_id) or [])
    if not known and manga.num_chapters_mal > 0:
        known = [str(i) for i in range(1, int(manga.num_chapters_mal) + 1)]
    for key in known:
        nk = normalize_chapter_key(key) or key
        if nk in local:
            continue
        missing.append(
            {
                "chapter_key": nk,
                "title": f"Chapter {nk}",
                "label": f"Chapter {nk}",
            }
        )

    def _sort_key(row: dict[str, Any]) -> tuple:
        num = str(row.get("chapter_key") or "")
        try:
            return (0, float(num), num)
        except ValueError:
            return (1, 0.0, num)

    missing.sort(key=_sort_key)
    return missing


def list_incomplete_manga(titles: list[MangaTitle]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manga in titles:
        missing = list_missing_chapters(manga)
        if not missing:
            continue
        rows.append(
            {
                "id": manga.id,
                "title": manga.title,
                "missing_count": len(missing),
                "local_count": sum(1 for c in manga.chapters if c.available),
                "media_type": manga.media_type,
            }
        )
    rows.sort(key=lambda row: str(row.get("title") or "").casefold())
    return rows


def _chapter_already_on_disk(title_dir: Path, chapter_key: str) -> bool:
    key = normalize_chapter_key(chapter_key) or chapter_key
    candidates = {
        key,
        f"Chapter {key}",
        f"Ch.{key}",
        f"Ch {key}",
        f"c{key}",
    }
    for path in title_dir.iterdir():
        if path.name.startswith("."):
            continue
        stem = path.stem if path.is_file() else path.name
        num = _chapter_number_from_stem(stem) or _chapter_number_from_stem(path.name)
        nk = normalize_chapter_key(num) if num else None
        if nk == key:
            return True
        if path.name in candidates or stem in candidates:
            return True
    return False


def _write_cbz_from_images(target: Path, files: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            zf.writestr(name, data)


def save_chapter_upload(
    manga: MangaTitle,
    chapter_key: str,
    upload_name: str,
    data: bytes,
    manga_root: Path,
    *,
    catalog_path: Path | None = None,
    require_missing: bool = True,
) -> dict[str, Any]:
    """Store one chapter as CBZ/ZIP or image-folder under the title directory."""
    if not data:
        raise MangaUploadError("Empty upload")
    key = normalize_chapter_key(chapter_key) or str(chapter_key).strip()
    if not key:
        raise MangaUploadError("chapter_key required")

    folder_name = prepare_manga_folder(manga, manga_root, catalog_path=catalog_path)
    title_dir = _ensure_title_dir(manga_root, folder_name)
    if require_missing and _chapter_already_on_disk(title_dir, key):
        raise MangaUploadError("Chapter is already available")

    name = Path(upload_name).name
    ext = Path(name).suffix.lower()
    safe_stem = _sanitize_folder_name(f"Chapter {key}")

    if ext in CBZ_EXTENSIONS:
        target_name = f"{safe_stem}{ext if ext == '.cbz' else '.cbz'}"
        # Prefer .cbz extension even when source was .zip
        target_name = f"{safe_stem}.cbz"
        target = title_dir / target_name
        if require_missing and target.is_file():
            raise MangaUploadError("Chapter file already exists")
        # Validate zip
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                if not names:
                    raise MangaUploadError("Archive has no files")
        except zipfile.BadZipFile as exc:
            raise MangaUploadError("Invalid zip/cbz archive") from exc
        try:
            target.write_bytes(data)
        except OSError as exc:
            raise MangaUploadError(f"Could not write chapter: {exc}") from exc
        clear_manga_scan_cache()
        return {
            "ok": True,
            "filename": target.name,
            "folder": folder_name,
            "chapter_key": key,
            "kind": "cbz",
            "path": str(target),
        }

    if ext in IMAGE_EXTENSIONS:
        chapter_dir = title_dir / safe_stem
        if require_missing and chapter_dir.is_dir() and any(chapter_dir.iterdir()):
            raise MangaUploadError("Chapter folder already exists")
        chapter_dir.mkdir(parents=True, exist_ok=True)
        page_name = f"001{ext}"
        page = chapter_dir / page_name
        try:
            page.write_bytes(data)
        except OSError as exc:
            raise MangaUploadError(f"Could not write page: {exc}") from exc
        clear_manga_scan_cache()
        return {
            "ok": True,
            "filename": f"{safe_stem}/{page_name}",
            "folder": folder_name,
            "chapter_key": key,
            "kind": "dir",
            "path": str(chapter_dir),
        }

    raise MangaUploadError(
        f"Unsupported type {ext or '(none)'}. Use: "
        f"{', '.join(sorted(CBZ_EXTENSIONS | IMAGE_EXTENSIONS))}"
    )


def save_chapter_images_bulk(
    manga: MangaTitle,
    chapter_key: str,
    images: list[tuple[str, bytes]],
    manga_root: Path,
    *,
    catalog_path: Path | None = None,
    require_missing: bool = True,
) -> dict[str, Any]:
    """Store multiple page images as one chapter folder (or pack as CBZ)."""
    if not images:
        raise MangaUploadError("No images provided")
    key = normalize_chapter_key(chapter_key) or str(chapter_key).strip()
    folder_name = prepare_manga_folder(manga, manga_root, catalog_path=catalog_path)
    title_dir = _ensure_title_dir(manga_root, folder_name)
    if require_missing and _chapter_already_on_disk(title_dir, key):
        raise MangaUploadError("Chapter is already available")

    safe_stem = _sanitize_folder_name(f"Chapter {key}")
    chapter_dir = title_dir / safe_stem
    if require_missing and chapter_dir.is_dir() and any(chapter_dir.iterdir()):
        raise MangaUploadError("Chapter folder already exists")
    chapter_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for idx, (upload_name, data) in enumerate(images, start=1):
        if not data:
            continue
        ext = Path(upload_name).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        page = chapter_dir / f"{idx:03d}{ext}"
        page.write_bytes(data)
        written += 1
    if written <= 0:
        raise MangaUploadError("No valid image pages in upload")
    clear_manga_scan_cache()
    return {
        "ok": True,
        "filename": safe_stem,
        "folder": folder_name,
        "chapter_key": key,
        "kind": "dir",
        "page_count": written,
        "path": str(chapter_dir),
    }


def guess_chapter_key_from_filename(name: str) -> str | None:
    stem = Path(name).stem
    num = _chapter_number_from_stem(stem) or _chapter_number_from_stem(name)
    if not num:
        return None
    return normalize_chapter_key(num) or num
