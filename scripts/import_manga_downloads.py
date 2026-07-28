"""Import unsorted inbox -> D:\\Media\\Ko-Stream\\manga (copy CBZ, skip same-size dupes)."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

INBOX_ROOT = Path(os.environ.get("KOSTREAM_INBOX_ROOT", r"D:\UnsortedFiles\KoStream"))
DOWNLOADS = Path(os.environ.get("KOSTREAM_INBOX_MANGA", str(INBOX_ROOT / "Manga")))
MEDIA_ROOT = Path(r"D:\Media\Ko-Stream\manga")
MANGA_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "manga" / "selected.json"
)

# download folder -> (library folder, catalog id or None)
MANGA_MAP: dict[str, tuple[str, str | None]] = {
    "black_clover": ("Black Clover", "mal-manga-86337"),
    "Black_Clover": ("Black Clover", "mal-manga-86337"),
    "Chainsaw_Man": ("Chainsaw Man", "mal-manga-116778"),
    "DEATH_NOTE__Tanpenshuu": ("Death Note Tanpenshuu", "mal-manga-132335"),
    "Dice": ("Dice", None),
    "fate_type_redline": ("Fate type Redline", "mal-manga-123444"),
    "Fate_Extra_CCC__Fox_Tail": ("Fate Extra CCC Fox Tail", "mal-manga-61147"),
    "Fire_Punch": ("Fire Punch", "mal-manga-98270"),
    "Mieruko_chan": ("Mieruko-chan", "mal-manga-116790"),
    "Overgeared": ("Overgeared", "mal-manga-147727"),
    "ragna_crimson": ("Ragna Crimson", "mal-manga-106733"),
    "overgeared": ("Overgeared", "mal-manga-147727"),
    "Re_Zero_kara_Hajimeru_Isekai_Seikatsu___Daisshou___Outo_no_Ichinichi_Hen": (
        "Re Zero Daisshou Outo no Ichinichi Hen",
        None,
    ),
    "Sakamoto_Days": ("Sakamoto Days", "mal-manga-131334"),
    "shangri_la_frontier": ("Shangri-La Frontier", None),
    "Tomoshibi_no_Otr": ("Tomoshibi no Otr", None),
}

CBZ_EXT = {".cbz", ".zip"}
SKIP_EXT = {".part", ".crdownload"}
_CHAPTER_NUM = re.compile(r"([\d.]+)")


def _chapter_key(name: str) -> str | None:
    m = _CHAPTER_NUM.search(Path(name).stem)
    return m.group(1).rstrip(".") if m else None


def _padded_alt(name: str) -> str | None:
    m = re.match(r"(?i)Chapter (\d)(\..*)?\.cbz$", name)
    if not m:
        return None
    suffix = m.group(2) or ""
    return f"Chapter 0{m.group(1)}{suffix}.cbz"


def load_manga_catalog() -> dict:
    if not MANGA_CATALOG_PATH.exists():
        return {"titles": []}
    return json.loads(MANGA_CATALOG_PATH.read_text(encoding="utf-8"))


def save_manga_catalog(data: dict) -> None:
    MANGA_CATALOG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def ensure_catalog_folder(catalog_id: str | None, folder_name: str) -> bool:
    if not catalog_id:
        return False
    data = load_manga_catalog()
    titles = data.get("titles", [])
    updated = False
    for entry in titles:
        if entry.get("id") == catalog_id:
            if entry.get("folder") != folder_name:
                entry["folder"] = folder_name
                updated = True
            break
    if updated:
        save_manga_catalog(data)
    return updated


def _dest_has_same_chapter(dest_dir: Path, src_file: Path) -> bool:
    """True if library already has same chapter (any padding) with same byte size."""
    if not dest_dir.is_dir():
        return False
    key = _chapter_key(src_file.name)
    if not key:
        return False
    src_size = src_file.stat().st_size
    for existing in dest_dir.glob("*.cbz"):
        if _chapter_key(existing.name) != key:
            continue
        if existing.stat().st_size == src_size:
            return True
    return False


def import_all() -> dict:
    imported: list[str] = []
    skipped: list[str] = []
    conflicts: list[str] = []
    unmapped: list[str] = []
    catalog_updates: list[str] = []

    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

    for src_dir in sorted(DOWNLOADS.iterdir()):
        if not src_dir.is_dir():
            continue
        name = src_dir.name
        if name not in MANGA_MAP:
            unmapped.append(name)
            continue
        folder_name, catalog_id = MANGA_MAP[name]
        dest_dir = MEDIA_ROOT / folder_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        if ensure_catalog_folder(catalog_id, folder_name):
            catalog_updates.append(f"{catalog_id} -> {folder_name}")

        candidates: list[Path] = []
        for path in src_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in SKIP_EXT or path.stat().st_size == 0:
                continue
            if path.suffix.lower() in CBZ_EXT:
                candidates.append(path)
        # Loose CBZ at manga downloads root
        for path in sorted(candidates, key=lambda p: p.name.casefold()):
            dest_file = dest_dir / path.name
            src_size = path.stat().st_size
            if dest_file.exists():
                if dest_file.stat().st_size == src_size:
                    skipped.append(f"{folder_name}/{dest_file.name}")
                    continue
                conflicts.append(
                    f"{dest_file.name} in {folder_name}: size mismatch"
                )
                continue
            alt = _padded_alt(path.name)
            if alt and (dest_dir / alt).exists():
                if (dest_dir / alt).stat().st_size == src_size:
                    skipped.append(f"{folder_name}/{path.name} (dup of {alt})")
                    continue
            if _dest_has_same_chapter(dest_dir, path):
                skipped.append(f"{folder_name}/{path.name} (chapter dup)")
                continue
            shutil.copy2(path, dest_file)
            imported.append(f"{folder_name}/{dest_file.name}")

    return {
        "imported": imported,
        "skipped": skipped,
        "conflicts": conflicts,
        "unmapped": unmapped,
        "catalog_updates": catalog_updates,
    }


if __name__ == "__main__":
    result = import_all()
    print("IMPORTED:", len(result["imported"]))
    print("SKIPPED:", len(result["skipped"]))
    print("CONFLICTS:", len(result["conflicts"]))
    print("UNMAPPED:", result["unmapped"])
    print("CATALOG:", len(result["catalog_updates"]))
    for line in result["imported"][:25]:
        print(" +", line)
    if len(result["imported"]) > 25:
        print(f" ... and {len(result['imported']) - 25} more")
    for c in result["conflicts"][:10]:
        print(" !", c)
