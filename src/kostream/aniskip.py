"""AniSkip OP/ED skip times — fetch on sync/add, read from cache on playback."""

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
SKIP_TYPES = ("op", "ed")
REQUEST_TIMEOUT_S = 12


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


def _store_episode(
    mal_id: int,
    episode_number: int,
    skips: dict[str, Any],
    *,
    root: Path | None = None,
) -> None:
    path = cache_path(mal_id, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"mal_id": int(mal_id), "episodes": {}}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError):
            pass
    episodes = data.setdefault("episodes", {})
    if not isinstance(episodes, dict):
        episodes = {}
        data["episodes"] = episodes
    episodes[str(int(episode_number))] = skips
    data["mal_id"] = int(mal_id)
    atomic_write_json(path, data, ensure_ascii=False)


def _parse_results(payload: dict[str, Any]) -> dict[str, Any]:
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


def fetch_skip_times(
    mal_id: int,
    episode_number: int,
    *,
    episode_length: float = 0,
    root: Path | None = None,
    network: bool = True,
) -> dict[str, Any]:
    """Fetch OP/ED for one episode and write cache. Returns skip map (may be empty)."""
    if not network or mal_id <= 0 or episode_number <= 0:
        return load_skip_times(mal_id, episode_number, root=root) or {}

    params = [("types", t) for t in SKIP_TYPES]
    params.append(("episodeLength", str(episode_length or 0)))
    url = (
        f"{ANISKIP_API}/{int(mal_id)}/{int(episode_number)}"
        f"?{urllib.parse.urlencode(params)}"
    )
    skips: dict[str, Any] = {}
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        if isinstance(raw, dict):
            skips = _parse_results(raw)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        # Cache empty miss so we do not hammer the API every sync for unknown eps.
        skips = {}
    _store_episode(mal_id, episode_number, skips, root=root)
    return skips


def ensure_skip_times_for_episodes(
    mal_id: int,
    episode_numbers: list[int],
    *,
    root: Path | None = None,
    network: bool = True,
    force: bool = False,
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
        fetch_skip_times(mal_id, n, root=root, network=True)
        fetched += 1
    return fetched
