"""Family recommendations — one pick per category per user."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kostream.jsonio import atomic_write_json
from kostream.manga_progress import load_manga_completed
from kostream.user_paths import user_data_paths
from kostream.watch_progress import load_completed

RECOMMENDATIONS_FILE = Path(__file__).resolve().parents[2] / "data" / "recommendations.json"

KIND_SERIES = "series"
KIND_MOVIE = "movie"
KIND_MANGA = "manga"
KIND_MANHWA = "manhwa"

VALID_KINDS = frozenset({KIND_SERIES, KIND_MOVIE, KIND_MANGA, KIND_MANHWA})

KIND_LABELS = {
    KIND_SERIES: "Series",
    KIND_MOVIE: "Movie",
    KIND_MANGA: "Manga",
    KIND_MANHWA: "Manhwa",
}

SHOW_KINDS = frozenset({KIND_SERIES, KIND_MOVIE})
MANGA_KINDS = frozenset({KIND_MANGA, KIND_MANHWA})

RECOMMEND_BLOCKED_ALL_COMPLETED = "Everyone has already completed this."


class RecommendationConflict(Exception):
    """Slot already filled; caller must confirm swap."""

    def __init__(self, current: dict[str, Any]):
        self.current = current
        super().__init__("Recommendation slot already filled")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_kind(value: str | None) -> str:
    """Map request/browse kinds onto recommendation categories."""
    v = (value or "").strip().casefold()
    if v in ("animes", "anime", "tv", "series", "special", "specials"):
        return KIND_SERIES
    if v in ("movies", "movie", "film"):
        return KIND_MOVIE
    if v in ("manga",):
        return KIND_MANGA
    if v in ("manhwa",):
        return KIND_MANHWA
    if v in VALID_KINDS:
        return v
    raise ValueError(f"Invalid recommendation kind: {value!r}")


def empty_slots() -> dict[str, Any]:
    return {kind: None for kind in (KIND_SERIES, KIND_MOVIE, KIND_MANGA, KIND_MANHWA)}


def _normalize_user_slots(raw: Any) -> dict[str, Any]:
    slots = empty_slots()
    if not isinstance(raw, dict):
        return slots
    for kind in VALID_KINDS:
        pick = raw.get(kind)
        if pick is None:
            slots[kind] = None
        elif isinstance(pick, dict):
            slots[kind] = dict(pick)
        else:
            slots[kind] = None
    return slots


def load_recommendations(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return ``{user_id: {kind: pick|null}}``."""
    file_path = path or RECOMMENDATIONS_FILE
    if not file_path.is_file():
        return {}
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for user_id, slots in raw.items():
        uid = str(user_id or "").strip()
        if not uid:
            continue
        out[uid] = _normalize_user_slots(slots)
    return out


def save_recommendations(
    data: dict[str, dict[str, Any]],
    path: Path | None = None,
) -> None:
    file_path = path or RECOMMENDATIONS_FILE
    cleaned: dict[str, dict[str, Any]] = {}
    for user_id, slots in data.items():
        uid = str(user_id or "").strip()
        if not uid:
            continue
        cleaned[uid] = _normalize_user_slots(slots)
    atomic_write_json(file_path, cleaned, ensure_ascii=False)


def get_user_slots(user_id: str, path: Path | None = None) -> dict[str, Any]:
    uid = (user_id or "").strip()
    if not uid:
        return empty_slots()
    return load_recommendations(path).get(uid, empty_slots())


def _build_pick(
    kind: str,
    *,
    title: str,
    show_id: str | None = None,
    manga_id: str | None = None,
    mal_id: int | None = None,
    poster_url: str | None = None,
) -> dict[str, Any]:
    pick: dict[str, Any] = {
        "title": title,
        "set_at": _utc_now(),
    }
    if mal_id is not None:
        pick["mal_id"] = int(mal_id)
    if poster_url:
        pick["poster_url"] = poster_url
    if kind in SHOW_KINDS:
        sid = (show_id or "").strip()
        if not sid:
            raise ValueError("show_id required for series/movie recommendations")
        pick["show_id"] = sid
    else:
        mid = (manga_id or "").strip()
        if not mid:
            raise ValueError("manga_id required for manga/manhwa recommendations")
        pick["manga_id"] = mid
    return pick


