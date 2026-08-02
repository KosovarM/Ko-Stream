"""OP/ED skip times — Anime-Skip primary, AniSkip fallback; cache under data/aniskip."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from kostream.jsonio import atomic_write_json

ANISKIP_DIR = Path(__file__).resolve().parents[2] / "data" / "aniskip"
ANISKIP_API = "https://api.aniskip.com/v2/skip-times"
ANIME_SKIP_GQL = "https://api.anime-skip.com/graphql"
ANIME_SKIP_CLIENT_ID = "ZGfO0sMF3eCwLYf8yMSCJjlynwNGRXWE"
SKIP_TYPES = ("op", "ed")
REQUEST_TIMEOUT_S = 12

# Anime-Skip timestamp type IDs (stable; also matched by name).
_OP_TYPE_IDS = frozenset(
    {
        "14550023-2589-46f0-bfb4-152976506b4c",  # Intro
        "cbb42238-d285-4c88-9e91-feab4bb8ae0a",  # Mixed Intro
        "679fb610-ff3c-4cf4-83c0-75bcc7fe8778",  # New Intro
    }
)
_ED_TYPE_IDS = frozenset(
    {
        "2a730a51-a601-439b-bc1f-7b94a640ffb9",  # Credits
        "6c4ade53-4fee-447f-89e4-3bb29184e87a",  # Mixed Credits
        "d839cdb1-21b3-455d-9c21-7ffeb37adbec",  # New Credits
    }
)
_OP_NAMES = frozenset({"intro", "mixed intro", "new intro"})
_ED_NAMES = frozenset({"credits", "mixed credits", "new credits"})


def cache_path(mal_id: int, *, root: Path | None = None) -> Path:
    return (root or ANISKIP_DIR) / f"{int(mal_id)}.json"


def load_skip_times(
    mal_id: int,
    episode_number: int,
    *,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Return cached skip payload for one episode, or None."""
    path = cache_path(mal_id, root=root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    episodes = data.get("episodes") if isinstance(data, dict) else None
    if not isinstance(episodes, dict):
        return None
    row = episodes.get(str(int(episode_number)))
    return row if isinstance(row, dict) else None


def _load_cache_doc(mal_id: int, *, root: Path | None = None) -> dict[str, Any]:
    path = cache_path(mal_id, root=root)
    data: dict[str, Any] = {"mal_id": int(mal_id), "episodes": {}}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError):
            pass
    if not isinstance(data.get("episodes"), dict):
        data["episodes"] = {}
    data["mal_id"] = int(mal_id)
    return data


