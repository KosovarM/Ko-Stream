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


@dataclass(frozen=True)
class RelatedAnime:
    mal_id: int
    title: str
    relation_type: str


@dataclass
class Show:
    id: str
    title: str
    description: str
    poster: str | None = None
    poster_url: str | None = None
    banner_url: str | None = None
    type_label: str = "TV"
    media_type: str | None = None  # MAL: tv | movie | ova | ona | special | …
    episodes: list[Episode] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    studios: list[str] = field(default_factory=list)
    anilist_id: int | None = None
    mal_id: int | None = None
    episodes_watched: int = 0
    anime_status: str | None = None
    list_status: str | None = None
    added_at: str | None = None
    latest_local_mtime: float | None = None  # max mtime of local video files
    user_score: int | None = None
    mean_score: float | None = None
    related_anime: list[RelatedAnime] = field(default_factory=list)
    broadcast_day: str | None = None  # monday..sunday (MAL / JST)
    broadcast_time: str | None = None  # HH:MM JST
    release_year: int | None = None  # MAL start_date.year

    @property
    def episode_count(self) -> int:
        return len(self.episodes)

    @property
    def is_metadata_only(self) -> bool:
        """True when there are no local/playable files — MAL/AniList placeholders only."""
        if not self.episodes:
            return True
        return all(ep.filename == "demo.mp4" for ep in self.episodes)

    @property
    def has_local_files(self) -> bool:
        """True when at least one episode is a real file under media/shows."""
        return any(is_local_file_episode(ep) for ep in self.episodes)

    @property
    def is_stream_only(self) -> bool:
        """True when there are no local video files (demo/strm/jellyfin/metadata only)."""
        return not self.has_local_files

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
STRM_EXTENSION = ".strm"


def is_jellyfin_episode(episode: Episode) -> bool:
    return episode.filename.startswith("jellyfin:")


def is_strm_episode(episode: Episode) -> bool:
    return episode.filename.startswith("strm:")


def is_local_file_episode(episode: Episode) -> bool:
    """True when the episode points at a real file under media/shows (not demo/strm/jellyfin)."""
    if episode.filename == "demo.mp4":
        return False
    if is_strm_episode(episode) or is_jellyfin_episode(episode):
        return False
    return bool(episode.filename)


def is_stream_only_episode(episode: Episode) -> bool:
    """Placeholder episode playable only via Grab / remote stream, no local file."""
    return episode.filename == "demo.mp4"


def jellyfin_item_id(episode: Episode) -> str:
    return episode.filename.split(":", 1)[1]


def strm_target_url(episode: Episode) -> str:
    return episode.filename.split(":", 1)[1]
