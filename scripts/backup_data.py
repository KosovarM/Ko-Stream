#!/usr/bin/env python3
"""Zip Ko-Stream ``data/`` for backup (accounts, progress, tokens, catalogs).

Usage (from repo root)::

    python scripts/backup_data.py
    python scripts/backup_data.py --out D:\\Backups\\kostream-data.zip
    python scripts/backup_data.py --include-cache   # also AniList/MAL API caches

Excludes bulky API caches by default. Does not backup media files.
"""

from __future__ import annotations

import argparse
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = REPO_ROOT / "data"

# Skip by default — regenerable / large
_CACHE_DIR_NAMES = {"cache", "anilist"}
_CACHE_PATH_PARTS = (
    ("mal", "cache"),
    ("cache",),
)


def _is_cache_path(rel: Path) -> bool:
    parts = rel.parts
    if not parts:
        return False
    if parts[0] in _CACHE_DIR_NAMES:
        return True
    for skip in _CACHE_PATH_PARTS:
        if len(parts) >= len(skip) and parts[: len(skip)] == skip:
            return True
    return False


def build_zip(
    data_dir: Path,
    out_path: Path,
    *,
    include_cache: bool = False,
) -> tuple[Path, int]:
    data_dir = data_dir.resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError(f"data dir not found: {data_dir}")

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(data_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(data_dir)
            if not include_cache and _is_cache_path(rel):
                continue
            # Skip lock leftovers
            if path.suffix == ".lock" or path.name.endswith(".lock"):
                continue
            zf.write(path, arcname=str(Path("data") / rel))
            count += 1
    return out_path, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA,
        help=f"Path to data/ (default: {DEFAULT_DATA})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output zip path (default: backups/kostream-data-YYYYMMDD-HHMMSS.zip)",
    )
    parser.add_argument(
        "--include-cache",
        action="store_true",
        help="Include regenerable API caches under data/cache and data/mal/cache",
    )
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = args.out or (REPO_ROOT / "backups" / f"kostream-data-{stamp}.zip")

    path, count = build_zip(args.data, out, include_cache=args.include_cache)
    print(f"Wrote {path} ({count} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
