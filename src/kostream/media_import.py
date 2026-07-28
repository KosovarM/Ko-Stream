"""Import anime media folders into the catalog with optional MAL linking."""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError

from kostream.anilist import AniListError, search_anime
from kostream.catalog import (
    CatalogEntry,
    CatalogState,
    find_matching_entry,
    load_catalog,
    remove_entry,
    save_catalog,
    upsert_entry,
)
from kostream.library import MEDIA_ROOT, _scan_show_folder
from kostream.mal import (
    MalConfig,
    MalError,
    ensure_episode_titles_async,
    get_valid_access_token,
    is_connected as mal_is_connected,
    merge_anime_details_into_cache,
    update_anime_list_status,
)
from kostream.manga_catalog import _manga_tokens
from kostream.media_title_aliases import (
    best_catalog_match,
    entry_match_keys,
    folder_mal_id,
    folder_match_keys,
    match_score,
    normalize_search_query,
)
from kostream.models import slugify

PLAN_TO_WATCH = "plan_to_watch"


@dataclass
class MediaImportResult:
    added: list[dict[str, Any]] = field(default_factory=list)
    linked: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    mal_synced: list[dict[str, Any]] = field(default_factory=list)
    mal_errors: list[dict[str, Any]] = field(default_factory=list)
    unmatched: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "linked": self.linked,
            "skipped": self.skipped,
            "mal_synced": self.mal_synced,
            "mal_errors": self.mal_errors,
            "unmatched": self.unmatched,
            "counts": {
                "added": len(self.added),
                "linked": len(self.linked),
                "skipped": len(self.skipped),
                "mal_synced": len(self.mal_synced),
                "mal_errors": len(self.mal_errors),
                "unmatched": len(self.unmatched),
            },
        }


def list_folders_with_videos(media_root: Path | None = None) -> list[str]:
    """Return sorted folder names under the anime root that contain playable files."""
    root = media_root or MEDIA_ROOT
    if not root.is_dir():
        return []
    folders: list[str] = []
    for show_dir in sorted(root.iterdir()):
        if not show_dir.is_dir() or show_dir.name.startswith("."):
            continue
        episodes, _mtime = _scan_show_folder(show_dir)
        if episodes:
            folders.append(show_dir.name)
    return folders


def preview_media_import(
    *,
    media_root: Path | None = None,
    catalog_path: Path | None = None,
) -> list[dict[str, Any]]:
    """List media folders not yet represented in the catalog (no mutation)."""
    root = media_root or MEDIA_ROOT
    state = load_catalog(catalog_path)
    folder_map = _load_folder_mal_map()
    rows: list[dict[str, Any]] = []
    for folder in list_folders_with_videos(root):
        action, entry, mal_id, title = _classify_folder(folder, state, folder_map)
        if action == "skip":
            continue
        rows.append(
            {
                "folder": folder,
                "action": action,
                "mal_id": mal_id,
                "title": title or folder,
                "catalog_id": entry.id if entry else (f"mal-{mal_id}" if mal_id else slugify(folder)),
            }
        )
    return rows


