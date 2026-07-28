"""AniList GraphQL — legal metadata & cover art for anime."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://graphql.anilist.co"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "anilist"
MAL_INDEX_DIR = CACHE_DIR / "mal"
CACHE_TTL_SECONDS = 7 * 24 * 3600
USER_AGENT = "Ko-Stream/0.2 (+https://github.com/KosovarM/Ko-Stream; local metadata)"

_MEDIA_FIELDS = """
        id
        title { romaji english native }
        description(asHtml: false)
        genres
        idMal
        episodes
        coverImage { large extraLarge }
        bannerImage
"""


class AniListError(Exception):
    """AniList API request failed."""


@dataclass
class AniListMedia:
    anilist_id: int
    title: str
    description: str
    genres: list[str]
    poster_url: str | None
    banner_url: str | None
    mal_id: int | None = None
    episodes: int | None = None
    title_english: str | None = None
    title_romaji: str | None = None
    title_native: str | None = None


def search_anime(query: str, limit: int = 8) -> list[AniListMedia]:
    if not query.strip():
        return []
    gql = """
    query ($search: String, $limit: Int) {
      Page(page: 1, perPage: $limit) {
        media(search: $search, type: ANIME, sort: POPULARITY_DESC) {
          id
          title { romaji english native }
          description(asHtml: false)
          genres
          idMal
          episodes
          coverImage { large extraLarge }
          bannerImage
        }
      }
    }
    """
    try:
        data = _post_graphql(gql, {"search": query.strip(), "limit": limit})
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise AniListError(str(exc)) from exc
    items = data.get("data", {}).get("Page", {}).get("media", []) or []
    return [_parse_media(item) for item in items]


def fetch_anime(anilist_id: int, *, network: bool = True) -> AniListMedia | None:
    cached = _read_cache(anilist_id)
    if cached:
        return cached
    if not network:
        return None
    gql = f"""
    query ($id: Int) {{
      Media(id: $id, type: ANIME) {{
{_MEDIA_FIELDS}
      }}
    }}
    """
    try:
        data = _post_graphql(gql, {"id": anilist_id})
    except (URLError, OSError, ValueError, KeyError):
        return None
    media = data.get("data", {}).get("Media")
    if not media:
        return None
    parsed = _parse_media(media)
    _write_cache(parsed)
    return parsed


def fetch_anime_by_mal_id(mal_id: int, *, network: bool = True) -> AniListMedia | None:
    """Resolve AniList media (incl. wide bannerImage) from a MAL id."""
    try:
        mid = int(mal_id)
    except (TypeError, ValueError):
        return None
    if mid <= 0:
        return None

    indexed = _read_mal_index(mid)
    if indexed is not None:
        return indexed

    scanned = _scan_cache_for_mal(mid)
    if scanned is not None:
        _write_mal_index(mid, scanned.anilist_id)
        return scanned

    if not network:
        return None

    gql = f"""
    query ($idMal: Int) {{
      Media(idMal: $idMal, type: ANIME) {{
{_MEDIA_FIELDS}
      }}
    }}
    """
    try:
        data = _post_graphql(gql, {"idMal": mid})
    except (URLError, OSError, ValueError, KeyError, AniListError):
        return None
    media = data.get("data", {}).get("Media")
    if not media:
        return None
    parsed = _parse_media(media)
    _write_cache(parsed)
    return parsed


def _parse_media(item: dict[str, Any]) -> AniListMedia:
    titles = item.get("title") or {}
    english = (titles.get("english") or "").strip() or None
    romaji = (titles.get("romaji") or "").strip() or None
    native = (titles.get("native") or "").strip() or None
    title = english or romaji or native or "Unknown"
    cover = item.get("coverImage") or {}
    poster = cover.get("extraLarge") or cover.get("large")
    description = (item.get("description") or "").replace("<br>", "\n")
    return AniListMedia(
        anilist_id=int(item["id"]),
        title=title,
        description=description.strip(),
        genres=[g for g in (item.get("genres") or [])[:5]],
        poster_url=poster,
        banner_url=item.get("bannerImage"),
        mal_id=int(item["idMal"]) if item.get("idMal") else None,
        episodes=int(item["episodes"]) if item.get("episodes") else None,
        title_english=english,
        title_romaji=romaji,
        title_native=native,
    )


def fetch_mal_id(anilist_id: int) -> int | None:
    """Resolve MyAnimeList id via AniList (no MAL OAuth required)."""
    media = fetch_anime(anilist_id)
    return media.mal_id if media else None


def _post_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise AniListError(f"HTTP {exc.code}: {detail}") from exc
    if payload.get("errors"):
        raise ValueError(str(payload["errors"]))
    return payload



def _media_from_cache_dict(data: dict[str, Any]) -> AniListMedia:
    """Rebuild ``AniListMedia`` from a cache JSON object (legacy-safe)."""
    def _opt_str(key: str) -> str | None:
        raw = data.get(key)
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    return AniListMedia(
        anilist_id=int(data["anilist_id"]),
        title=str(data.get("title") or "Unknown"),
        description=str(data.get("description") or ""),
        genres=list(data.get("genres") or []),
        poster_url=data.get("poster_url"),
        banner_url=data.get("banner_url"),
        mal_id=int(data["mal_id"]) if data.get("mal_id") else None,
        episodes=int(data["episodes"]) if data.get("episodes") else None,
        title_english=_opt_str("title_english"),
        title_romaji=_opt_str("title_romaji"),
        title_native=_opt_str("title_native"),
    )


def _cache_path(anilist_id: int) -> Path:
    return CACHE_DIR / f"{anilist_id}.json"


def _mal_index_path(mal_id: int) -> Path:
    return MAL_INDEX_DIR / f"{int(mal_id)}.json"


def _read_mal_index(mal_id: int) -> AniListMedia | None:
    path = _mal_index_path(mal_id)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        anilist_id = int(data["anilist_id"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return _read_cache(anilist_id)


def _write_mal_index(mal_id: int, anilist_id: int) -> None:
    MAL_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"mal_id": int(mal_id), "anilist_id": int(anilist_id)}
    _mal_index_path(mal_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _scan_cache_for_mal(mal_id: int) -> AniListMedia | None:
    """Best-effort: find an existing AniList cache entry that maps to this MAL id."""
    if not CACHE_DIR.is_dir():
        return None
    mid = int(mal_id)
    for path in CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if int(data.get("mal_id") or 0) != mid:
                continue
            if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
                continue
            media = _media_from_cache_dict(data)
            media.mal_id = mid
            return media
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return None


def _read_cache(anilist_id: int) -> AniListMedia | None:
    path = _cache_path(anilist_id)
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return _media_from_cache_dict(data)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(media: AniListMedia) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "anilist_id": media.anilist_id,
        "title": media.title,
        "description": media.description,
        "genres": media.genres,
        "poster_url": media.poster_url,
        "banner_url": media.banner_url,
        "mal_id": media.mal_id,
        "episodes": media.episodes,
        "title_english": media.title_english,
        "title_romaji": media.title_romaji,
        "title_native": media.title_native,
    }
    _cache_path(media.anilist_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if media.mal_id:
        _write_mal_index(int(media.mal_id), media.anilist_id)
