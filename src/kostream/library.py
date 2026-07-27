from __future__ import annotations

import json
import os
import re
from pathlib import Path

from kostream.anilist import fetch_anime
from kostream.catalog import CatalogEntry, load_catalog
from kostream.models import (
    Episode,
    Show,
    STRM_EXTENSION,
    VIDEO_EXTENSIONS,
    slugify,
)
from kostream.jellyfin import JellyfinConfig, fetch_shows as jellyfin_fetch_shows
from kostream.mal import load_cached_anime
from kostream.watch_progress import apply_mal_metadata

_REPO_MEDIA_SHOWS = Path(__file__).resolve().parents[2] / "media" / "shows"
_DEFAULT_ANIME = Path(os.environ.get("KOSTREAM_ANIME_ROOT", r"D:\Media\Ko-Stream\anime"))


def default_media_root() -> Path:
    """Anime library root (env ``KOSTREAM_ANIME_ROOT`` / ``KOSTREAM_MEDIA_ROOT``)."""
    env = (os.environ.get("KOSTREAM_ANIME_ROOT") or os.environ.get("KOSTREAM_MEDIA_ROOT") or "").strip()
    if env:
        return Path(env)
    if _DEFAULT_ANIME.exists() or _DEFAULT_ANIME.parent.exists():
        return _DEFAULT_ANIME
    return _REPO_MEDIA_SHOWS


MEDIA_ROOT = default_media_root()
# S01E02 / s04e01, 1x02 (season x ep), Episode 2 / Ep 2 / Ep.2
EPISODE_PATTERN = re.compile(
    r"(?:"
    r"[Ss](?P<season>\d+)[Ee](?P<ep>\d+)"
    r"|(?P<season2>\d+)[xX](?P<ep2>\d+)"
    r"|(?:Episode|Ep\.?)\s*(?P<ep3>\d+)"
    r")",
    re.IGNORECASE,
)
SEASON_LABEL_PATTERN = re.compile(
    r"(?:Season|Staffel)\s*(?P<n>\d+)|(?P<nth>\d+)(?:st|nd|rd|th)\s*Season",
    re.IGNORECASE,
)


def scan_library(root: Path | None = None, catalog_path: Path | None = None) -> list[Show]:
    """Load only catalog-selected shows when data/catalog/selected.json exists."""
    base = root or MEDIA_ROOT
    catalog = load_catalog(catalog_path)
    enabled = catalog.enabled

    if enabled:
        shows = [_build_show_from_entry(entry, base) for entry in enabled]
        shows = [s for s in shows if s is not None]
        return shows if shows else _demo_shows()

    return _scan_all(base)


def _attach_catalog_meta(show: Show, entry: CatalogEntry) -> Show:
    show.added_at = entry.added_at
    return show


def _scan_all(base: Path) -> list[Show]:
    shows: list[Show] = []

    if base.exists():
        for show_dir in sorted(base.iterdir()):
            if not show_dir.is_dir():
                continue
            episodes = _scan_show_folder(show_dir)
            if not episodes:
                continue
            show_id = slugify(show_dir.name)
            shows.append(
                _enrich_show(
                    Show(
                        id=show_id,
                        title=show_dir.name.replace("-", " ").replace("_", " "),
                        description=f"Local library — {len(episodes)} episode(s)",
                        poster=_find_poster(show_dir),
                        episodes=episodes,
                        genres=["Local"],
                    ),
                    show_dir,
                )
            )

    cfg = JellyfinConfig.from_env()
    if cfg:
        shows = _merge_shows(shows, jellyfin_fetch_shows(cfg))

    return shows if shows else _demo_shows()