def import_media_to_catalog(
    *,
    media_root: Path | None = None,
    catalog_path: Path | None = None,
    user_id: str | None = None,
    mal_cfg: MalConfig | None = None,
    sync_mal: bool = True,
) -> MediaImportResult:
    """Add or link uncataloged media folders; optionally set MAL status plan_to_watch."""
    root = media_root or MEDIA_ROOT
    state = load_catalog(catalog_path)
    folder_map = _load_folder_mal_map()
    state, _repair_notes = repair_local_mal_links(state, folder_map)
    result = MediaImportResult()

    mal_ready = False
    if sync_mal and user_id and mal_cfg and mal_is_connected(user_id):
        try:
            get_valid_access_token(mal_cfg, user_id)
            mal_ready = True
        except MalError:
            mal_ready = False

    for folder in list_folders_with_videos(root):
        action, existing, mal_id, title = _classify_folder(folder, state, folder_map)
        if action == "skip":
            result.skipped.append({"folder": folder, "reason": "already in catalog"})
            continue

        if action == "link" and existing is not None:
            for stale in [e for e in state.shows if e.folder == folder and e.id != existing.id]:
                state = remove_entry(state, stale.id)
            updated = CatalogEntry(
                id=existing.id,
                enabled=existing.enabled,
                source=_mal_source(existing, mal_id),
                folder=folder,
                jellyfin_id=existing.jellyfin_id,
                anilist_id=existing.anilist_id,
                mal_id=existing.mal_id or mal_id,
                title=existing.title or title or folder,
                added_at=existing.added_at,
            )
            state = upsert_entry(state, updated)
            result.linked.append(
                {
                    "folder": folder,
                    "id": updated.id,
                    "mal_id": updated.mal_id,
                    "title": updated.title,
                }
            )
            entry = updated
        elif action == "upgrade" and existing is not None and mal_id is not None:
            entry, state = _upgrade_local_entry(
                state,
                existing=existing,
                folder=folder,
                mal_id=mal_id,
                title=title,
            )
            result.linked.append(
                {
                    "folder": folder,
                    "id": entry.id,
                    "mal_id": entry.mal_id,
                    "title": entry.title,
                }
            )
        else:
            entry_id = f"mal-{mal_id}" if mal_id else slugify(folder)
            source = "mal" if mal_id else "local"
            entry = CatalogEntry(
                id=entry_id,
                enabled=True,
                source=source,
                folder=folder,
                mal_id=mal_id,
                title=title or folder,
            )
            state = upsert_entry(state, entry)
            payload = {
                "folder": folder,
                "id": entry.id,
                "mal_id": mal_id,
                "title": entry.title,
                "source": source,
            }
            if mal_id:
                result.added.append(payload)
            else:
                result.unmatched.append(payload)

        if mal_id:
            _enrich_mal_cache(mal_cfg, user_id, mal_id, title or folder, mal_ready)
            if mal_ready and mal_cfg and user_id:
                try:
                    update_anime_list_status(
                        mal_cfg,
                        int(mal_id),
                        PLAN_TO_WATCH,
                        user_id=user_id,
                    )
                    result.mal_synced.append({"folder": folder, "mal_id": mal_id})
                except MalError as exc:
                    result.mal_errors.append(
                        {"folder": folder, "mal_id": mal_id, "error": str(exc)}
                    )
            ensure_episode_titles_async(int(mal_id))

    save_catalog(state, catalog_path)
    return result


def repair_local_mal_links(
    state: CatalogState,
    folder_map: dict[str, int],
) -> tuple[CatalogState, list[str]]:
    """Merge local-only folder rows into MAL-linked catalog entries."""
    notes: list[str] = []
    remove_ids: set[str] = set()

    for entry in list(state.shows):
        if not entry.folder or entry.mal_id is not None:
            continue
        folder = entry.folder
        mal_id = folder_map.get(folder)
        resolved_title: str | None = None
        if mal_id is None:
            mal_id = folder_mal_id(folder, folder_map)
        if mal_id is None:
            mal_id, resolved_title = _resolve_mal_from_search(folder)
        if mal_id is None:
            mal_id, _score = _resolve_mal_from_catalog(state, folder)
        if mal_id is None:
            continue

        target = find_matching_entry(state, mal_id=mal_id)
        if target and target.id != entry.id:
            if not target.folder:
                updated = CatalogEntry(
                    id=target.id,
                    enabled=target.enabled,
                    source=_mal_source(target, mal_id),
                    folder=folder,
                    jellyfin_id=target.jellyfin_id,
                    anilist_id=target.anilist_id,
                    mal_id=mal_id,
                    title=target.title or resolved_title or _title_for_mal(mal_id) or entry.title,
                    added_at=target.added_at,
                )
                state = upsert_entry(state, updated)
                notes.append(f"linked {folder} -> {target.id}")
            remove_ids.add(entry.id)
            continue

        entry, state = _upgrade_local_entry(
            state,
            existing=entry,
            folder=folder,
            mal_id=mal_id,
            title=resolved_title or entry.title,
        )
        notes.append(f"upgraded {folder} -> {entry.id}")

    for mid in {int(e.mal_id) for e in state.shows if e.mal_id is not None}:
        group = [e for e in state.shows if e.mal_id is not None and int(e.mal_id) == mid]
        if len(group) < 2:
            continue
        with_folder = [e for e in group if e.folder]
        if not with_folder:
            continue
        keep = next((e for e in with_folder if e.id == f"mal-{mid}"), with_folder[0])
        for entry in group:
            if entry.id != keep.id:
                remove_ids.add(entry.id)
                notes.append(f"deduped mal-{mid}: removed {entry.id}")

    for entry_id in remove_ids:
        state = remove_entry(state, entry_id)

    return state, notes


def _mal_source(entry: CatalogEntry, mal_id: int | None) -> str:
    if mal_id is not None:
        return "mal"
    return entry.source


