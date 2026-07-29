from __future__ import annotations

import json
import os
import re
from pathlib import Path

from kostream.anilist import AniListError, fetch_anime, fetch_anime_by_mal_id
from kostream.catalog import CatalogEntry, load_catalog
from kostream.jsonio import atomic_write_json
from kostream.models import (
    Episode,
    Show,
    STRM_EXTENSION,
    VIDEO_EXTENSIONS,
    slugify,
)
from kostream.jellyfin import JellyfinConfig, fetch_shows as jellyfin_fetch_shows
from kostream.mal import apply_list_row_to_anime, get_anime_list_row, load_cached_anime
from kostream.titles import (
    all_searchable_titles,
    merge_title_variants,
    pick_display_title,
    resolve_title_language,
    variants_from_anilist_fields,
    variants_from_mal_fields,
)
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


def _current_title_pref(explicit: str | None = None) -> str:
    return resolve_title_language(explicit)


def _apply_title_variants(show: Show, variants, *, title_language: str | None = None) -> Show:
    pref = _current_title_pref(title_language)
    show.title = pick_display_title(variants, pref)
    show.title_aliases = all_searchable_titles(variants)
    return show


def _variants_for_mal_entry(cached, *, anilist_meta=None):
    mal_v = variants_from_mal_fields(
        title=cached.title,
        title_en=cached.title_en,
        title_ja=cached.title_ja,
        title_ger=cached.title_ger,
        synonyms=cached.title_synonyms,
    )
    al_v = None
    if anilist_meta is not None:
        al_v = variants_from_anilist_fields(
            title=anilist_meta.title,
            english=anilist_meta.title_english,
            romaji=anilist_meta.title_romaji,
            native=anilist_meta.title_native,
        )
    elif getattr(cached, "mal_id", None):
        meta = fetch_anime_by_mal_id(cached.mal_id, network=False)
        if meta:
            al_v = variants_from_anilist_fields(
                title=meta.title,
                english=meta.title_english,
                romaji=meta.title_romaji,
                native=meta.title_native,
            )
    return merge_title_variants(mal_v, al_v)


def scan_library(
    root: Path | None = None,
    catalog_path: Path | None = None,
    *,
    user_id: str | None = None,
) -> list[Show]:
    """Load only catalog-selected shows when data/catalog/selected.json exists."""
    base = root or MEDIA_ROOT
    catalog = load_catalog(catalog_path)
    enabled = catalog.enabled

    if enabled:
        list_state: dict = {}
        if user_id:
            from kostream.mal import load_anime_list_state

            list_state = load_anime_list_state(user_id)

        def _row_for(entry: CatalogEntry):
            if not entry.mal_id:
                return None
            raw = list_state.get(str(int(entry.mal_id)))
            return dict(raw) if isinstance(raw, dict) else None

        shows: list[Show] = []
        for entry in enabled:
            try:
                built = _build_show_from_entry(
                    entry, base, user_id=user_id, list_row=_row_for(entry)
                )
            except (OSError, ValueError, TypeError, KeyError, AniListError):
                # Missing disks / corrupt cache / bad catalog row must not 500 UI.
                continue
            if built is not None:
                shows.append(built)
        return shows if shows else _demo_shows()

    return _scan_all(base)


def _attach_catalog_meta(show: Show, entry: CatalogEntry) -> Show:
    show.added_at = entry.added_at
    return show


def _scan_all(base: Path) -> list[Show]:
    shows: list[Show] = []

    try:
        root_ok = base.is_dir()
    except OSError:
        root_ok = False

    if root_ok:
        try:
            children = sorted(base.iterdir())
        except OSError:
            children = []
        for show_dir in children:
            if not show_dir.is_dir():
                continue
            try:
                episodes, latest_mtime = _scan_show_folder(show_dir)
            except OSError:
                continue
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
                        latest_local_mtime=latest_mtime,
                    ),
                    show_dir,
                )
            )

    cfg = JellyfinConfig.from_env()
    if cfg:
        shows = _merge_shows(shows, jellyfin_fetch_shows(cfg))

    return shows if shows else _demo_shows()


def _build_show_from_entry(
    entry: CatalogEntry,
    base: Path,
    *,
    user_id: str | None = None,
    list_row: dict | None = None,
) -> Show | None:
    if entry.mal_id:
        show = _mal_show_for_entry(entry, base, user_id=user_id, list_row=list_row)
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
            episodes, latest_mtime = _scan_show_folder(show_dir)
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
                    latest_local_mtime=latest_mtime,
                )
                show = _enrich_show(built, show_dir, entry.anilist_id)
    else:
        show = _metadata_only_show(entry)

    if show is None:
        return None
    return _attach_catalog_meta(show, entry)