def _build_show_from_entry(entry: CatalogEntry, base: Path) -> Show | None:
    if entry.mal_id:
        show = _mal_show_for_entry(entry, base)
        if show:
            return _attach_catalog_meta(show, entry)

    show: Show | None = None
    if entry.source in ("demo", "anilist"):
        show = _demo_show_for_entry(entry)
    elif entry.source == "jellyfin" and entry.jellyfin_id:
        show = _jellyfin_show_for_entry(entry)
    elif entry.source == "local" and entry.folder:
        show_dir = base / entry.folder
        if not show_dir.is_dir():
            show = _metadata_only_show(entry)
        else:
            episodes = _scan_show_folder(show_dir)
            if not episodes:
                show = _metadata_only_show(entry)
            else:
                show_id = entry.id or slugify(entry.folder)
                built = Show(
                    id=show_id,
                    title=entry.title or entry.folder.replace("-", " ").replace("_", " "),
                    description=f"Local — {len(episodes)} episode(s)",
                    poster=_find_poster(show_dir),
                    episodes=episodes,
                    genres=["Local"],
                    anilist_id=entry.anilist_id,
                )
                show = _enrich_show(built, show_dir, entry.anilist_id)
    else:
        show = _metadata_only_show(entry)

    if show is None:
        return None
    return _attach_catalog_meta(show, entry)


def _mal_show_for_entry(entry: CatalogEntry, base: Path) -> Show | None:
    cached = load_cached_anime(entry.mal_id) if entry.mal_id else None
    show_id = entry.id

    local_episodes: list[Episode] = []
    local_poster: str | None = None
    if entry.folder:
        show_dir = base / entry.folder
        if show_dir.is_dir():
            local_episodes = _scan_show_folder(show_dir)
            local_poster = _find_poster(show_dir)

    if cached:
        status_label = cached.list_status.replace("_", " ").title()
        score_bit = f" · Your score: {cached.score}/10" if cached.score else ""
        desc = cached.synopsis[:480] if cached.synopsis else f"From your MyAnimeList ({status_label})."
        if len(desc) < 500:
            desc = f"{desc} [{status_label}{score_bit}]".strip()

        ep_count = _mal_episode_count(cached)
        display_season = _infer_display_season(
            entry.folder, entry.title or cached.title, local_episodes
        )
        episodes = _merge_mal_and_local_episodes(
            show_id,
            ep_count,
            local_episodes,
            display_season=display_season,
            episode_titles=cached.episode_titles,
        )
        local_n = sum(1 for e in episodes if e.filename != "demo.mp4")
        if local_n:
            desc = f"MAL + {local_n} local file(s). {desc}"[:500]

        show = Show(
            id=show_id,
            title=cached.title,
            description=desc[:500],
            poster=local_poster,
            poster_url=cached.poster_url,
            genres=cached.genres or ["MAL"],
            mal_id=cached.mal_id,
            episodes=episodes,
        )
        apply_mal_metadata(show, cached)
        return _attach_catalog_meta(show, entry)

    if local_episodes:
        display_season = _infer_display_season(
            entry.folder, entry.title, local_episodes
        )
        episodes = _merge_mal_and_local_episodes(
            show_id,
            max(len(local_episodes), max((e.number for e in local_episodes), default=1)),
            local_episodes,
            display_season=display_season,
        )
        show = Show(
            id=show_id,
            title=entry.title or (entry.folder or show_id),
            description=f"MAL + local — {len(local_episodes)} episode(s)",
            poster=local_poster,
            episodes=episodes,
            genres=["Local", "MAL"],
            mal_id=entry.mal_id,
        )
        return _attach_catalog_meta(show, entry)

    show = _metadata_only_show(entry)
    show.mal_id = entry.mal_id
    return show