def _upgrade_local_entry(
    state: CatalogState,
    *,
    existing: CatalogEntry,
    folder: str,
    mal_id: int,
    title: str | None,
) -> tuple[CatalogEntry, CatalogState]:
    target_id = f"mal-{mal_id}"
    duplicate = find_matching_entry(state, mal_id=mal_id)
    if duplicate and duplicate.id != existing.id:
        updated = CatalogEntry(
            id=duplicate.id,
            enabled=duplicate.enabled,
            source=_mal_source(duplicate, mal_id),
            folder=folder,
            jellyfin_id=duplicate.jellyfin_id,
            anilist_id=duplicate.anilist_id,
            mal_id=mal_id,
            title=duplicate.title or title or _title_for_mal(mal_id) or folder,
            added_at=duplicate.added_at or existing.added_at,
        )
        state = remove_entry(state, existing.id)
        state = upsert_entry(state, updated)
        return updated, state

    if existing.id != target_id:
        state = remove_entry(state, existing.id)
    updated = CatalogEntry(
        id=target_id,
        enabled=existing.enabled,
        source="mal",
        folder=folder,
        jellyfin_id=existing.jellyfin_id,
        anilist_id=existing.anilist_id,
        mal_id=mal_id,
        title=title or _title_for_mal(mal_id) or existing.title or folder,
        added_at=existing.added_at,
    )
    state = upsert_entry(state, updated)
    return updated, state


def _enrich_mal_cache(
    mal_cfg: MalConfig | None,
    user_id: str | None,
    mal_id: int,
    title: str | None,
    mal_ready: bool,
) -> None:
    if not mal_ready or not mal_cfg or not user_id:
        return
    try:
        access_token = get_valid_access_token(mal_cfg, user_id)
        merge_anime_details_into_cache(access_token, int(mal_id), title_fallback=title)
    except MalError:
        pass


def _classify_folder(
    folder: str,
    state: CatalogState,
    folder_map: dict[str, int],
) -> tuple[str, CatalogEntry | None, int | None, str | None]:
    """Return (action, entry, mal_id, title) where action is skip|link|add|upgrade."""
    folder_entry: CatalogEntry | None = None
    for entry in state.shows:
        if entry.folder == folder:
            folder_entry = entry
            break

    mal_id = folder_map.get(folder)
    if mal_id is None:
        mal_id = folder_mal_id(folder, folder_map)
    title = folder.replace("-", " ").replace("_", " ")

    if folder_entry is not None:
        if folder_entry.mal_id is not None:
            return "skip", folder_entry, folder_entry.mal_id, folder_entry.title
        resolved_mal = mal_id
        resolved_title = title
        if resolved_mal is None:
            resolved_mal, resolved_title = _resolve_mal_from_search(folder)
        if resolved_mal is None:
            resolved_mal, _score = _resolve_mal_from_catalog(state, folder)
        if resolved_mal is not None:
            existing = find_matching_entry(state, mal_id=resolved_mal)
            if existing and existing.id != folder_entry.id:
                return "link", existing, resolved_mal, existing.title or resolved_title or folder_entry.title
            return "upgrade", folder_entry, resolved_mal, resolved_title or folder_entry.title or title
        return "skip", folder_entry, None, folder_entry.title

    if mal_id is not None:
        existing = find_matching_entry(state, mal_id=mal_id)
        if existing:
            return "link", existing, mal_id, existing.title or title
        resolved_title = _title_for_mal(mal_id) or title
        return "add", None, mal_id, resolved_title

    existing = _find_entry_by_folder_title(state, folder)
    if existing:
        return "link", existing, existing.mal_id, existing.title or title

    resolved_mal, resolved_title = _resolve_mal_from_search(folder)
    if resolved_mal is None:
        resolved_mal, _score = _resolve_mal_from_catalog(state, folder)
        if resolved_mal is not None:
            resolved_title = _title_for_mal(resolved_mal)
    if resolved_mal:
        existing = find_matching_entry(state, mal_id=resolved_mal)
        if existing:
            return "link", existing, resolved_mal, existing.title or resolved_title
        return "add", None, resolved_mal, resolved_title or title

    if existing := find_matching_entry(state, entry_id=slugify(folder)):
        return "link", existing, existing.mal_id, existing.title or title

    return "add", None, None, title