def _mal_show_for_entry(
    entry: CatalogEntry,
    base: Path,
    *,
    user_id: str | None = None,
    list_row: dict | None = None,
) -> Show | None:
    cached = load_cached_anime(entry.mal_id) if entry.mal_id else None
    if list_row is None and user_id and entry.mal_id:
        list_row = get_anime_list_row(user_id, entry.mal_id)
    if cached and list_row:
        apply_list_row_to_anime(cached, list_row)
    show_id = entry.id

    local_episodes: list[Episode] = []
    local_poster: str | None = None
    latest_mtime: float | None = None
    if entry.folder:
        show_dir = base / entry.folder
        if show_dir.is_dir():
            local_episodes, latest_mtime = _scan_show_folder(show_dir)
            local_poster = _find_poster(show_dir)

    if cached:
        if list_row and list_row.get("list_status"):
            status_label = str(list_row["list_status"]).replace("_", " ").title()
            user_score = int(list_row.get("score") or 0)
            score_bit = f" · Your score: {user_score}/10" if user_score else ""
        else:
            status_label = "Not watched"
            score_bit = ""
        desc = cached.synopsis[:480] if cached.synopsis else f"From MyAnimeList ({status_label})."
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
        show = Show(
            id=show_id,
            title=cached.title,
            description=desc[:500],
            poster=local_poster,
            poster_url=_prefer_local_anime_poster(cached.mal_id, cached.poster_url),
            genres=cached.genres or ["MAL"],
            mal_id=cached.mal_id,
            episodes=episodes,
            latest_local_mtime=latest_mtime,
        )
        _apply_title_variants(show, _variants_for_mal_entry(cached))
        apply_mal_metadata(show, cached, list_row)
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
            description=f"{len(local_episodes)} local episode(s).",
            poster=local_poster,
            episodes=episodes,
            genres=["Local", "MAL"],
            mal_id=entry.mal_id,
            latest_local_mtime=latest_mtime,
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
        existing = by_number.get(ep.number)
        # Prefer files tagged with the show's display season (S02+ after rename).
        if existing is None:
            by_number[ep.number] = ep
        elif ep.season == season and existing.season != season:
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


def _metadata_only_show(entry: CatalogEntry) -> Show:
    show_id = entry.id
    meta = fetch_anime(entry.anilist_id) if entry.anilist_id else None
    title = entry.title or (meta.title if meta else show_id.replace("-", " ").title())
    description = meta.description[:500] if meta and meta.description else "No local episodes yet."
    show = Show(
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
    if meta:
        variants = merge_title_variants(
            variants_from_anilist_fields(
                title=meta.title,
                english=meta.title_english,
                romaji=meta.title_romaji,
                native=meta.title_native,
            ),
            variants_from_mal_fields(title=entry.title) if entry.title else None,
        )
        _apply_title_variants(show, variants)
    elif entry.title:
        _apply_title_variants(show, variants_from_mal_fields(title=entry.title))
    return show


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
            match.description = meta.description[:500] or match.description
            match.poster_url = meta.poster_url
            match.banner_url = meta.banner_url
            match.genres = meta.genres or match.genres
            match.anilist_id = entry.anilist_id
            _apply_title_variants(
                match,
                merge_title_variants(
                    variants_from_anilist_fields(
                        title=meta.title,
                        english=meta.title_english,
                        romaji=meta.title_romaji,
                        native=meta.title_native,
                    ),
                    variants_from_mal_fields(title=entry.title or match.title),
                ),
            )
    return match


def _enrich_show(show: Show, show_dir: Path, anilist_id: int | None = None) -> Show:
    aid = anilist_id or show.anilist_id
    if aid:
        meta = fetch_anime(aid)
        if meta:
            show.description = meta.description[:500] or show.description
            show.poster_url = meta.poster_url
            show.banner_url = meta.banner_url
            show.genres = meta.genres or show.genres
            show.anilist_id = aid
            _apply_title_variants(
                show,
                merge_title_variants(
                    variants_from_anilist_fields(
                        title=meta.title,
                        english=meta.title_english,
                        romaji=meta.title_romaji,
                        native=meta.title_native,
                    ),
                    variants_from_mal_fields(title=show.title),
                ),
            )
    local_poster = _find_poster(show_dir)
    if local_poster:
        show.poster = local_poster
    return show


def count_unique_local_episodes(show_dir: Path) -> int:
    """Count distinct ``(season, number)`` video slots under a show folder."""
    try:
        if not show_dir.is_dir():
            return 0
        episodes, _mtime = _scan_show_folder(show_dir)
    except OSError:
        return 0
    return len({(ep.season, ep.number) for ep in episodes})


def _scan_show_folder(show_dir: Path) -> tuple[list[Episode], float | None]:
    """Scan local videos/strm under ``show_dir``.

    Returns ``(episodes, latest_local_mtime)`` where mtime is the max filesystem
    mtime of real video files (``.mp4`` / ``.mkv`` / ``.webm``), ignoring strm.
    """
    show_id = slugify(show_dir.name)
    episodes: list[Episode] = []
    latest_mtime: float | None = None
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
        try:
            mtime = path.stat().st_mtime
            if latest_mtime is None or mtime > latest_mtime:
                latest_mtime = mtime
        except OSError:
            pass
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
    return sorted(episodes, key=lambda e: (e.season, e.number)), latest_mtime


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


def _prefer_local_anime_poster(mal_id: int | None, remote_url: str | None) -> str | None:
    """Prefer Thumbnail/anime/<mal_id> over MAL CDN URL."""
    if mal_id:
        try:
            from kostream.thumbnails import thumbnail_public_url

            local = thumbnail_public_url("anime", int(mal_id))
            if local:
                return local
        except (OSError, TypeError, ValueError):
            pass
    return remote_url


def get_show(
    show_id: str,
    root: Path | None = None,
    catalog_path: Path | None = None,
    *,
    user_id: str | None = None,
) -> Show | None:
    for show in scan_library(root, catalog_path, user_id=user_id):
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
    atomic_write_json(path, data)


def _merge_shows(local: list[Show], remote: list[Show]) -> list[Show]:
    by_id = {s.id: s for s in local}
    for show in remote:
        by_id[show.id] = show
    return list(by_id.values())