def set_recommendation(
    user_id: str,
    kind: str,
    *,
    title: str,
    show_id: str | None = None,
    manga_id: str | None = None,
    mal_id: int | None = None,
    poster_url: str | None = None,
    replace: bool = False,
    path: Path | None = None,
) -> tuple[dict[str, Any], bool]:
    """Set the current user's pick for ``kind``.

    Returns ``(pick, swapped)``.
    Raises ``RecommendationConflict`` when the slot is filled and ``replace`` is false.
    """
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id required")
    kind_n = normalize_kind(kind)
    title_n = (title or "").strip()
    if not title_n:
        raise ValueError("title required")

    pick = _build_pick(
        kind_n,
        title=title_n,
        show_id=show_id,
        manga_id=manga_id,
        mal_id=mal_id,
        poster_url=(poster_url or "").strip() or None,
    )

    data = load_recommendations(path)
    slots = _normalize_user_slots(data.get(uid))
    current = slots.get(kind_n)
    swapped = False
    if isinstance(current, dict) and current.get("title"):
        same_show = (
            kind_n in SHOW_KINDS
            and current.get("show_id") == pick.get("show_id")
        )
        same_manga = (
            kind_n in MANGA_KINDS
            and current.get("manga_id") == pick.get("manga_id")
        )
        if same_show or same_manga:
            # Refresh metadata without requiring confirm.
            slots[kind_n] = {**current, **pick, "set_at": current.get("set_at") or pick["set_at"]}
            data[uid] = slots
            save_recommendations(data, path)
            return slots[kind_n], False
        if not replace:
            raise RecommendationConflict(dict(current))
        swapped = True

    slots[kind_n] = pick
    data[uid] = slots
    save_recommendations(data, path)
    return pick, swapped


def clear_recommendation(
    user_id: str,
    kind: str,
    path: Path | None = None,
) -> bool:
    """Clear one slot for the user. Returns True when a pick was removed."""
    uid = (user_id or "").strip()
    if not uid:
        return False
    kind_n = normalize_kind(kind)
    data = load_recommendations(path)
    slots = data.get(uid)
    if not slots:
        return False
    slots = _normalize_user_slots(slots)
    if slots.get(kind_n) is None:
        return False
    slots[kind_n] = None
    if all(v is None for v in slots.values()):
        data.pop(uid, None)
    else:
        data[uid] = slots
    save_recommendations(data, path)
    return True


def user_recommended_this(
    user_id: str,
    kind: str,
    *,
    show_id: str | None = None,
    manga_id: str | None = None,
    path: Path | None = None,
) -> bool:
    """True when the user's current pick for ``kind`` is this title."""
    uid = (user_id or "").strip()
    if not uid:
        return False
    try:
        kind_n = normalize_kind(kind)
    except ValueError:
        return False
    pick = get_user_slots(uid, path).get(kind_n)
    if not isinstance(pick, dict):
        return False
    if kind_n in SHOW_KINDS:
        sid = (show_id or "").strip()
        return bool(sid) and str(pick.get("show_id") or "") == sid
    mid = (manga_id or "").strip()
    return bool(mid) and str(pick.get("manga_id") or "") == mid


def _eligible_users(users: list[Any] | None) -> list[Any]:
    """Non-restricted accounts (restricted users are excluded from “everyone”)."""
    if not users:
        return []
    out: list[Any] = []
    for user in users:
        restricted = bool(
            getattr(user, "restricted", None)
            if not isinstance(user, dict)
            else user.get("restricted", False)
        )
        if restricted:
            continue
        uid = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
        if uid:
            out.append(user)
    return out


def _user_id_of(user: Any) -> str:
    uid = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
    return str(uid or "").strip()


def _mal_list_status_completed(user_id: str, mal_id: int | None, *, manga: bool) -> bool:
    if mal_id is None:
        return False
    try:
        from kostream.mal import get_anime_list_row, get_manga_list_row

        row = get_manga_list_row(user_id, int(mal_id)) if manga else get_anime_list_row(
            user_id, int(mal_id)
        )
    except (OSError, TypeError, ValueError):
        return False
    if not isinstance(row, dict):
        return False
    return str(row.get("list_status") or "").strip().casefold() == "completed"