def _find_entry_by_folder_title(state: CatalogState, folder: str) -> CatalogEntry | None:
    want_keys = folder_match_keys(folder)
    if not want_keys:
        return None

    best: CatalogEntry | None = None
    best_score = 0.0
    for entry in state.shows:
        if entry.folder:
            continue
        candidates: list[tuple[str | None, int | None]] = [(entry.title, entry.mal_id)]
        if entry.mal_id is not None:
            cached_title = _title_for_mal(int(entry.mal_id))
            if cached_title:
                candidates.append((cached_title, entry.mal_id))
        for title, mal_id in candidates:
            score = match_score(want_keys, entry_match_keys(title, mal_id=mal_id))
            if score > best_score:
                best = entry
                best_score = score

    if best is not None and best_score >= 0.45:
        return best

    # Legacy token overlap fallback for titles without alias coverage
    folder_tokens = set(_manga_tokens(normalize_search_query(folder)))
    legacy_best: CatalogEntry | None = None
    legacy_score = 0
    for entry in state.shows:
        if entry.folder:
            continue
        for candidate in (entry.title, entry.id.replace("mal-", "").replace("-", " ")):
            if not candidate:
                continue
            tokens = set(_manga_tokens(str(candidate)))
            if not tokens:
                continue
            overlap = tokens & folder_tokens
            score = len(overlap)
            if score >= 2 and score >= min(len(tokens), len(folder_tokens)) * 0.6:
                if score > legacy_score:
                    legacy_best = entry
                    legacy_score = score
    return legacy_best


def _resolve_mal_from_catalog(state: CatalogState, folder: str) -> tuple[int | None, float]:
    """Match folder to an existing catalog row by English/Japanese title aliases."""
    candidates = [
        (entry.title, entry.mal_id)
        for entry in state.shows
        if entry.mal_id is not None and not entry.folder
    ]
    mal_id, score = best_catalog_match(folder, candidates)
    return mal_id, score


def _resolve_mal_from_search(folder: str) -> tuple[int | None, str | None]:
    query = normalize_search_query(folder)
    if len(query) < 2:
        return None, None
    try:
        results = search_anime(query, limit=8)
    except (AniListError, URLError, OSError, ValueError):
        return None, None
    if not results:
        # Retry with simpler query (drop arc suffix noise)
        short = re.sub(r"\b(part|season|2nd|3rd)\b.*$", "", query, flags=re.IGNORECASE).strip()
        if short and short != query:
            try:
                results = search_anime(short, limit=8)
            except (AniListError, URLError, OSError, ValueError):
                return None, None
    if not results:
        return None, None
    want_keys = folder_match_keys(folder)
    best_mal: int | None = None
    best_title: str | None = None
    best_score = 0.0
    for item in results:
        if not item.mal_id:
            continue
        score = match_score(want_keys, entry_match_keys(item.title, mal_id=int(item.mal_id)))
        if score > best_score:
            best_score = score
            best_mal = int(item.mal_id)
            best_title = item.title
    if best_mal is not None and best_score >= 0.35:
        return best_mal, best_title
    first = next((r for r in results if r.mal_id), None)
    if first and len(query) >= 4:
        return int(first.mal_id), first.title
    return None, None


def _title_for_mal(mal_id: int) -> str | None:
    from kostream.mal import load_cached_anime

    cached = load_cached_anime(int(mal_id))
    if cached and cached.title:
        return cached.title
    return None


def _load_folder_mal_map() -> dict[str, int]:
    """Build library-folder → mal_id map from scripts/import_anime_downloads FOLDER_MAP."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "import_anime_downloads.py"
    if not script.is_file():
        return {}
    spec = importlib.util.spec_from_file_location("kostream_import_anime_downloads", script)
    if spec is None or spec.loader is None:
        return {}
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return {}
    raw = getattr(module, "FOLDER_MAP", None)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    from kostream.media_title_aliases import FOLDER_MAL_IDS

    for folder_name, mal_id in FOLDER_MAL_IDS.items():
        out[str(folder_name)] = int(mal_id)
    for _src, value in raw.items():
        try:
            if len(value) == 2:
                folder_name, catalog_id = value
                offset = 0
            else:
                folder_name, catalog_id, offset = value  # noqa: F841
            if not catalog_id or not str(catalog_id).startswith("mal-"):
                continue
            mal_id = int(str(catalog_id).replace("mal-", ""))
            out[str(folder_name)] = mal_id
        except (TypeError, ValueError):
            continue
    return out


def summarize_import(result: MediaImportResult) -> str:
    c = result.to_dict()["counts"]
    parts: list[str] = []
    if c["added"]:
        parts.append(f"{c['added']} added")
    if c["linked"]:
        parts.append(f"{c['linked']} linked")
    if c["skipped"]:
        parts.append(f"{c['skipped']} skipped")
    if c["unmatched"]:
        parts.append(f"{c['unmatched']} local-only (no MAL match)")
    if c["mal_synced"]:
        parts.append(f"{c['mal_synced']} set to Plan to Watch on MAL")
    if c["mal_errors"]:
        parts.append(f"{c['mal_errors']} MAL sync errors")
    if not parts:
        return "No new media folders to import."
    return "Import from media: " + ", ".join(parts) + "."
