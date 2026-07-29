from __future__ import annotations

import json
from pathlib import Path

from kostream.jsonio import atomic_write_json
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


def _progress_seconds(entry: float | dict | None) -> float:
    if entry is None:
        return 0.0
    if isinstance(entry, (int, float)):
        return float(entry)
    if isinstance(entry, dict):
        return float(entry.get("seconds") or 0)
    return 0.0


def _progress_duration(entry: float | dict | None) -> float | None:
    if isinstance(entry, dict):
        raw = entry.get("duration")
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None
    return None


def progress_reached_completion(entry: float | dict | None) -> bool:
    """True when stored watch progress is ≥ COMPLETION_RATIO of duration."""
    seconds = _progress_seconds(entry)
    duration = _progress_duration(entry)
    if duration and duration > 0 and seconds > 0:
        return seconds >= COMPLETION_RATIO * duration
    return False


def resume_seconds_for_episode(
    entry: float | dict | None,
    *,
    is_completed: bool = False,
) -> float:
    """Seconds to seek on open; 0 if completed or past the 90% threshold."""
    if is_completed:
        return 0.0
    seconds = _progress_seconds(entry)
    if seconds <= 0:
        return 0.0
    duration = _progress_duration(entry)
    if duration and duration > 0 and seconds >= COMPLETION_RATIO * duration:
        return 0.0
    return seconds


def should_persist_watch_progress(
    seconds: float,
    duration: float | None,
    *,
    is_completed: bool = False,
) -> bool:
    """False when episode is done or playback is at/past completion ratio."""
    if is_completed:
        return False
    if seconds <= 0:
        return False
    if duration and duration > 0 and seconds >= COMPLETION_RATIO * duration:
        return False
    return True