def _merge_mal_and_local_episodes(
    show_id: str,
    mal_count: int,
    local: list[Episode],
    *,
    display_season: int = 1,
    episode_titles: dict[int, str] | None = None,
) -> list[Episode]:
    """Full episode list (MAL count), overlaying local files by episode number.

    Season tags in filenames (S01 vs S04) do not create separate rows — they are
    normalized to ``display_season`` so stream-only slots stay aligned.
    Titles use MAL names when available, else ``Episode N``.
    """
    season = max(1, display_season)
    by_number: dict[int, Episode] = {}
    for ep in local:
        by_number[ep.number] = ep

    total = max(mal_count, max(by_number.keys(), default=0), 0)
    merged: list[Episode] = []
    for number in range(1, total + 1):
        local_ep = by_number.get(number)
        title = _mal_episode_display_title(number, episode_titles)
        if local_ep:
            merged.append(
                Episode(
                    id=f"{show_id}-s{season:02d}e{number:02d}",
                    show_id=show_id,
                    season=season,
                    number=number,
                    title=title,
                    filename=local_ep.filename,
                )
            )
        else:
            merged.append(
                Episode(
                    id=f"{show_id}-s{season:02d}e{number:02d}",
                    show_id=show_id,
                    season=season,
                    number=number,
                    title=title,
                    filename="demo.mp4",
                )
            )
    return merged


def _mal_episode_display_title(number: int, titles: dict[int, str] | None) -> str:
    if titles:
        name = (titles.get(number) or "").strip()
        if name:
            return name
    return f"Episode {number}"


def _infer_display_season(
    folder: str | None,
    title: str | None,
    local: list[Episode],
) -> int:
    """Prefer Season N from folder/title; else common season from local files."""
    for text in (folder, title):
        if not text:
            continue
        match = SEASON_LABEL_PATTERN.search(text)
        if match:
            raw = match.group("n") or match.group("nth")
            if raw:
                return max(1, int(raw))

    seasons = [ep.season for ep in local if ep.season >= 1]
    if seasons:
        return max(set(seasons), key=seasons.count)
    return 1


def _mal_episode_count(cached) -> int:
    total = cached.num_episodes or 0
    watched = cached.num_episodes_watched or 0
    if cached.anime_status == "currently_airing":
        total = max(total, watched + 1)
    if total <= 0:
        total = max(watched, 1)
    return total


def _mal_episode_list(show_id: str, count: int) -> list[Episode]:
    return [
        Episode(
            f"{show_id}-s01e{num:02d}",
            show_id,
            1,
            num,
            f"Episode {num}",
            "demo.mp4",
        )
        for num in range(1, count + 1)
    ]


def _metadata_only_show(entry: CatalogEntry) -> Show:
    show_id = entry.id
    meta = fetch_anime(entry.anilist_id) if entry.anilist_id else None
    title = entry.title or (meta.title if meta else show_id.replace("-", " ").title())
    description = meta.description[:500] if meta and meta.description else "No local episodes yet."
    return Show(
        id=show_id,
        title=title,
        description=description,
        poster_url=meta.poster_url if meta else None,
        banner_url=meta.banner_url if meta else None,
        genres=meta.genres if meta else ["Catalog"],
        anilist_id=entry.anilist_id,
        episodes=[
            Episode(f"{show_id}-demo", show_id, 1, 1, "Episode 1 (add files)", "demo.mp4"),
        ],
    )


def _demo_show_for_entry(entry: CatalogEntry) -> Show:
    show = _metadata_only_show(entry)
    show.genres = list(dict.fromkeys([*(show.genres or []), "Demo"]))
    return show


def _jellyfin_show_for_entry(entry: CatalogEntry) -> Show | None:
    cfg = JellyfinConfig.from_env()
    if not cfg:
        return _metadata_only_show(entry)
    remote = jellyfin_fetch_shows(cfg)
    match = next((s for s in remote if s.id == f"jf-{entry.jellyfin_id}"), None)
    if not match:
        match = next((s for s in remote if s.id == entry.id), None)
    if not match:
        return _metadata_only_show(entry)
    if entry.anilist_id:
        meta = fetch_anime(entry.anilist_id)
        if meta:
            match.title = entry.title or meta.title
            match.description = meta.description[:500] or match.description
            match.poster_url = meta.poster_url
            match.banner_url = meta.banner_url
            match.genres = meta.genres or match.genres
            match.anilist_id = entry.anilist_id
    return match


