"""MAL manga catalog — selected manga from mangalist sync."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kostream.models import slugify

MANGA_CATALOG_DIR = Path(__file__).resolve().parents[2] / "data" / "manga"
MANGA_SELECTED_FILE = MANGA_CATALOG_DIR / "selected.json"


@dataclass
class MangaCatalogEntry:
    id: str
    enabled: bool = True
    source: str = "local"  # local | mal
    folder: str | None = None
    mal_id: int | None = None
    title: str | None = None
    media_type: str | None = None  # manga | manhwa | manhua | …
    mangadex_id: str | None = None  # optional UUID override for chapter-title sync
    added_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> MangaCatalogEntry:
        entry_id = data.get("id") or slugify(data.get("folder") or data.get("title", "manga"))
        mal_id = data.get("mal_id")
        mdx = data.get("mangadex_id")
        return cls(
            id=entry_id,
            enabled=bool(data.get("enabled", True)),
            source=data.get("source", "local"),
            folder=data.get("folder"),
            mal_id=int(mal_id) if mal_id is not None else None,
            title=data.get("title"),
            media_type=data.get("media_type"),
            mangadex_id=str(mdx).strip() if mdx else None,
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
        if self.mal_id is not None:
            payload["mal_id"] = self.mal_id
        if self.title:
            payload["title"] = self.title
        if self.media_type:
            payload["media_type"] = self.media_type
        if self.mangadex_id:
            payload["mangadex_id"] = self.mangadex_id
        if self.added_at:
            payload["added_at"] = self.added_at
        return payload


@dataclass
class MangaCatalogState:
    titles: list[MangaCatalogEntry] = field(default_factory=list)

    @property
    def enabled(self) -> list[MangaCatalogEntry]:
        return [t for t in self.titles if t.enabled]

    def get(self, title_id: str) -> MangaCatalogEntry | None:
        return next((t for t in self.titles if t.id == title_id), None)


def load_manga_catalog(path: Path | None = None) -> MangaCatalogState:
    file_path = path or MANGA_SELECTED_FILE
    if not file_path.exists():
        return MangaCatalogState()
    data = json.loads(file_path.read_text(encoding="utf-8-sig"))
    titles = [MangaCatalogEntry.from_dict(item) for item in data.get("titles", [])]
    return MangaCatalogState(titles=titles)


def save_manga_catalog(state: MangaCatalogState, path: Path | None = None) -> None:
    file_path = path or MANGA_SELECTED_FILE
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"titles": [entry.to_dict() for entry in state.titles]}
    file_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def upsert_manga_entry(state: MangaCatalogState, entry: MangaCatalogEntry) -> MangaCatalogState:
    existing = state.get(entry.id)
    if existing and existing.added_at and not entry.added_at:
        entry.added_at = existing.added_at
    if not entry.added_at:
        entry.added_at = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
    titles = [t for t in state.titles if t.id != entry.id]
    titles.append(entry)
    titles.sort(key=lambda t: (t.title or t.folder or t.id).lower())
    return MangaCatalogState(titles=titles)


def match_local_folder(media_root: Path, title: str) -> str | None:
    """Best-effort match a media/manga folder name to a MAL title."""
    if not media_root.is_dir() or not title:
        return None
    want = _manga_match_key(title)
    if not want:
        return None

    exact: str | None = None
    soft: list[tuple[int, str]] = []
    for folder in media_root.iterdir():
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        key = _manga_match_key(folder.name)
        if not key:
            continue
        if key == want:
            exact = folder.name
            break
        # Soft: shared significant run (ignore punctuation / : /)
        if want in key or key in want:
            soft.append((abs(len(want) - len(key)), folder.name))
            continue
        # Token overlap (Fate Extra CCC Fox Tail ↔ Fate/Extra CCC: Fox Tail)
        want_tokens = set(_manga_tokens(title))
        folder_tokens = set(_manga_tokens(folder.name))
        if not want_tokens or not folder_tokens:
            continue
        overlap = want_tokens & folder_tokens
        if len(overlap) >= 3 and len(overlap) >= min(len(want_tokens), len(folder_tokens)) * 0.6:
            soft.append((len(want_tokens) - len(overlap), folder.name))

    if exact:
        return exact
    if soft:
        soft.sort(key=lambda item: item[0])
        return soft[0][1]
    return None


def _manga_match_key(value: str) -> str:
    """Normalize titles/folders for matching (strip punctuation, spaces)."""
    import re

    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _manga_tokens(value: str) -> list[str]:
    import re

    return [t for t in re.split(r"[^a-z0-9]+", value.casefold()) if len(t) > 1]
