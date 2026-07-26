from __future__ import annotations

import json
from pathlib import Path

from kostream.models import Episode, Show

COMPLETION_RATIO = 0.9
COMPLETED_FILE = Path(__file__).resolve().parents[2] / "data" / "completed.json"


def sorted_episodes(show: Show) -> list[Episode]:
    return sorted(show.episodes, key=lambda e: (e.season, e.number))


def _episode_position(show: Show, episode: Episode) -> int:
    for idx, ep in enumerate(sorted_episodes(show), start=1):
        if ep.id == episode.id:
            return idx
    return 0


def _effective_watched_count(show: Show, completed: dict[str, int] | None = None) -> int:
    local = (completed or {}).get(show.id, 0)
    return max(show.episodes_watched, local)


def episode_completed(
    show: Show,
    episode: Episode,
    local_progress: dict[str, float] | None = None,
    completed: dict[str, int] | None = None,
) -> bool:
    if show.list_status == "completed":
        return True
    watched = _effective_watched_count(show, completed)
    if watched > 0:
        pos = _episode_position(show, episode)
        if pos and pos <= watched:
            return True
    if local_progress and episode.id in local_progress:
        seconds = local_progress[episode.id]
        if seconds > 0 and episode.filename != "demo.mp4":
            return seconds >= COMPLETION_RATIO * 600
    return False


def next_unwatched_episode(
    show: Show,
    local_progress: dict[str, float] | None = None,
    completed: dict[str, int] | None = None,
) -> Episode | None:
    for ep in sorted_episodes(show):
        if not episode_completed(show, ep, local_progress, completed):
            return ep
    return None


def load_completed(path: Path | None = None) -> dict[str, int]:
    file_path = path or COMPLETED_FILE
    if not file_path.exists():
        return {}
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in raw.items()}


def save_completed(path: Path, data: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def mark_episode_watched(show: Show, episode: Episode, path: Path | None = None) -> int:
    """Record episode as watched locally; returns new watched count for the show."""
    pos = _episode_position(show, episode)
    if not pos:
        return _effective_watched_count(show)
    file_path = path or COMPLETED_FILE
    data = load_completed(file_path)
    data[show.id] = max(data.get(show.id, 0), pos)
    save_completed(file_path, data)
    show.episodes_watched = max(show.episodes_watched, pos)
    return show.episodes_watched


def is_currently_airing(show: Show) -> bool:
    if show.anime_status != "currently_airing":
        return False
    if show.list_status == "completed":
        return False
    return True


def filter_currently_airing(shows: list[Show]) -> list[Show]:
    airing = [s for s in shows if is_currently_airing(s)]
    return sorted(airing, key=lambda s: s.title.casefold())


def recently_added(shows: list[Show], limit: int = 12) -> list[Show]:
    dated = [s for s in shows if s.added_at]
    undated = [s for s in shows if not s.added_at]
    dated.sort(key=lambda s: s.added_at or "", reverse=True)
    return (dated + undated)[:limit]


def apply_mal_metadata(show: Show, cached) -> None:
    """Copy MAL list progress, ratings, and relations onto a Show."""
    show.episodes_watched = cached.num_episodes_watched
    show.anime_status = cached.anime_status
    show.list_status = cached.list_status
    show.user_score = cached.score if cached.score else None
    show.mean_score = cached.mean_score
    show.related_anime = list(cached.related_anime or [])


def apply_mal_progress(show: Show, cached) -> None:
    """Copy MAL list progress onto a Show instance."""
    apply_mal_metadata(show, cached)


def sort_by_mean_score(shows: list[Show], limit: int = 12) -> list[Show]:
    return sorted(
        shows,
        key=lambda s: (s.mean_score is not None, s.mean_score or 0.0),
        reverse=True,
    )[:limit]