def user_completed_show(
    show_id: str,
    user_id: str,
    user_data_dir: Path,
    *,
    episode_total: int = 0,
    mal_id: int | None = None,
) -> bool:
    """True when this user has completed the show (local map and/or MAL)."""
    sid = (show_id or "").strip()
    uid = (user_id or "").strip()
    if not sid or not uid:
        return False
    completed_path = user_data_paths(uid, user_data_dir)["completed"]
    if completed_path.is_file():
        watched = int(load_completed(completed_path).get(sid, 0) or 0)
        total = max(int(episode_total or 0), 0)
        if total > 0 and watched >= total:
            return True
    return _mal_list_status_completed(uid, mal_id, manga=False)


def user_completed_manga(
    manga_id: str,
    user_id: str,
    user_data_dir: Path,
    *,
    chapter_total: int = 0,
    mal_id: int | None = None,
) -> bool:
    """True when this user has completed the manga (local map and/or MAL)."""
    mid = (manga_id or "").strip()
    uid = (user_id or "").strip()
    if not mid or not uid:
        return False
    completed_path = user_data_paths(uid, user_data_dir)["manga_completed"]
    if completed_path.is_file():
        read = int(load_manga_completed(completed_path).get(mid, 0) or 0)
        total = max(int(chapter_total or 0), 0)
        if total > 0 and read >= total:
            return True
    return _mal_list_status_completed(uid, mal_id, manga=True)


def all_users_completed_show(
    show_id: str,
    users: list[Any] | None,
    user_data_dir: Path,
    *,
    episode_total: int = 0,
    mal_id: int | None = None,
) -> bool:
    """True when every non-restricted user has completed this show.

    No eligible users → False (do not block). Missing progress files → not completed.
    """
    eligible = _eligible_users(users)
    if not eligible:
        return False
    return all(
        user_completed_show(
            show_id,
            _user_id_of(user),
            user_data_dir,
            episode_total=episode_total,
            mal_id=mal_id,
        )
        for user in eligible
    )


def all_users_completed_manga(
    manga_id: str,
    users: list[Any] | None,
    user_data_dir: Path,
    *,
    chapter_total: int = 0,
    mal_id: int | None = None,
) -> bool:
    """True when every non-restricted user has completed this manga."""
    eligible = _eligible_users(users)
    if not eligible:
        return False
    return all(
        user_completed_manga(
            manga_id,
            _user_id_of(user),
            user_data_dir,
            chapter_total=chapter_total,
            mal_id=mal_id,
        )
        for user in eligible
    )


def list_family_recommendations(
    path: Path | None = None,
    *,
    users: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Homepage rows grouped by recommender.

    Each group: ``{user_id, username, display_name, picks: [...]}``.
    """
    data = load_recommendations(path)
    users_by_id: dict[str, Any] = {}
    if users:
        for user in users:
            uid = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
            if uid:
                users_by_id[str(uid)] = user

    groups: list[dict[str, Any]] = []
    for user_id, slots in data.items():
        picks: list[dict[str, Any]] = []
        for kind in (KIND_SERIES, KIND_MOVIE, KIND_MANGA, KIND_MANHWA):
            pick = slots.get(kind) if isinstance(slots, dict) else None
            if not isinstance(pick, dict):
                continue
            title = str(pick.get("title") or "").strip()
            if not title:
                continue
            item = {
                "kind": kind,
                "kind_label": KIND_LABELS.get(kind, kind.title()),
                "title": title,
                "mal_id": pick.get("mal_id"),
                "show_id": pick.get("show_id"),
                "manga_id": pick.get("manga_id"),
                "poster_url": pick.get("poster_url"),
                "set_at": pick.get("set_at"),
            }
            picks.append(item)
        if not picks:
            continue

        user = users_by_id.get(user_id)
        if user is not None:
            username = str(getattr(user, "username", None) or (user.get("username") if isinstance(user, dict) else "") or user_id)
            display_name = str(
                getattr(user, "display_name", None)
                or (user.get("display_name") if isinstance(user, dict) else None)
                or username
            )
        else:
            username = user_id
            display_name = user_id

        groups.append(
            {
                "user_id": user_id,
                "username": username,
                "display_name": display_name,
                "picks": picks,
            }
        )

    groups.sort(key=lambda g: (str(g.get("display_name") or "").casefold(), str(g.get("user_id") or "")))
    return groups
