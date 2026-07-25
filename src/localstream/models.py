from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Episode:
    id: str
    show_id: str
    season: int
    number: int
    title: str
    filename: str
    duration_label: str = "TV"


@dataclass
class Show:
    id: str
    title: str
    description: str
    poster: str | None = None
    type_label: str = "TV"
    episodes: list[Episode] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)

    @property
    def episode_count(self) -> int:
        return len(self.episodes)

    @property
    def latest_episode(self) -> Episode | None:
        if not self.episodes:
            return None
        return max(self.episodes, key=lambda e: (e.season, e.number))


def slugify(name: str) -> str:
    return (
        name.lower()
        .replace(" ", "-")
        .replace("_", "-")
        .replace("'", "")
        .replace(".", "")
    )


VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv"}
