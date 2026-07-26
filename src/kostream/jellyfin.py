"""Optional Jellyfin backend — streams from YOUR Jellyfin server (own library)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
import json

from kostream.models import Episode, Show, slugify


@dataclass
class JellyfinConfig:
    base_url: str
    api_key: str

    @classmethod
    def from_env(cls) -> JellyfinConfig | None:
        url = os.environ.get("JELLYFIN_URL", "").rstrip("/")
        key = os.environ.get("JELLYFIN_API_KEY", "")
        if not url or not key:
            return None
        return cls(base_url=url, api_key=key)


def fetch_shows(cfg: JellyfinConfig, limit: int = 50) -> list[Show]:
    """Pull series from Jellyfin library (metadata only — no local copy)."""
    try:
        items = _get_json(
            cfg,
            f"/Users/{_user_id(cfg)}/Items?"
            "IncludeItemTypes=Series&Recursive=true&Limit={limit}".format(limit=limit),
        )
    except (URLError, OSError, ValueError, KeyError):
        return []

    shows: list[Show] = []
    for item in items.get("Items", []):
        show_id = f"jf-{item['Id']}"
        episodes = _fetch_episodes(cfg, item["Id"])
        shows.append(
            Show(
                id=show_id,
                title=item.get("Name", "Unknown"),
                description=(item.get("Overview") or "From Jellyfin library")[:500],
                type_label="TV",
                genres=[g for g in (item.get("Genres") or [])[:3]],
                episodes=episodes,
            )
        )
    return shows


def stream_url(cfg: JellyfinConfig, item_id: str) -> str:
    """Direct stream URL — browser plays from Jellyfin (on-demand, no Ko-Stream copy)."""
    return (
        f"{cfg.base_url}/Videos/{item_id}/stream"
        f"?Static=true&api_key={cfg.api_key}"
    )


def _fetch_episodes(cfg: JellyfinConfig, series_id: str) -> list[Episode]:
    try:
        data = _get_json(
            cfg,
            f"/Shows/{series_id}/Episodes?UserId={_user_id(cfg)}&Fields=Path",
        )
    except (URLError, OSError, ValueError, KeyError):
        return []

    episodes: list[Episode] = []
    for ep in data.get("Items", []):
        ep_id = ep["Id"]
        show_id = f"jf-{series_id}"
        season = ep.get("ParentIndexNumber") or 1
        number = ep.get("IndexNumber") or 1
        episodes.append(
            Episode(
                id=f"jf-ep-{ep_id}",
                show_id=show_id,
                season=season,
                number=number,
                title=ep.get("Name", f"Episode {number}"),
                filename=f"jellyfin:{ep_id}",
            )
        )
    return sorted(episodes, key=lambda e: (e.season, e.number))


def _user_id(cfg: JellyfinConfig) -> str:
    data = _get_json(cfg, "/Users/Me")
    return data["Id"]


def _get_json(cfg: JellyfinConfig, path: str) -> dict[str, Any]:
    req = Request(
        f"{cfg.base_url}{path}",
        headers={
            "X-Emby-Token": cfg.api_key,
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))
