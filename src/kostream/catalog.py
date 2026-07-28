"""Curated catalog — load only selected shows (fast local dev)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kostream.jsonio import atomic_write_json
from kostream.models import slugify

CATALOG_DIR = Path(__file__).resolve().parents[2] / "data" / "catalog"
SELECTED_FILE = CATALOG_DIR / "selected.json"


@dataclass
class CatalogEntry:
    id: str
    enabled: bool = True
    source: str = "local"  # local | jellyfin | demo | mal
    folder: str | None = None
    jellyfin_id: str | None = None
    anilist_id: int | None = None
    mal_id: int | None = None
    title: str | None = None
    added_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> CatalogEntry:
        entry_id = data.get("id") or slugify(data.get("folder") or data.get("title", "show"))
        mal_id = data.get("mal_id")
        return cls(
            id=entry_id,
            enabled=bool(data.get("enabled", True)),
            source=data.get("source", "local"),
            folder=data.get("folder"),
            jellyfin_id=data.get("jellyfin_id"),
            anilist_id=int(data["anilist_id"]) if data.get("anilist_id") is not None else None,
            mal_id=int(mal_id) if mal_id is not None else None,
            title=data.get("title"),
            added_at=data.get("added_at"),
        )

    def to_dict(self) -> dict:
        payload = {
            "id": self.id,
            "enabled": self.enabled,
            "source": self.source,
        }
        if self.folder:
            payload["folder"] = self.folder
        if self.jellyfin_id:
            payload["jellyfin_id"] = self.jellyfin_id
        if self.anilist_id is not None:
            payload["anilist_id"] = self.anilist_id
        if self.mal_id is not None:
            payload["mal_id"] = self.mal_id
        if self.title:
            payload["title"] = self.title
        if self.added_at:
            payload["added_at"] = self.added_at
        return payload


@dataclass
class CatalogState:
    shows: list[CatalogEntry] = field(default_factory=list)

    @property
    def enabled(self) -> list[CatalogEntry]:
        return [s for s in self.shows if s.enabled]

    def get(self, show_id: str) -> CatalogEntry | None:
        return next((s for s in self.shows if s.id == show_id), None)


def load_catalog(path: Path | None = None) -> CatalogState:
    file_path = path or SELECTED_FILE
    if not file_path.exists():
        return CatalogState()
    data = json.loads(file_path.read_text(encoding="utf-8-sig"))
    shows = [CatalogEntry.from_dict(item) for item in data.get("shows", [])]
    return CatalogState(shows=shows)


def save_catalog(state: CatalogState, path: Path | None = None) -> None:
    file_path = path or SELECTED_FILE
    payload = {"shows": [entry.to_dict() for entry in state.shows]}
    atomic_write_json(file_path, payload, ensure_ascii=False)


def upsert_entry(state: CatalogState, entry: CatalogEntry) -> CatalogState:
    existing = state.get(entry.id)
    if existing and existing.added_at and not entry.added_at:
        entry.added_at = existing.added_at
    if not entry.added_at:
        entry.added_at = utc_now_iso()
    shows = [s for s in state.shows if s.id != entry.id]
    shows.append(entry)
    shows.sort(key=lambda s: (s.title or s.folder or s.id).lower())
    return CatalogState(shows=shows)


def find_matching_entry(
    state: CatalogState,
    *,
    entry_id: str | None = None,
    mal_id: int | None = None,
    anilist_id: int | None = None,
) -> CatalogEntry | None:
    """Find an existing catalog row by id, MAL id, or AniList id (no duplicates)."""
    if entry_id:
        found = state.get(entry_id)
        if found:
            return found
    if mal_id is not None:
        mid = int(mal_id)
        for entry in state.shows:
            if entry.mal_id is not None and int(entry.mal_id) == mid:
                return entry
            if entry.id == f"mal-{mid}":
                return entry
    if anilist_id is not None:
        aid = int(anilist_id)
        for entry in state.shows:
            if entry.anilist_id is not None and int(entry.anilist_id) == aid:
                return entry
            if entry.id == f"anilist-{aid}":
                return entry
    return None


def remove_entry(state: CatalogState, show_id: str) -> CatalogState:
    """Drop a catalog row by id. Does not touch media files on disk."""
    shows = [s for s in state.shows if s.id != show_id]
    return CatalogState(shows=shows)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def toggle_entry(state: CatalogState, show_id: str, enabled: bool) -> CatalogState:
    shows: list[CatalogEntry] = []
    for entry in state.shows:
        if entry.id == show_id:
            shows.append(
                CatalogEntry(
                    id=entry.id,
                    enabled=enabled,
                    source=entry.source,
                    folder=entry.folder,
                    jellyfin_id=entry.jellyfin_id,
                    anilist_id=entry.anilist_id,
                    mal_id=entry.mal_id,
                    title=entry.title,
                    added_at=entry.added_at,
                )
            )
        else:
            shows.append(entry)
    return CatalogState(shows=shows)