def format_duration(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS for episode list / player chrome."""
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_episode_progress(entry: float | dict | None) -> str | None:
    """Display string like ``2:00/24:20`` or ``8%`` for in-progress episodes."""
    seconds = _progress_seconds(entry)
    if seconds <= 0:
        return None
    duration = _progress_duration(entry)
    if duration and duration > 0:
        return f"{format_duration(seconds)}/{format_duration(duration)}"
    return format_duration(seconds)


def episode_in_progress(
    show: Show,
    episode: Episode,
    local_progress: dict | None = None,
    completed: dict[str, int] | None = None,
) -> bool:
    """True when the episode has saved watch progress and is not completed."""
    if episode_completed(show, episode, local_progress, completed):
        return False
    entry = (local_progress or {}).get(episode.id)
    if not entry:
        return False
    seconds = _progress_seconds(entry)
    if seconds <= 0:
        return False
    return not progress_reached_completion(entry)


def episode_completed(
    show: Show,
    episode: Episode,
    local_progress: dict | None = None,
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
        entry = local_progress[episode.id]
        if progress_reached_completion(entry):
            return True
        # Legacy: old progress was seconds-only with a 10‑minute assumption
        seconds = _progress_seconds(entry)
        if seconds > 0 and episode.filename != "demo.mp4" and _progress_duration(entry) is None:
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
    atomic_write_json(path, data, trailing_newline=False)


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


def unmark_episode_watched(show: Show, episode: Episode, path: Path | None = None) -> int:
    """Undo a single episode complete: set local watched count to position − 1.

    Returns the new watched count. If the show was list-completed, status becomes
    ``watching`` when any episode remains unfinished.
    """
    pos = _episode_position(show, episode)
    if not pos:
        return _effective_watched_count(show, load_completed(path or COMPLETED_FILE))
    file_path = path or COMPLETED_FILE
    data = load_completed(file_path)
    new_count = max(0, pos - 1)
    if new_count > 0:
        data[show.id] = new_count
    else:
        data.pop(show.id, None)
    save_completed(file_path, data)
    show.episodes_watched = new_count
    total = max(len(sorted_episodes(show)), show.episode_count or 0, 0)
    if show.list_status == "completed" and (not total or new_count < total):
        show.list_status = "watching"
    return new_count


def mark_show_completed(show: Show, path: Path | None = None) -> int:
    """Mark the whole show complete locally; returns watched-episode count."""
    total = max(len(sorted_episodes(show)), show.episode_count or 0, 0)
    if not total:
        total = max(_effective_watched_count(show), 1)
    file_path = path or COMPLETED_FILE
    data = load_completed(file_path)
    data[show.id] = max(data.get(show.id, 0), total)
    save_completed(file_path, data)
    show.episodes_watched = max(show.episodes_watched, total)
    show.list_status = "completed"
    return data[show.id]


def is_currently_airing(show: Show) -> bool:
    from kostream.browse import KIND_ANIMES, classify_show_kind

    if classify_show_kind(show) != KIND_ANIMES:
        return False
    if show.anime_status != "currently_airing":
        return False
    if show.list_status == "completed":
        return False
    return True


def filter_currently_airing(shows: list[Show]) -> list[Show]:
    airing = [s for s in shows if is_currently_airing(s)]
    return sorted(airing, key=lambda s: s.title.casefold())


def recently_added(shows: list[Show], limit: int = 12) -> list[Show]:
    """Shows that most recently gained local episode files (by filesystem mtime)."""
    with_local = [
        s for s in shows if s.has_local_files and s.latest_local_mtime is not None
    ]
    with_local.sort(key=lambda s: s.latest_local_mtime or 0.0, reverse=True)
    return with_local[:limit]


def apply_mal_metadata(show: Show, cached, list_row: dict | None = None) -> None:
    """Copy MAL list progress, ratings, and relations onto a Show.

    Progress is merged upward: local ``episodes_watched`` is never lowered.
    When ``list_row`` is provided (per-user overlay), it supplies watched/score/list_status.
    """
    from kostream.browse import format_type_label

    watched = int(getattr(cached, "num_episodes_watched", 0) or 0)
    score = int(getattr(cached, "score", 0) or 0)
    list_status = getattr(cached, "list_status", None)
    if list_row:
        if "num_episodes_watched" in list_row:
            watched = int(list_row.get("num_episodes_watched") or 0)
        if "score" in list_row:
            score = int(list_row.get("score") or 0)
        if list_row.get("list_status"):
            list_status = str(list_row["list_status"])

    show.episodes_watched = max(show.episodes_watched, watched)
    show.anime_status = cached.anime_status
    # Keep completed if we are already at/above MAL progress
    if show.list_status != "completed":
        show.list_status = list_status
    show.user_score = score if score else None
    show.mean_score = cached.mean_score
    show.related_anime = list(cached.related_anime or [])
    show.broadcast_day = getattr(cached, "broadcast_day", None)
    show.broadcast_time = getattr(cached, "broadcast_time", None)
    media_type = getattr(cached, "media_type", None)
    if media_type:
        show.media_type = str(media_type)
        show.type_label = format_type_label(media_type)
    show.release_year = getattr(cached, "release_year", None)
    studios = getattr(cached, "studios", None) or []
    show.studios = [str(s).strip() for s in studios if str(s or "").strip()]


def reconcile_anime_progress(
    show: Show,
    *,
    completed_path: Path | None = None,
    mal_cfg=None,
    user_id: str | None = None,
) -> int:
    """Take max(local completed, MAL cache) and push upward both ways.

    - If MAL is ahead → raise local completed count.
    - If local is ahead and MAL is connected → PATCH MAL upward only.
    Returns the merged watched count.
    """
    from kostream.mal import (
        MalConfig,
        MalError,
        get_anime_list_row,
        load_cached_anime,
        update_episodes_watched,
    )

    file_path = completed_path or COMPLETED_FILE
    local = _effective_watched_count(show, load_completed(file_path))
    remote = 0
    got_overlay = False
    if show.mal_id and user_id:
        row = get_anime_list_row(user_id, show.mal_id)
        if row is not None:
            remote = int(row.get("num_episodes_watched") or 0)
            got_overlay = True
    if not got_overlay and show.mal_id:
        cached = load_cached_anime(show.mal_id)
        if cached:
            remote = int(cached.num_episodes_watched or 0)
    merged = max(local, remote, show.episodes_watched or 0)
    if merged <= 0:
        return 0

    data = load_completed(file_path)
    prev_local = data.get(show.id, 0)
    if merged > prev_local:
        data[show.id] = merged
        save_completed(file_path, data)
    show.episodes_watched = max(show.episodes_watched, merged)

    cfg = mal_cfg
    if cfg is None:
        try:
            cfg = MalConfig.from_env()
        except Exception:  # noqa: BLE001
            cfg = None
    if cfg and show.mal_id and user_id and merged > remote:
        try:
            total = show.episode_count or 0
            status = "completed" if total and merged >= total else None
            update_episodes_watched(
                cfg, show.mal_id, merged, status=status, user_id=user_id
            )
        except MalError:
            pass
    return merged


def sort_by_mean_score(shows: list[Show], limit: int = 12) -> list[Show]:
    return sorted(
        shows,
        key=lambda s: (s.mean_score is not None, s.mean_score or 0.0),
        reverse=True,
    )[:limit]
