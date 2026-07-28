"""Remove inbox anime files already present in library (same byte size). No copies."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Reuse mapping/parsing from import script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_anime_downloads import (  # noqa: E402
    DOWNLOADS,
    FOLDER_MAP,
    MEDIA_ROOT,
    SKIP_EXT,
    VIDEO_EXTS,
    _map_entry,
    _video_exists_for_episode,
    import_subtitles,
    parse_episode,
    parse_vtt_sidecar,
    target_name,
)


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def cleanup_videos(*, dry_run: bool) -> dict:
    deleted: list[str] = []
    skipped_no_dest: list[str] = []
    skipped_conflict: list[str] = []
    skipped_unknown: list[str] = []
    unmapped: list[str] = []
    bytes_freed = 0
    empty_dirs: list[str] = []

    for src_dir in sorted(DOWNLOADS.iterdir()):
        if not src_dir.is_dir():
            continue
        name = src_dir.name
        if name not in FOLDER_MAP:
            unmapped.append(name)
            continue
        folder_name, _catalog_id, ep_offset = _map_entry(FOLDER_MAP[name])
        dest_dir = MEDIA_ROOT / folder_name

        for src_file in sorted(src_dir.iterdir()):
            if not src_file.is_file():
                continue
            if src_file.suffix.lower() in SKIP_EXT or src_file.stat().st_size == 0:
                continue
            if src_file.suffix.lower() == ".vtt":
                continue
            parsed = parse_episode(src_file.name)
            if not parsed:
                skipped_unknown.append(str(src_file))
                continue
            ep, ext = parsed
            if ext.lower() not in VIDEO_EXTS:
                continue
            dest_file = dest_dir / target_name(ep + ep_offset, ext)
            src_size = src_file.stat().st_size
            if not dest_file.is_file():
                skipped_no_dest.append(f"{src_file.name} -> {folder_name}/{dest_file.name}")
                continue
            dest_size = dest_file.stat().st_size
            if dest_size != src_size:
                skipped_conflict.append(
                    f"{src_file.name} in {name}: "
                    f"library {dest_size} vs inbox {src_size}"
                )
                continue
            if dry_run:
                deleted.append(str(src_file))
                bytes_freed += src_size
            else:
                try:
                    src_file.unlink()
                    deleted.append(str(src_file))
                    bytes_freed += src_size
                except OSError as err:
                    skipped_conflict.append(f"delete failed {src_file}: {err}")

    return {
        "deleted": deleted,
        "skipped_no_dest": skipped_no_dest,
        "skipped_conflict": skipped_conflict,
        "skipped_unknown": skipped_unknown,
        "unmapped": unmapped,
        "bytes_freed": bytes_freed,
    }


def cleanup_subtitles(*, dry_run: bool) -> dict:
    deleted: list[str] = []
    skipped_no_dest: list[str] = []
    skipped_conflict: list[str] = []
    skipped_unknown: list[str] = []
    no_video: list[str] = []
    unmapped: list[str] = []
    bytes_freed = 0

    for src_dir in sorted(DOWNLOADS.iterdir()):
        if not src_dir.is_dir():
            continue
        name = src_dir.name
        if name not in FOLDER_MAP:
            continue
        folder_name, _catalog_id, ep_offset = _map_entry(FOLDER_MAP[name])
        dest_dir = MEDIA_ROOT / folder_name
        if not dest_dir.is_dir():
            continue

        for src_file in sorted(src_dir.rglob("*.vtt")):
            if not src_file.is_file() or src_file.stat().st_size == 0:
                continue
            parsed = parse_vtt_sidecar(src_file.name)
            if not parsed:
                skipped_unknown.append(str(src_file))
                continue
            ep_num, suffix = parsed
            ep = ep_num + ep_offset
            if not _video_exists_for_episode(dest_dir, ep):
                no_video.append(f"{folder_name}/S01E{ep:02d}{suffix}")
                continue
            dest_file = dest_dir / target_name(ep, suffix)
            src_size = src_file.stat().st_size
            if not dest_file.is_file():
                skipped_no_dest.append(str(src_file))
                continue
            dest_size = dest_file.stat().st_size
            if dest_size != src_size:
                skipped_conflict.append(
                    f"{src_file.name}: library {dest_size} vs inbox {src_size}"
                )
                continue
            if dry_run:
                deleted.append(str(src_file))
                bytes_freed += src_size
            else:
                try:
                    src_file.unlink()
                    deleted.append(str(src_file))
                    bytes_freed += src_size
                except OSError as err:
                    skipped_conflict.append(f"delete failed {src_file}: {err}")

    return {
        "deleted": deleted,
        "skipped_no_dest": skipped_no_dest,
        "skipped_conflict": skipped_conflict,
        "skipped_unknown": skipped_unknown,
        "no_video": no_video,
        "bytes_freed": bytes_freed,
    }


def remove_empty_inbox_dirs() -> list[str]:
    removed: list[str] = []
    for src_dir in sorted(DOWNLOADS.iterdir()):
        if not src_dir.is_dir():
            continue
        if name := src_dir.name:
            if name not in FOLDER_MAP:
                continue
        # Remove empty subs/ and show dirs
        for sub in sorted(src_dir.rglob("*"), reverse=True):
            if sub.is_dir():
                try:
                    sub.rmdir()
                except OSError:
                    pass
        try:
            src_dir.rmdir()
            removed.append(str(src_dir))
        except OSError:
            pass
    return removed


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    videos = cleanup_videos(dry_run=dry_run)
    subs = cleanup_subtitles(dry_run=dry_run)
    empty_dirs: list[str] = []
    if not dry_run:
        empty_dirs = remove_empty_inbox_dirs()

    total_deleted = len(videos["deleted"]) + len(subs["deleted"])
    total_freed = videos["bytes_freed"] + subs["bytes_freed"]

    print("MODE:", "dry-run" if dry_run else "delete")
    print("VIDEOS DELETED:", len(videos["deleted"]))
    print("SUBS DELETED:", len(subs["deleted"]))
    print("TOTAL FILES:", total_deleted)
    print("BYTES FREED:", total_freed, f"({_human_size(total_freed)})")
    print("NOT IN LIBRARY (kept):", len(videos["skipped_no_dest"]) + len(subs["skipped_no_dest"]))
    print("SIZE CONFLICTS (kept):", len(videos["skipped_conflict"]) + len(subs["skipped_conflict"]))
    print("UNKNOWN NAMES (kept):", len(videos["skipped_unknown"]) + len(subs["skipped_unknown"]))
    print("SUBS NO VIDEO (kept):", len(subs["no_video"]))
    print("UNMAPPED FOLDERS:", len(videos["unmapped"]))
    print("EMPTY DIRS REMOVED:", len(empty_dirs))

    if videos["skipped_conflict"]:
        print("\nVIDEO CONFLICTS (first 10):")
        for c in videos["skipped_conflict"][:10]:
            print(" !", c)
    if subs["skipped_conflict"]:
        print("\nSUB CONFLICTS (first 10):")
        for c in subs["skipped_conflict"][:10]:
            print(" !", c)
    if videos["unmapped"]:
        print("\nUNMAPPED (kept entirely):")
        for u in videos["unmapped"]:
            print(" ?", u)
    if empty_dirs:
        print("\nEMPTY DIRS REMOVED:")
        for d in empty_dirs[:20]:
            print(" -", d)
        if len(empty_dirs) > 20:
            print(f" ... and {len(empty_dirs) - 20} more")

    out = Path(__file__).resolve().parents[1] / "_cleanup_anime_report.json"
    out.write_text(
        json.dumps(
            {
                "dry_run": dry_run,
                "videos": {k: v for k, v in videos.items()},
                "subs": {k: v for k, v in subs.items()},
                "empty_dirs_removed": empty_dirs,
                "total_files_deleted": total_deleted,
                "bytes_freed": total_freed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