def _store_episode(
    mal_id: int,
    episode_number: int,
    skips: dict[str, Any],
    *,
    root: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    path = cache_path(mal_id, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_cache_doc(mal_id, root=root)
    if extra:
        for key, value in extra.items():
            if value is not None:
                data[key] = value
    episodes = data.setdefault("episodes", {})
    if not isinstance(episodes, dict):
        episodes = {}
        data["episodes"] = episodes
    episodes[str(int(episode_number))] = skips
    atomic_write_json(path, data, ensure_ascii=False)


def _parse_aniskip_results(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize AniSkip results into ``{op: {start,end}, ed: {start,end}}``."""
    out: dict[str, Any] = {}
    results = payload.get("results")
    if not isinstance(results, list):
        return out
    for row in results:
        if not isinstance(row, dict):
            continue
        stype = str(row.get("skipType") or row.get("skip_type") or "").strip().casefold()
        if stype not in SKIP_TYPES:
            continue
        interval = row.get("interval") or {}
        if not isinstance(interval, dict):
            continue
        try:
            start = float(interval.get("startTime", interval.get("start_time")))
            end = float(interval.get("endTime", interval.get("end_time")))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        out[stype] = {"start": start, "end": end}
    return out


def _gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any] | None:
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ANIME_SKIP_GQL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Client-ID": ANIME_SKIP_CLIENT_ID,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ):
        return None
    if not isinstance(raw, dict) or raw.get("errors"):
        return None
    data = raw.get("data")
    return data if isinstance(data, dict) else None


def _is_op_type(type_row: dict[str, Any] | None) -> bool:
    if not isinstance(type_row, dict):
        return False
    tid = str(type_row.get("id") or "")
    name = str(type_row.get("name") or "").strip().casefold()
    return tid in _OP_TYPE_IDS or name in _OP_NAMES


def _is_ed_type(type_row: dict[str, Any] | None) -> bool:
    if not isinstance(type_row, dict):
        return False
    tid = str(type_row.get("id") or "")
    name = str(type_row.get("name") or "").strip().casefold()
    return tid in _ED_TYPE_IDS or name in _ED_NAMES


def _timestamps_to_skips(
    timestamps: list[Any],
    *,
    episode_length: float = 0,
) -> dict[str, Any]:
    """Convert Anime-Skip point timestamps into OP/ED intervals."""
    points: list[tuple[float, str]] = []
    for row in timestamps:
        if not isinstance(row, dict):
            continue
        try:
            at = float(row.get("at"))
        except (TypeError, ValueError):
            continue
        kind = "other"
        t = row.get("type") if isinstance(row.get("type"), dict) else None
        if _is_op_type(t):
            kind = "op"
        elif _is_ed_type(t):
            kind = "ed"
        points.append((at, kind))
    points.sort(key=lambda p: p[0])
    out: dict[str, Any] = {}
    for idx, (at, kind) in enumerate(points):
        if kind not in SKIP_TYPES or at < 0:
            continue
        end = episode_length if episode_length > at else 0.0
        for nxt_at, _nxt_kind in points[idx + 1 :]:
            if nxt_at > at:
                end = nxt_at
                break
        if end <= at:
            # No next marker — OP often ~90s; ED often ~90s toward end.
            end = at + 90.0
            if episode_length > at:
                end = min(end, episode_length)
        out[kind] = {"start": at, "end": end}
    return out


def _episode_number_matches(ep: dict[str, Any], episode_number: int) -> bool:
    want = str(int(episode_number))
    for key in ("absoluteNumber", "number"):
        raw = ep.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        if text == want:
            return True
        try:
            if float(text) == float(want):
                return True
        except ValueError:
            continue
    return False


def _resolve_anime_skip_show_id(title: str) -> str | None:
    data = _gql(
        "query($s:String!){ searchShows(search:$s, limit:8){ id name episodeCount } }",
        {"s": title},
    )
    if not data:
        return None
    shows = data.get("searchShows")
    if not isinstance(shows, list) or not shows:
        return None
    want = title.strip().casefold()
    best = None
    for row in shows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if name.casefold() == want:
            return str(row.get("id") or "") or None
        if best is None and want and want in name.casefold():
            best = row
    pick = best or (shows[0] if isinstance(shows[0], dict) else None)
    if not pick:
        return None
    sid = str(pick.get("id") or "").strip()
    return sid or None


def _fetch_anime_skip(
    mal_id: int,
    episode_number: int,
    *,
    title: str | None = None,
    episode_length: float = 0,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Return skips from Anime-Skip, or None when show/episode cannot be resolved."""
    doc = _load_cache_doc(mal_id, root=root)
    show_id = str(doc.get("anime_skip_show_id") or "").strip() or None
    if not show_id and title:
        show_id = _resolve_anime_skip_show_id(title)
        if show_id:
            doc["anime_skip_show_id"] = show_id
            path = cache_path(mal_id, root=root)
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, doc, ensure_ascii=False)
    if not show_id:
        return None

    data = _gql(
        "query($id:ID!){ findEpisodesByShowId(showId:$id){"
        " id number absoluteNumber baseDuration"
        " timestamps{ at type{ id name } }"
        " } }",
        {"id": show_id},
    )
    if not data:
        return None
    episodes = data.get("findEpisodesByShowId")
    if not isinstance(episodes, list):
        return None
    match = next(
        (ep for ep in episodes if isinstance(ep, dict) and _episode_number_matches(ep, episode_number)),
        None,
    )
    if not match:
        return None
    stamps = match.get("timestamps")
    if not isinstance(stamps, list) or not stamps:
        return None
    try:
        duration = float(match.get("baseDuration") or episode_length or 0)
    except (TypeError, ValueError):
        duration = float(episode_length or 0)
    skips = _timestamps_to_skips(stamps, episode_length=duration)
    if not skips:
        return None
    skips["_source"] = "anime-skip"
    return skips


def _fetch_aniskip_fallback(
    mal_id: int,
    episode_number: int,
    *,
    episode_length: float = 0,
) -> dict[str, Any]:
    params = [("types", t) for t in SKIP_TYPES]
    params.append(("episodeLength", str(episode_length or 0)))
    url = (
        f"{ANISKIP_API}/{int(mal_id)}/{int(episode_number)}"
        f"?{urllib.parse.urlencode(params)}"
    )
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        if isinstance(raw, dict):
            skips = _parse_aniskip_results(raw)
            if skips:
                skips["_source"] = "aniskip"
            return skips
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ):
        pass
    return {}


def fetch_skip_times(
    mal_id: int,
    episode_number: int,
    *,
    episode_length: float = 0,
    root: Path | None = None,
    network: bool = True,
    title: str | None = None,
) -> dict[str, Any]:
    """Fetch OP/ED (Anime-Skip → AniSkip) and write cache. May return empty."""
    if not network or mal_id <= 0 or episode_number <= 0:
        return load_skip_times(mal_id, episode_number, root=root) or {}

    skips: dict[str, Any] = {}
    source = None
    primary = _fetch_anime_skip(
        mal_id,
        episode_number,
        title=title,
        episode_length=episode_length,
        root=root,
    )
    if primary:
        skips = {k: v for k, v in primary.items() if k in SKIP_TYPES}
        source = "anime-skip"
    if not skips.get("op") and not skips.get("ed"):
        fallback = _fetch_aniskip_fallback(
            mal_id, episode_number, episode_length=episode_length
        )
        if fallback:
            for key in SKIP_TYPES:
                if key in fallback and key not in skips:
                    skips[key] = fallback[key]
            source = fallback.get("_source") or "aniskip"

    extra = {"provider": source} if source else None
    _store_episode(mal_id, episode_number, skips, root=root, extra=extra)
    return skips


def ensure_skip_times_for_episodes(
    mal_id: int,
    episode_numbers: list[int],
    *,
    root: Path | None = None,
    network: bool = True,
    force: bool = False,
    title: str | None = None,
) -> int:
    """Fetch missing episode skip caches. Returns number of network fetches."""
    if mal_id <= 0 or not episode_numbers:
        return 0
    fetched = 0
    for num in episode_numbers:
        n = int(num)
        if n <= 0:
            continue
        if not force and load_skip_times(mal_id, n, root=root) is not None:
            continue
        if not network:
            continue
        fetch_skip_times(mal_id, n, root=root, network=True, title=title)
        fetched += 1
    return fetched


# Back-compat alias used by older tests
_parse_results = _parse_aniskip_results