def _enrich_show(show: Show, show_dir: Path, anilist_id: int | None = None) -> Show:
    aid = anilist_id or show.anilist_id
    if aid:
        meta = fetch_anime(aid)
        if meta:
            show.title = meta.title
            show.description = meta.description[:500] or show.description
            show.poster_url = meta.poster_url
            show.banner_url = meta.banner_url
            show.genres = meta.genres or show.genres
            show.anilist_id = aid
    local_poster = _find_poster(show_dir)
    if local_poster:
        show.poster = local_poster
    return show


def _scan_show_folder(show_dir: Path) -> list[Episode]:
    show_id = slugify(show_dir.name)
    episodes: list[Episode] = []
    for path in sorted(show_dir.rglob("*")):
        suffix = path.suffix.lower()
        if suffix == STRM_EXTENSION:
            url = path.read_text(encoding="utf-8").strip()
            if not url:
                continue
            season, number = _parse_episode_numbers(path.stem)
            episodes.append(
                Episode(
                    id=f"{show_id}-s{season:02d}e{number:02d}",
                    show_id=show_id,
                    season=season,
                    number=number,
                    title=f"Episode {number}",
                    filename=f"strm:{url}",
                )
            )
            continue
        if suffix not in VIDEO_EXTENSIONS:
            continue
        season, number = _parse_episode_numbers(path.name)
        rel = path.relative_to(show_dir)
        episodes.append(
            Episode(
                id=f"{show_id}-s{season:02d}e{number:02d}",
                show_id=show_id,
                season=season,
                number=number,
                title=f"Episode {number}",
                filename=str(rel).replace("\\", "/"),
            )
        )
    return sorted(episodes, key=lambda e: (e.season, e.number))


def _parse_episode_numbers(name: str) -> tuple[int, int]:
    match = EPISODE_PATTERN.search(name)
    if not match:
        return 1, 1
    if match.group("season") and match.group("ep"):
        return int(match.group("season")), int(match.group("ep"))
    if match.group("season2") and match.group("ep2"):
        return int(match.group("season2")), int(match.group("ep2"))
    if match.group("ep3"):
        return 1, int(match.group("ep3"))
    return 1, 1


def _find_poster(show_dir: Path) -> str | None:
    for name in ("poster.jpg", "poster.png", "folder.jpg", "cover.jpg"):
        candidate = show_dir / name
        if candidate.exists():
            return candidate.name
    return None


def get_show(show_id: str, root: Path | None = None, catalog_path: Path | None = None) -> Show | None:
    for show in scan_library(root, catalog_path):
        if show.id == show_id:
            return show
    return None


def _demo_shows() -> list[Show]:
    return [
        Show(
            id="demo-one-piece",
            title="Demo — One Piece",
            description="Add entries in Catalog or files under media/shows/.",
            type_label="TV",
            genres=["Adventure", "Demo"],
            anilist_id=21,
            episodes=[Episode("demo-1", "demo-one-piece", 1, 1, "Episode 1", "demo.mp4")],
        ),
        Show(
            id="demo-frieren",
            title="Demo — Frieren",
            description="Use Catalog page to pick shows — only those load.",
            type_label="TV",
            genres=["Fantasy", "Demo"],
            anilist_id=154587,
            episodes=[Episode("demo-f1", "demo-frieren", 1, 1, "Episode 1", "demo.mp4")],
        ),
    ]


def load_progress(path: Path) -> dict:
    """Episode progress map: id → seconds (legacy) or {seconds, duration}."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_progress(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _merge_shows(local: list[Show], remote: list[Show]) -> list[Show]:
    by_id = {s.id: s for s in local}
    for show in remote:
        by_id[show.id] = show
    return list(by_id.values())
