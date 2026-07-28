"""MyAnimeList OAuth2 + animelist sync for Ko-Stream catalog."""

from __future__ import annotations

import base64
import html as html_lib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from kostream.catalog import CatalogEntry, CatalogState, load_catalog, save_catalog, upsert_entry
from kostream.jsonio import atomic_write_json
from kostream.models import RelatedAnime

log = logging.getLogger(__name__)

MAL_AUTH_URL = "https://myanimelist.net/v1/oauth2/authorize"
MAL_TOKEN_URL = "https://myanimelist.net/v1/oauth2/token"
MAL_API_URL = "https://api.myanimelist.net/v2"
MAL_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "mal"
# Shared anime/manga metadata cache (personal list fields live in per-user overlay).
CACHE_DIR = MAL_DATA_DIR / "cache"

# Personal list fields — never written to shared cache after list-state split.
ANIME_LIST_FIELD_KEYS = ("list_status", "num_episodes_watched", "score")
ANIME_LIST_STATUSES = frozenset(
    {"watching", "completed", "on_hold", "dropped", "plan_to_watch"}
)
USER_AGENT = "Ko-Stream/0.2 (+https://github.com/KosovarM/Ko-Stream; local MAL sync)"
JIKAN_EPISODES_URL = "https://api.jikan.moe/v4/anime/{mal_id}/episodes"
# Dummy slug works; MAL serves the canonical episode list page.
MAL_EPISODES_PAGE_URL = "https://myanimelist.net/anime/{mal_id}/_/episode"
MAL_EPISODE_TITLE_RE = re.compile(
    r'<td[^>]*class="[^"]*episode-title[^"]*"[^>]*>\s*'
    r'<a[^>]+href="[^"]*/episode/(\d+)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)

ANIMELIST_FIELDS = (
    "list_status,num_episodes,synopsis,genres,studios,main_picture,mean,media_type,status,"
    "start_date,start_season,broadcast,alternative_titles"
)

MANGALIST_FIELDS = (
    "list_status,num_volumes,num_chapters,synopsis,genres,main_picture,mean,media_type,status,"
    "start_date,alternative_titles"
)

ANIME_DETAIL_FIELDS = (
    "related_anime,synopsis,genres,studios,main_picture,mean,num_episodes,status,media_type,title,"
    "broadcast,start_date,start_season,alternative_titles"
)

MANGA_CACHE_DIR = MAL_DATA_DIR / "manga_cache"


class MalError(Exception):
    """MyAnimeList API or OAuth error."""


@dataclass
class MalConfig:
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> MalConfig | None:
        import os

        client_id = os.environ.get("MAL_CLIENT_ID", "").strip()
        client_secret = os.environ.get("MAL_CLIENT_SECRET", "").strip()
        redirect_uri = os.environ.get(
            "MAL_REDIRECT_URI", "http://127.0.0.1:5001/auth/mal/callback"
        ).strip()
        if not client_id:
            return None
        if len(client_id) != 32:
            raise MalError(
                f"MAL_CLIENT_ID must be exactly 32 characters (got {len(client_id)}). "
                "Copy it again from myanimelist.net/apiconfig — no extra digits or spaces."
            )
        return cls(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)


@dataclass
class MalTokens:
    access_token: str
    refresh_token: str
    expires_at: float
    username: str | None = None

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - 60


@dataclass
class MalAnimeEntry:
    mal_id: int
    title: str
    synopsis: str
    poster_url: str | None
    genres: list[str]
    num_episodes: int
    list_status: str
    num_episodes_watched: int
    anime_status: str | None
    score: int
    mean_score: float | None
    related_anime: list[RelatedAnime] = field(default_factory=list)
    broadcast_day: str | None = None  # monday..sunday (MAL / JST)
    broadcast_time: str | None = None  # HH:MM JST
    # Episode number → title (from MAL episode pages via Jikan; official API has none)
    episode_titles: dict[int, str] = field(default_factory=dict)
    media_type: str | None = None  # tv | movie | ova | ona | special | …
    release_year: int | None = None
    studios: list[str] = field(default_factory=list)
    title_en: str | None = None
    title_ja: str | None = None
    title_ger: str | None = None  # not in MAL API; reserved for future / manual
    title_synonyms: list[str] = field(default_factory=list)


@dataclass
class MalMangaEntry:
    mal_id: int
    title: str
    synopsis: str
    poster_url: str | None
    genres: list[str]
    num_volumes: int
    num_chapters: int
    list_status: str
    num_volumes_read: int
    num_chapters_read: int
    manga_status: str | None
    score: int
    mean_score: float | None
    media_type: str | None = None  # manga | manhwa | manhua | novel | …
    release_year: int | None = None
    title_en: str | None = None
    title_ja: str | None = None
    title_ger: str | None = None
    title_synonyms: list[str] = field(default_factory=list)


def _year_in_range(year: int) -> int | None:
    return year if 1900 <= year <= 2100 else None


def _parse_studio_names(node: dict[str, Any] | None) -> list[str]:
    """Extract studio display names from a MAL anime node or cache payload."""
    if not isinstance(node, dict):
        return []
    raw = node.get("studios")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names



def _parse_alternative_titles(node: dict[str, Any] | None) -> tuple[str | None, str | None, str | None, list[str]]:
    """Return ``(en, ja, ger, synonyms)`` from a MAL node or cache payload.

    MAL does not expose German titles; ``ger`` is only filled if a nonstandard
    ``ger``/``de`` key appears (manual cache / future sources).
    """
    if not isinstance(node, dict):
        return None, None, None, []
    alt = node.get("alternative_titles")
    if not isinstance(alt, dict):
        # Flat cache fields
        en = str(node.get("title_en") or "").strip() or None
        ja = str(node.get("title_ja") or "").strip() or None
        ger = str(node.get("title_ger") or "").strip() or None
        raw_syn = node.get("title_synonyms") or []
        synonyms: list[str] = []
        if isinstance(raw_syn, list):
            for item in raw_syn:
                name = str(item or "").strip()
                if name:
                    synonyms.append(name)
        return en, ja, ger, synonyms
    en = str(alt.get("en") or "").strip() or None
    ja = str(alt.get("ja") or "").strip() or None
    ger = str(alt.get("ger") or alt.get("de") or "").strip() or None
    synonyms = []
    for item in alt.get("synonyms") or []:
        name = str(item or "").strip()
        if name:
            synonyms.append(name)
    return en, ja, ger, synonyms

def _year_from_mal_date_string(value: str) -> int | None:
    """Parse MAL ``date`` fields: ``YYYY``, ``YYYY-MM``, or ``YYYY-MM-DD``."""
    text = value.strip()
    if not text:
        return None
    head = text.split("-", 1)[0]
    try:
        return _year_in_range(int(head))
    except ValueError:
        return None


def parse_mal_start_year(source: dict[str, Any] | None) -> int | None:
    """Extract release/start year from a MAL API node or ``start_date`` value.

    MAL v2 returns ``start_date`` as an ISO date string (e.g. ``"2011-07-22"``),
    not as ``{year, month, day}``. ``start_season.year`` is used as a fallback.
    """
    if not isinstance(source, dict):
        return None

    start = source.get("start_date") if "start_date" in source else source
    if isinstance(start, str):
        year = _year_from_mal_date_string(start)
        if year is not None:
            return year
    elif isinstance(start, dict):
        try:
            year = int(start.get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        found = _year_in_range(year)
        if found is not None:
            return found

    season = source.get("start_season")
    if isinstance(season, dict):
        try:
            year = int(season.get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        return _year_in_range(year)

    return None


def _normalize_user_id(user_id: str) -> str:
    uid = str(user_id or "").strip()
    if not uid or "/" in uid or "\\" in uid or uid in (".", ".."):
        raise MalError("Invalid user_id for MAL tokens.")
    return uid


def mal_user_dir(user_id: str) -> Path:
    """Per-user MAL directory: ``data/mal/users/<user_id>/``."""
    return MAL_DATA_DIR / "users" / _normalize_user_id(user_id)


def token_path(user_id: str) -> Path:
    return mal_user_dir(user_id) / "tokens.json"


def pending_oauth_path(user_id: str) -> Path:
    return mal_user_dir(user_id) / "pending_oauth.json"


def last_sync_path(user_id: str) -> Path:
    return mal_user_dir(user_id) / "last_sync.json"


def anime_list_state_path(user_id: str) -> Path:
    return mal_user_dir(user_id) / "anime_list_state.json"


def manga_list_state_path(user_id: str) -> Path:
    return mal_user_dir(user_id) / "manga_list_state.json"


def _load_list_state(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out[str(key)] = value
    return out


def _save_list_state(path: Path, state: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(path, state, ensure_ascii=False)


def load_anime_list_state(user_id: str) -> dict[str, dict[str, Any]]:
    """mal_id (str) → {list_status, num_episodes_watched, score}."""
    return _load_list_state(anime_list_state_path(user_id))


def save_anime_list_state(user_id: str, state: dict[str, dict[str, Any]]) -> None:
    _save_list_state(anime_list_state_path(user_id), state)


def load_manga_list_state(user_id: str) -> dict[str, dict[str, Any]]:
    """mal_id (str) → {list_status, num_volumes_read, num_chapters_read, score}."""
    return _load_list_state(manga_list_state_path(user_id))


def save_manga_list_state(user_id: str, state: dict[str, dict[str, Any]]) -> None:
    _save_list_state(manga_list_state_path(user_id), state)


def get_anime_list_row(user_id: str, mal_id: int) -> dict[str, Any] | None:
    state = load_anime_list_state(user_id)
    row = state.get(str(int(mal_id)))
    return dict(row) if isinstance(row, dict) else None


def get_manga_list_row(user_id: str, mal_id: int) -> dict[str, Any] | None:
    state = load_manga_list_state(user_id)
    row = state.get(str(int(mal_id)))
    return dict(row) if isinstance(row, dict) else None


def upsert_anime_list_row(
    user_id: str,
    mal_id: int,
    *,
    list_status: str | None = None,
    num_episodes_watched: int | None = None,
    score: int | None = None,
) -> dict[str, Any]:
    state = load_anime_list_state(user_id)
    key = str(int(mal_id))
    row = dict(state.get(key) or {})
    if list_status is not None:
        row["list_status"] = str(list_status)
    if num_episodes_watched is not None:
        row["num_episodes_watched"] = max(0, int(num_episodes_watched))
    if score is not None:
        row["score"] = max(0, int(score))
    row.setdefault("list_status", "plan_to_watch")
    row.setdefault("num_episodes_watched", 0)
    row.setdefault("score", 0)
    state[key] = row
    save_anime_list_state(user_id, state)
    return row


def upsert_manga_list_row(
    user_id: str,
    mal_id: int,
    *,
    list_status: str | None = None,
    num_volumes_read: int | None = None,
    num_chapters_read: int | None = None,
    score: int | None = None,
) -> dict[str, Any]:
    state = load_manga_list_state(user_id)
    key = str(int(mal_id))
    row = dict(state.get(key) or {})
    if list_status is not None:
        row["list_status"] = str(list_status)
    if num_volumes_read is not None:
        row["num_volumes_read"] = max(0, int(num_volumes_read))
    if num_chapters_read is not None:
        row["num_chapters_read"] = max(0, int(num_chapters_read))
    if score is not None:
        row["score"] = max(0, int(score))
    row.setdefault("list_status", "plan_to_read")
    row.setdefault("num_volumes_read", 0)
    row.setdefault("num_chapters_read", 0)
    row.setdefault("score", 0)
    state[key] = row
    save_manga_list_state(user_id, state)
    return row


def write_anime_list_state_from_entries(user_id: str, entries: list[MalAnimeEntry]) -> None:
    state = load_anime_list_state(user_id)
    for item in entries:
        state[str(item.mal_id)] = {
            "list_status": item.list_status,
            "num_episodes_watched": int(item.num_episodes_watched or 0),
            "score": int(item.score or 0),
        }
    save_anime_list_state(user_id, state)


def write_manga_list_state_from_entries(user_id: str, entries: list[MalMangaEntry]) -> None:
    state = load_manga_list_state(user_id)
    for item in entries:
        state[str(item.mal_id)] = {
            "list_status": item.list_status,
            "num_volumes_read": int(item.num_volumes_read or 0),
            "num_chapters_read": int(item.num_chapters_read or 0),
            "score": int(item.score or 0),
        }
    save_manga_list_state(user_id, state)


def apply_list_row_to_anime(entry: MalAnimeEntry, list_row: dict[str, Any] | None) -> MalAnimeEntry:
    """Overlay personal list fields onto a metadata cache entry (in place)."""
    if not list_row:
        return entry
    if list_row.get("list_status"):
        entry.list_status = str(list_row["list_status"])
    if "num_episodes_watched" in list_row:
        entry.num_episodes_watched = int(list_row.get("num_episodes_watched") or 0)
    if "score" in list_row:
        entry.score = int(list_row.get("score") or 0)
    return entry


def apply_list_row_to_manga(entry: MalMangaEntry, list_row: dict[str, Any] | None) -> MalMangaEntry:
    if not list_row:
        return entry
    if list_row.get("list_status"):
        entry.list_status = str(list_row["list_status"])
    if "num_volumes_read" in list_row:
        entry.num_volumes_read = int(list_row.get("num_volumes_read") or 0)
    if "num_chapters_read" in list_row:
        entry.num_chapters_read = int(list_row.get("num_chapters_read") or 0)
    if "score" in list_row:
        entry.score = int(list_row.get("score") or 0)
    return entry


def load_cached_anime_for_user(mal_id: int, user_id: str | None) -> MalAnimeEntry | None:
    """Load shared metadata and merge this user's list overlay when ``user_id`` is set."""
    entry = load_cached_anime(mal_id)
    if entry is None or not user_id:
        return entry
    return apply_list_row_to_anime(entry, get_anime_list_row(user_id, mal_id))


def load_cached_manga_for_user(mal_id: int, user_id: str | None) -> MalMangaEntry | None:
    entry = load_cached_manga(mal_id)
    if entry is None or not user_id:
        return entry
    return apply_list_row_to_manga(entry, get_manga_list_row(user_id, mal_id))


def is_connected(user_id: str) -> bool:
    return load_tokens(user_id) is not None


def load_tokens(user_id: str) -> MalTokens | None:
    path = token_path(user_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("access_token") or not data.get("refresh_token"):
        return None
    return MalTokens(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=float(data.get("expires_at", 0)),
        username=data.get("username"),
    )


def save_tokens(user_id: str, tokens: MalTokens) -> None:
    path = token_path(user_id)
    payload = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "expires_at": tokens.expires_at,
        "username": tokens.username,
    }
    atomic_write_json(path, payload, trailing_newline=False)


def disconnect(user_id: str) -> None:
    """Remove this user's MAL tokens (and any pending OAuth). Does not touch catalog."""
    path = token_path(user_id)
    if path.exists():
        path.unlink()
    pending = pending_oauth_path(user_id)
    if pending.exists():
        pending.unlink()


def start_oauth(cfg: MalConfig, user_id: str) -> str:
    """Return authorization URL. Stores PKCE verifier for this user."""
    return prepare_oauth(cfg, user_id)["authorize_url"]


def prepare_oauth(cfg: MalConfig, user_id: str) -> dict[str, str]:
    """Create OAuth session and return login + authorize URLs (same PKCE session)."""
    uid = _normalize_user_id(user_id)
    state = secrets.token_urlsafe(32)
    code_verifier = _new_code_verifier()

    pending = pending_oauth_path(uid)
    atomic_write_json(
        pending,
        {
            "user_id": uid,
            "state": state,
            "code_verifier": code_verifier,
            "created_at": time.time(),
        },
        indent=None,
        trailing_newline=False,
    )

    query = urlencode(
        {
            "response_type": "code",
            "client_id": cfg.client_id,
            "state": state,
            "redirect_uri": cfg.redirect_uri,
            "code_challenge": code_verifier,
            "code_challenge_method": "plain",
        }
    )
    authorize_path = f"/v1/oauth2/authorize?{query}"
    return {
        "authorize_url": f"{MAL_AUTH_URL}?{query}",
        "login_first_url": (
            "https://myanimelist.net/login.php?from="
            + urllib.parse.quote(authorize_path, safe="")
        ),
    }


def complete_oauth_with_code(cfg: MalConfig, raw_code: str, user_id: str) -> MalTokens:
    """Finish OAuth using pasted code (full URL or code string)."""
    uid = _normalize_user_id(user_id)
    code = extract_oauth_code(raw_code)
    pending_path = pending_oauth_path(uid)
    if not pending_path.exists():
        raise MalError("OAuth session expired — open Connect MyAnimeList again first.")
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    _assert_pending_user(pending, uid)
    if time.time() - float(pending.get("created_at", 0)) > 1800:
        raise MalError("OAuth session timed out (30 min) — start again.")

    tokens = _exchange_code(cfg, code, pending["code_verifier"])
    pending_path.unlink(missing_ok=True)

    try:
        profile = _api_get(cfg, tokens.access_token, "/users/@me?fields=anime_statistics")
        tokens.username = profile.get("name")
    except MalError:
        tokens.username = None

    save_tokens(uid, tokens)
    return tokens


def extract_oauth_code(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise MalError("Authorization code is empty.")
    if "code=" in text:
        parsed = urlparse(text)
        values = parse_qs(parsed.query).get("code") or []
        if values:
            return values[0]
    if "?" in text and "code=" in text:
        _, query = text.split("?", 1)
        values = parse_qs(query).get("code") or []
        if values:
            return values[0]
    return text


def _new_code_verifier() -> str:
    code_verifier = secrets.token_urlsafe(96)[:128]
    if len(code_verifier) < 43:
        code_verifier = code_verifier + ("x" * (43 - len(code_verifier)))
    return code_verifier


def _assert_pending_user(pending: dict[str, Any], user_id: str) -> None:
    pending_uid = str(pending.get("user_id") or "").strip()
    if not pending_uid or pending_uid != user_id:
        raise MalError(
            "OAuth session belongs to a different user — log in as that user and try again."
        )


def complete_oauth(cfg: MalConfig, code: str, state: str, user_id: str) -> MalTokens:
    uid = _normalize_user_id(user_id)
    pending_path = pending_oauth_path(uid)
    if not pending_path.exists():
        raise MalError("OAuth session expired — try connecting again.")
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    _assert_pending_user(pending, uid)
    if pending.get("state") != state:
        raise MalError("OAuth state mismatch.")
    if time.time() - float(pending.get("created_at", 0)) > 1800:
        raise MalError("OAuth session timed out.")

    tokens = _exchange_code(cfg, code, pending["code_verifier"])
    pending_path.unlink(missing_ok=True)

    try:
        profile = _api_get(cfg, tokens.access_token, "/users/@me?fields=anime_statistics")
        tokens.username = profile.get("name")
    except MalError:
        tokens.username = None

    save_tokens(uid, tokens)
    return tokens


def get_valid_access_token(cfg: MalConfig, user_id: str) -> str:
    tokens = load_tokens(user_id)
    if not tokens:
        raise MalError("Not connected to MyAnimeList.")
    if not tokens.expired:
        return tokens.access_token
    refreshed = _refresh_tokens(cfg, tokens.refresh_token, user_id)
    save_tokens(user_id, refreshed)
    return refreshed.access_token


def sync_animelist_to_catalog(
    cfg: MalConfig,
    catalog_path: Path | None = None,
    *,
    user_id: str,
    enrich: bool = True,
) -> int:
    """Fetch MAL animelist and upsert into the shared catalog.

    Adds missing titles and updates metadata for shows on this user's list.
    Never deletes catalog entries or clears folder/enabled for titles absent
    from this sync (other users' / library titles must remain).
    """
    access_token = get_valid_access_token(cfg, user_id)
    entries = fetch_animelist(access_token)
    write_anime_list_state_from_entries(user_id, entries)
    _write_cache(entries)

    state = load_catalog(catalog_path)

    for item in entries:
        entry_id = f"mal-{item.mal_id}"
        previous = state.get(entry_id)
        entry = CatalogEntry(
            id=entry_id,
            enabled=previous.enabled if previous is not None else True,
            source="mal",
            folder=previous.folder if previous else None,
            jellyfin_id=previous.jellyfin_id if previous else None,
            anilist_id=previous.anilist_id if previous else None,
            mal_id=item.mal_id,
            title=item.title,
            added_at=previous.added_at if previous else None,
        )
        state = upsert_entry(state, entry)

    save_catalog(state, catalog_path)
    record_last_sync(len(entries), user_id)
    if enrich:
        try:
            enrich_catalog_mal_details(
                cfg, catalog_path, user_id=user_id, limit=ENRICH_BATCH_SIZE
            )
        except (MalError, TimeoutError, OSError, URLError):
            pass
    return len(entries)


def sync_mangalist_to_catalog(
    cfg: MalConfig,
    *,
    user_id: str,
    manga_catalog_path: Path | None = None,
    manga_media_root: Path | None = None,
) -> int:
    """Fetch MAL mangalist into data/manga/selected.json. Returns count synced.

    MAL (official API) and Jikan only provide series metadata such as
    ``num_chapters`` — there is no per-chapter title list. Chapter names for
    local files come from ComicInfo/filenames, with MangaDex titles filled in
    by Sync (``kostream.mangadex.sync_catalog_chapter_titles``).
    """
    from kostream.manga import MANGA_ROOT
    from kostream.manga_catalog import (
        MangaCatalogEntry,
        MangaCatalogState,
        load_manga_catalog,
        match_local_folder,
        save_manga_catalog,
        upsert_manga_entry,
    )

    access_token = get_valid_access_token(cfg, user_id)
    entries = fetch_mangalist(access_token)
    write_manga_list_state_from_entries(user_id, entries)
    _write_manga_cache(entries)

    media_root = manga_media_root or MANGA_ROOT
    state = load_manga_catalog(manga_catalog_path)
    existing_mal = {t.id: t for t in state.titles if t.source == "mal"}
    state = MangaCatalogState(titles=[t for t in state.titles if t.source != "mal"])

    for item in entries:
        entry_id = f"mal-manga-{item.mal_id}"
        previous = existing_mal.get(entry_id)
        folder = previous.folder if previous else None
        if not folder:
            folder = match_local_folder(media_root, item.title)
        entry = MangaCatalogEntry(
            id=entry_id,
            enabled=previous.enabled if previous is not None else True,
            source="mal",
            folder=folder,
            mal_id=item.mal_id,
            title=item.title,
            media_type=item.media_type or (previous.media_type if previous else None),
            mangadex_id=previous.mangadex_id if previous else None,
            added_at=previous.added_at if previous else None,
        )
        state = upsert_manga_entry(state, entry)

    save_manga_catalog(state, manga_catalog_path)
    return len(entries)


def record_last_sync(synced_count: int, user_id: str) -> str:
    """Persist last successful animelist sync timestamp for this user. Returns ISO string."""
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    path = last_sync_path(user_id)
    atomic_write_json(
        path,
        {"synced_at": stamp, "count": synced_count},
        trailing_newline=False,
    )
    return stamp


def load_last_sync(user_id: str) -> dict[str, Any] | None:
    path = last_sync_path(user_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not data.get("synced_at"):
        return None
    return data


def format_last_sync_label(
    data: dict[str, Any] | None = None,
    *,
    user_id: str | None = None,
) -> str | None:
    """Human-readable last-sync label for the catalog UI."""
    info = data
    if info is None and user_id:
        info = load_last_sync(user_id)
    if not info:
        return None
    raw = str(info["synced_at"])
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        local = stamp.astimezone()
        label = local.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        label = raw
    count = info.get("count")
    if count is not None:
        return f"Last sync: {label} · {count} anime"
    return f"Last sync: {label}"


ENRICH_BATCH_SIZE = 25
# Keep batches modest: Jikan free tier rate-limits hard; long series eat the budget.
EPISODE_TITLE_BATCH_SIZE = 30
ENRICH_REQUEST_TIMEOUT = 12
JIKAN_PAGE_SLEEP = 0.75
JIKAN_SHOW_SLEEP = 1.0
# Keep low so Sync can fall back to MAL HTML without waiting minutes on 504s.
JIKAN_MAX_RETRIES = 2


def enrich_catalog_mal_details(
    cfg: MalConfig,
    catalog_path: Path | None = None,
    *,
    user_id: str,
    limit: int | None = ENRICH_BATCH_SIZE,
    force: bool = False,
    skip_mal_ids: set[int] | frozenset[int] | None = None,
) -> int:
    """Fetch GET /anime/{id} details (relations) for catalog MAL ids missing them."""
    try:
        _resolve_catalog_mal_ids(catalog_path)
    except Exception:
        pass
    catalog = load_catalog(catalog_path)
    mal_ids = {entry.mal_id for entry in catalog.shows if entry.mal_id}
    if skip_mal_ids:
        mal_ids -= {int(x) for x in skip_mal_ids}
    if not mal_ids:
        return 0
    access_token = get_valid_access_token(cfg, user_id)
    return enrich_mal_details(access_token, mal_ids, limit=limit, force=force)


def _episode_title_sync_priority(entry: CatalogEntry) -> tuple[int, int, int]:
    """Prefer linked local folders and shorter series so Sync fills useful titles first."""
    has_folder = 0 if (entry.folder or "").strip() else 1
    cached = load_cached_anime(entry.mal_id) if entry.mal_id else None
    ep_count = int(cached.num_episodes) if cached and cached.num_episodes else 10_000
    return (has_folder, ep_count, int(entry.mal_id or 0))


def sync_catalog_episode_titles(
    catalog_path: Path | None = None,
    *,
    limit: int | None = EPISODE_TITLE_BATCH_SIZE,
    enabled_only: bool = True,
    skip_mal_ids: set[int] | frozenset[int] | None = None,
) -> int:
    """Fetch missing Jikan episode titles into MAL cache for catalog titles.

    Skips ids whose cache is fresh (``episode_titles_need_fetch`` is False).
    Prioritizes folder-linked / shorter shows. Rate-limits between shows.
    Returns how many caches gained titles.
    """
    catalog = load_catalog(catalog_path)
    entries = catalog.enabled if enabled_only else catalog.shows
    skip = {int(x) for x in skip_mal_ids} if skip_mal_ids else set()
    pending_entries = [
        entry
        for entry in entries
        if entry.mal_id
        and int(entry.mal_id) not in skip
        and episode_titles_need_fetch(entry.mal_id)
    ]
    # Dedupe by mal_id, keeping the highest-priority catalog row.
    best: dict[int, CatalogEntry] = {}
    for entry in pending_entries:
        mid = int(entry.mal_id)
        prev = best.get(mid)
        if prev is None or _episode_title_sync_priority(entry) < _episode_title_sync_priority(prev):
            best[mid] = entry
    pending = [
        entry.mal_id
        for entry in sorted(best.values(), key=_episode_title_sync_priority)
    ]
    if limit is not None:
        pending = pending[: max(0, limit)]

    updated = 0
    for mal_id in pending:
        try:
            if ensure_episode_titles(mal_id):
                updated += 1
            time.sleep(JIKAN_SHOW_SLEEP)
        except (TimeoutError, OSError, URLError, HTTPError, ValueError, json.JSONDecodeError):
            continue
    return updated


def _resolve_catalog_mal_ids(catalog_path: Path | None = None) -> int:
    from kostream.anilist import fetch_mal_id

    catalog = load_catalog(catalog_path)
    resolved = 0
    shows: list[CatalogEntry] = []
    for entry in catalog.shows:
        if entry.mal_id or not entry.anilist_id:
            shows.append(entry)
            continue
        try:
            mal_id = fetch_mal_id(entry.anilist_id)
        except Exception:
            mal_id = None
        if mal_id:
            shows.append(
                CatalogEntry(
                    id=entry.id,
                    enabled=entry.enabled,
                    source=entry.source,
                    folder=entry.folder,
                    jellyfin_id=entry.jellyfin_id,
                    anilist_id=entry.anilist_id,
                    mal_id=mal_id,
                    title=entry.title,
                    added_at=entry.added_at,
                )
            )
            resolved += 1
        else:
            shows.append(entry)
    if resolved:
        save_catalog(CatalogState(shows=shows), catalog_path)
    return resolved


def cache_needs_enrichment(mal_id: int) -> bool:
    return _cache_needs_enrichment(mal_id)


def _cache_needs_enrichment(mal_id: int) -> bool:
    path = CACHE_DIR / f"{mal_id}.json"
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return True
    # Older caches were marked enriched before studios were stored — backfill.
    if "studios" not in data:
        return True
    if data.get("details_enriched"):
        return False
    return not (data.get("related_anime") or [])


_enrich_inflight: set[int] = set()
_enrich_lock = threading.Lock()
_episode_title_inflight: set[int] = set()


def episode_titles_need_fetch(mal_id: int) -> bool:
    """True when MAL episode titles are missing or likely stale (airing)."""
    path = CACHE_DIR / f"{mal_id}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    titles = data.get("episode_titles") or {}
    fetched_at = data.get("episode_titles_fetched_at")
    num_episodes = int(data.get("num_episodes") or 0)
    status = data.get("anime_status")
    if data.get("episode_titles_incomplete"):
        return True
    if not titles:
        return not fetched_at
    # Airing growth, or prior page-cap truncations on long airing series.
    if status == "currently_airing" and num_episodes > len(titles):
        return True
    return False


def ensure_episode_titles_async(mal_id: int) -> bool:
    """Background-fetch episode titles. Returns True if work was scheduled."""
    if not episode_titles_need_fetch(mal_id):
        return False
    with _enrich_lock:
        if mal_id in _episode_title_inflight:
            return True
        _episode_title_inflight.add(mal_id)

    def runner() -> None:
        try:
            ensure_episode_titles(mal_id)
        finally:
            with _enrich_lock:
                _episode_title_inflight.discard(mal_id)

    threading.Thread(target=runner, daemon=True, name=f"mal-ep-titles-{mal_id}").start()
    return True


def ensure_episode_titles(mal_id: int, *, force: bool = False) -> bool:
    """Fetch MAL episode titles into cache (Jikan, optional MAL HTML). Returns True if titles written.

    Prefer Jikan. HTML scrape is opt-in via ``KOSTREAM_MAL_HTML_SCRAPE=1`` and soft-fails
    (logs + keeps existing cache / incomplete flag) rather than inventing empty complete data.
    """
    if not force and not episode_titles_need_fetch(mal_id):
        return False
    titles: dict[int, str] = {}
    complete = True
    jikan_failed = False
    try:
        titles, complete = fetch_episode_titles(mal_id)
    except (TimeoutError, OSError, URLError, HTTPError, ValueError, json.JSONDecodeError) as exc:
        titles, complete = {}, False
        jikan_failed = True
        log.warning("Jikan episode titles failed for mal_id=%s: %s", mal_id, exc)

    if not titles and mal_html_scrape_enabled():
        try:
            titles, complete = fetch_episode_titles_from_mal_site(mal_id)
            if titles:
                log.info(
                    "MAL HTML scrape filled %d episode title(s) for mal_id=%s",
                    len(titles),
                    mal_id,
                )
        except (TimeoutError, OSError, URLError, HTTPError, ValueError) as exc:
            log.warning(
                "MAL HTML episode-title scrape failed for mal_id=%s (keeping cache): %s",
                mal_id,
                exc,
            )
            return False
    elif not titles and jikan_failed:
        log.info(
            "Episode titles incomplete for mal_id=%s (Jikan failed; HTML scrape disabled)",
            mal_id,
        )
        return False

    if not titles and not force:
        # Soft-fail: do not mark complete=True with an empty wipe — leave incomplete for retry.
        if jikan_failed:
            return False
        _store_episode_titles(mal_id, {}, complete=False)
        return False
    _store_episode_titles(mal_id, titles, complete=complete)
    return bool(titles)


def mal_html_scrape_enabled() -> bool:
    """Opt-in MAL HTML episode-title scrape when Jikan has nothing. Default off."""
    raw = os.environ.get("KOSTREAM_MAL_HTML_SCRAPE", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _jikan_retry_after_seconds(exc: BaseException, attempt: int) -> float:
    """Backoff for transient Jikan failures (429 / 5xx / timeouts)."""
    if isinstance(exc, HTTPError):
        header = ""
        try:
            header = (exc.headers.get("Retry-After") or "") if exc.headers else ""
        except Exception:
            header = ""
        if header.strip().isdigit():
            return float(header.strip()) + 0.25
        if exc.code == 429:
            return min(60.0, 5.0 * (2 ** attempt))
        if exc.code in (500, 502, 503, 504):
            return min(45.0, 2.0 * (2 ** attempt))
    return min(30.0, 1.5 * (2 ** attempt))


def _jikan_get_json(url: str) -> dict[str, Any]:
    """GET JSON from Jikan with retries on rate limits and gateway errors."""
    last_exc: BaseException | None = None
    for attempt in range(JIKAN_MAX_RETRIES):
        req = Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            last_exc = exc
            if exc.code not in (429, 500, 502, 503, 504) or attempt + 1 >= JIKAN_MAX_RETRIES:
                raise
            time.sleep(_jikan_retry_after_seconds(exc, attempt))
        except (TimeoutError, URLError, OSError) as exc:
            last_exc = exc
            if attempt + 1 >= JIKAN_MAX_RETRIES:
                raise
            time.sleep(_jikan_retry_after_seconds(exc, attempt))
    assert last_exc is not None
    raise last_exc


def fetch_episode_titles(mal_id: int) -> tuple[dict[int, str], bool]:
    """Pull episode titles from MAL episode pages (Jikan API mirror).

    Returns ``(titles, complete)``. ``complete`` is False when a later page failed
    after some titles were collected (caller should mark incomplete so Sync retries).
    """
    titles: dict[int, str] = {}
    page = 1
    # ~100 eps/page → 200 pages covers ~20k; keep sleeps between pages.
    max_pages = 200
    while page <= max_pages:
        url = JIKAN_EPISODES_URL.format(mal_id=mal_id) + f"?page={page}"
        try:
            payload = _jikan_get_json(url)
        except (TimeoutError, OSError, URLError, HTTPError, ValueError, json.JSONDecodeError):
            if titles:
                return titles, False
            raise
        for row in payload.get("data") or []:
            num = row.get("mal_id")
            title = (row.get("title") or "").strip()
            if num is None or not title:
                continue
            titles[int(num)] = title
        pagination = payload.get("pagination") or {}
        if not pagination.get("has_next_page"):
            break
        page += 1
        time.sleep(JIKAN_PAGE_SLEEP)
    return titles, True


def fetch_episode_titles_from_mal_site(mal_id: int) -> tuple[dict[int, str], bool]:
    """Scrape episode titles from MAL's public episode list pages.

    Used when Jikan is down or rate-limited. Pages use ``?offset=`` in steps of 100.
    """
    titles: dict[int, str] = {}
    offset = 0
    max_pages = 50
    for _ in range(max_pages):
        url = MAL_EPISODES_PAGE_URL.format(mal_id=mal_id)
        if offset:
            url = f"{url}?offset={offset}"
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
            method="GET",
        )
        with urlopen(req, timeout=30) as resp:
            page_html = resp.read().decode("utf-8", errors="replace")
        page_hits = 0
        for num_s, raw_title in MAL_EPISODE_TITLE_RE.findall(page_html):
            title = html_lib.unescape(raw_title).strip()
            if not title:
                continue
            titles[int(num_s)] = title
            page_hits += 1
        if page_hits == 0:
            break
        # MAL lists ~100 episodes per offset page.
        if page_hits < 100:
            return titles, True
        offset += 100
        time.sleep(0.5)
    return titles, bool(titles)


def _store_episode_titles(
    mal_id: int,
    titles: dict[int, str],
    *,
    complete: bool = True,
) -> None:
    path = CACHE_DIR / f"{mal_id}.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return
    # Merge so a partial refetch does not wipe earlier episode names.
    existing = _episode_titles_from_cache(data.get("episode_titles") or {})
    existing.update(titles)
    data["episode_titles"] = {str(k): v for k, v in sorted(existing.items())}
    for key in ANIME_LIST_FIELD_KEYS:
        data.pop(key, None)
    if complete:
        data["episode_titles_fetched_at"] = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        data.pop("episode_titles_incomplete", None)
    else:
        data["episode_titles_incomplete"] = True
        # Leave fetched_at unset/uncleared so need_fetch stays true via incomplete flag.
    atomic_write_json(path, data, ensure_ascii=False, trailing_newline=False)


def ensure_anime_details_async(cfg: MalConfig, mal_id: int, user_id: str) -> bool:
    """Start background enrich if needed. Returns True if work was scheduled."""
    if not cache_needs_enrichment(mal_id):
        return False
    with _enrich_lock:
        if mal_id in _enrich_inflight:
            return True
        _enrich_inflight.add(mal_id)

    def runner() -> None:
        try:
            ensure_anime_details(cfg, mal_id, user_id)
        finally:
            with _enrich_lock:
                _enrich_inflight.discard(mal_id)

    threading.Thread(target=runner, daemon=True, name=f"mal-enrich-{mal_id}").start()
    return True


def ensure_anime_details(cfg: MalConfig, mal_id: int, user_id: str) -> MalAnimeEntry | None:
    """Fetch related_anime for one title if missing. Used on show page load."""
    cached = load_cached_anime(mal_id)
    if cached and not _cache_needs_enrichment(mal_id):
        ensure_episode_titles(mal_id)
        return load_cached_anime(mal_id) or cached
    try:
        access_token = get_valid_access_token(cfg, user_id)
        merge_anime_details_into_cache(access_token, mal_id)
        ensure_episode_titles(mal_id)
        return load_cached_anime(mal_id)
    except (MalError, TimeoutError, OSError, URLError):
        ensure_episode_titles(mal_id)
        return load_cached_anime(mal_id) or cached


def enrich_mal_details(
    access_token: str,
    mal_ids: set[int] | list[int],
    *,
    limit: int | None = ENRICH_BATCH_SIZE,
    force: bool = False,
) -> int:
    """Enrich cache with related_anime. Skips already-enriched ids unless force=True."""
    pending = sorted(mal_ids if force else (mid for mid in mal_ids if _cache_needs_enrichment(mid)))
    if limit is not None:
        pending = pending[: max(0, limit)]

    enriched = 0
    for mal_id in pending:
        try:
            merge_anime_details_into_cache(access_token, mal_id)
            ensure_episode_titles(mal_id)
            enriched += 1
            time.sleep(0.15)
        except (MalError, TimeoutError, OSError, URLError):
            continue

    # Episode titles for already-enriched ids use their own budget so a full
    # relation batch does not starve title sync (see sync_catalog_episode_titles).
    title_pending = [
        mid
        for mid in sorted(mal_ids)
        if mid not in pending and episode_titles_need_fetch(mid)
    ]
    title_limit = EPISODE_TITLE_BATCH_SIZE if limit is not None else None
    if title_limit is not None:
        title_pending = title_pending[: max(0, title_limit)]
    for mal_id in title_pending:
        try:
            if ensure_episode_titles(mal_id):
                enriched += 1
            time.sleep(JIKAN_SHOW_SLEEP)
        except (MalError, TimeoutError, OSError, URLError):
            continue
    return enriched


def merge_anime_details_into_cache(access_token: str, mal_id: int, title_fallback: str | None = None) -> MalAnimeEntry:
    payload = _api_get_raw(
        access_token,
        f"/anime/{mal_id}?fields={ANIME_DETAIL_FIELDS}",
        timeout=ENRICH_REQUEST_TIMEOUT,
    )
    node = payload if payload.get("id") else payload.get("data") or payload
    if not node.get("id"):
        raise MalError(f"No anime details returned for MAL id {mal_id}")

    existing = load_cached_anime(mal_id)
    picture = node.get("main_picture") or {}
    genres = [g.get("name", "") for g in (node.get("genres") or []) if g.get("name")]
    studios = _parse_studio_names(node) or (list(existing.studios) if existing else [])
    related = _parse_related_anime(node)
    day, btime = _parse_broadcast(node)
    if day is None and existing:
        day = existing.broadcast_day
        btime = existing.broadcast_time

    media_type = node.get("media_type") or (existing.media_type if existing else None)
    release_year = parse_mal_start_year(node) or (existing.release_year if existing else None)
    title_en, title_ja, title_ger, title_synonyms = _parse_alternative_titles(node)
    # List fields are personal overlays — details enrich only updates shared metadata.
    entry = MalAnimeEntry(
        mal_id=mal_id,
        title=str(node.get("title") or (existing.title if existing else title_fallback or f"Anime {mal_id}")),
        synopsis=(node.get("synopsis") or (existing.synopsis if existing else "")).strip(),
        poster_url=(
            picture.get("large")
            or picture.get("medium")
            or (existing.poster_url if existing else None)
        ),
        genres=genres[:5] or (existing.genres if existing else []),
        num_episodes=int(node.get("num_episodes") or (existing.num_episodes if existing else 0)),
        list_status="plan_to_watch",
        num_episodes_watched=0,
        anime_status=node.get("status") or (existing.anime_status if existing else None),
        score=0,
        mean_score=node.get("mean") if node.get("mean") is not None else (existing.mean_score if existing else None),
        related_anime=related,
        broadcast_day=day,
        broadcast_time=btime,
        media_type=str(media_type) if media_type else None,
        release_year=release_year,
        studios=studios,
        title_en=title_en or (existing.title_en if existing else None),
        title_ja=title_ja or (existing.title_ja if existing else None),
        title_ger=title_ger or (existing.title_ger if existing else None),
        title_synonyms=title_synonyms or (list(existing.title_synonyms) if existing else []),
    )
    write_cached_anime(entry, preserve_relations=False)
    # Always mark as enriched after a successful details fetch (even if no relations).
    path = CACHE_DIR / f"{mal_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data["details_enriched"] = True
        data["related_anime"] = [
            {"mal_id": rel.mal_id, "title": rel.title, "relation_type": rel.relation_type}
            for rel in related
        ]
        atomic_write_json(path, data, ensure_ascii=False, trailing_newline=False)
    return entry


def update_episodes_watched(
    cfg: MalConfig,
    mal_id: int,
    num_watched: int,
    status: str | None = None,
    *,
    user_id: str,
) -> None:
    """Push local watch progress to MAL (PATCH my_list_status).

    Never decreases MAL progress: the value sent is at least the overlay remote count.
    """
    access_token = get_valid_access_token(cfg, user_id)
    row = get_anime_list_row(user_id, mal_id) or {}
    floor = int(row.get("num_episodes_watched") or 0)
    num_watched = max(0, int(num_watched), floor)
    form: dict[str, str] = {"num_watched_episodes": str(num_watched)}
    if status:
        form["status"] = status
    try:
        _api_form_raw(access_token, f"/anime/{mal_id}/my_list_status", form, method="PATCH")
    except MalError as exc:
        if "404" not in str(exc):
            raise
        put_form = {"status": status or "watching", "num_watched_episodes": str(num_watched)}
        _api_form_raw(access_token, f"/anime/{mal_id}/my_list_status", put_form, method="PUT")

    upsert_anime_list_row(
        user_id,
        mal_id,
        list_status=status or row.get("list_status") or "watching",
        num_episodes_watched=num_watched,
        score=int(row.get("score") or 0) if "score" in row else None,
    )


def update_anime_list_status(
    cfg: MalConfig,
    mal_id: int,
    status: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    """Set MAL anime list status via PATCH/PUT my_list_status; update per-user overlay."""
    status = str(status or "").strip()
    if status not in ANIME_LIST_STATUSES:
        raise MalError(f"Invalid list status: {status}")
    access_token = get_valid_access_token(cfg, user_id)
    row = get_anime_list_row(user_id, mal_id) or {}
    form: dict[str, str] = {"status": status}
    try:
        _api_form_raw(access_token, f"/anime/{mal_id}/my_list_status", form, method="PATCH")
    except MalError as exc:
        if "404" not in str(exc):
            raise
        put_form: dict[str, str] = {"status": status}
        if "num_episodes_watched" in row:
            put_form["num_watched_episodes"] = str(int(row.get("num_episodes_watched") or 0))
        _api_form_raw(access_token, f"/anime/{mal_id}/my_list_status", put_form, method="PUT")

    return upsert_anime_list_row(
        user_id,
        mal_id,
        list_status=status,
        num_episodes_watched=int(row["num_episodes_watched"])
        if "num_episodes_watched" in row
        else None,
        score=int(row["score"]) if "score" in row else None,
    )


def update_anime_list_score(
    cfg: MalConfig,
    mal_id: int,
    score: int,
    *,
    user_id: str,
) -> dict[str, Any]:
    """Set MAL anime score (0 = unset, 1–10) via PATCH/PUT; update per-user overlay."""
    score = int(score)
    if score < 0 or score > 10:
        raise MalError(f"Invalid score: {score}")
    access_token = get_valid_access_token(cfg, user_id)
    row = get_anime_list_row(user_id, mal_id) or {}
    form: dict[str, str] = {"score": str(score)}
    try:
        _api_form_raw(access_token, f"/anime/{mal_id}/my_list_status", form, method="PATCH")
    except MalError as exc:
        if "404" not in str(exc):
            raise
        put_form: dict[str, str] = {
            "status": str(row.get("list_status") or "plan_to_watch"),
            "score": str(score),
        }
        if "num_episodes_watched" in row:
            put_form["num_watched_episodes"] = str(int(row.get("num_episodes_watched") or 0))
        _api_form_raw(access_token, f"/anime/{mal_id}/my_list_status", put_form, method="PUT")

    return upsert_anime_list_row(
        user_id,
        mal_id,
        list_status=str(row["list_status"]) if row.get("list_status") else None,
        num_episodes_watched=int(row["num_episodes_watched"])
        if "num_episodes_watched" in row
        else None,
        score=score,
    )


def update_chapters_read(
    cfg: MalConfig,
    mal_id: int,
    num_chapters_read: int,
    status: str | None = None,
    *,
    user_id: str,
) -> None:
    """Push manga chapter progress to MAL (PATCH my_list_status).

    Never decreases MAL chapter progress relative to the per-user overlay floor.
    """
    access_token = get_valid_access_token(cfg, user_id)
    row = get_manga_list_row(user_id, mal_id) or {}
    floor = int(row.get("num_chapters_read") or 0)
    num_chapters_read = max(0, int(num_chapters_read), floor)
    form: dict[str, str] = {"num_chapters_read": str(num_chapters_read)}
    if status:
        form["status"] = status
    try:
        _api_form_raw(access_token, f"/manga/{mal_id}/my_list_status", form, method="PATCH")
    except MalError as exc:
        if "404" not in str(exc):
            raise
        put_form = {
            "status": status or "reading",
            "num_chapters_read": str(num_chapters_read),
        }
        _api_form_raw(access_token, f"/manga/{mal_id}/my_list_status", put_form, method="PUT")

    upsert_manga_list_row(
        user_id,
        mal_id,
        list_status=status or row.get("list_status") or "reading",
        num_chapters_read=num_chapters_read,
        num_volumes_read=int(row["num_volumes_read"]) if "num_volumes_read" in row else None,
        score=int(row["score"]) if "score" in row else None,
    )


def write_cached_anime(entry: MalAnimeEntry, *, preserve_relations: bool = True) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    related = list(entry.related_anime)
    details_enriched = False
    broadcast_day = entry.broadcast_day
    broadcast_time = entry.broadcast_time
    episode_titles = dict(entry.episode_titles)
    media_type = entry.media_type
    release_year = entry.release_year
    studios = list(entry.studios or [])
    existing_path = CACHE_DIR / f"{entry.mal_id}.json"
    if existing_path.exists():
        try:
            old = json.loads(existing_path.read_text(encoding="utf-8"))
            details_enriched = bool(old.get("details_enriched"))
            if preserve_relations and not related and old.get("related_anime"):
                related = _related_anime_from_cache(old.get("related_anime") or [])
            if not broadcast_day and old.get("broadcast_day"):
                broadcast_day = old.get("broadcast_day")
                broadcast_time = old.get("broadcast_time")
            if not episode_titles and old.get("episode_titles"):
                episode_titles = _episode_titles_from_cache(old.get("episode_titles") or {})
            if not media_type and old.get("media_type"):
                media_type = old.get("media_type")
            if release_year is None and old.get("release_year"):
                release_year = old.get("release_year")
            if not studios and old.get("studios") is not None:
                studios = _parse_studio_names(old)
            if not entry.title_en and not entry.title_ja and not entry.title_synonyms:
                old_en, old_ja, old_ger, old_syn = _parse_alternative_titles(old)
                if old_en or old_ja or old_ger or old_syn:
                    entry.title_en = entry.title_en or old_en
                    entry.title_ja = entry.title_ja or old_ja
                    entry.title_ger = entry.title_ger or old_ger
                    if not entry.title_synonyms:
                        entry.title_synonyms = list(old_syn)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    if related:
        details_enriched = True
    # Shared cache is metadata-only — personal list fields live in per-user overlay.
    payload = {
        "mal_id": entry.mal_id,
        "title": entry.title,
        "synopsis": entry.synopsis,
        "poster_url": entry.poster_url,
        "genres": entry.genres,
        "studios": studios,
        "num_episodes": entry.num_episodes,
        "anime_status": entry.anime_status,
        "mean_score": entry.mean_score,
        "broadcast_day": broadcast_day,
        "broadcast_time": broadcast_time,
        "media_type": media_type,
        "release_year": release_year,
        "related_anime": [
            {"mal_id": rel.mal_id, "title": rel.title, "relation_type": rel.relation_type}
            for rel in related
        ],
        "details_enriched": details_enriched,
        "episode_titles": {str(k): v for k, v in sorted(episode_titles.items())},
        "title_en": entry.title_en,
        "title_ja": entry.title_ja,
        "title_ger": entry.title_ger,
        "title_synonyms": list(entry.title_synonyms or []),
    }
    if existing_path.exists():
        try:
            old = json.loads(existing_path.read_text(encoding="utf-8"))
            if old.get("episode_titles_fetched_at"):
                payload["episode_titles_fetched_at"] = old["episode_titles_fetched_at"]
            if old.get("episode_titles_incomplete") and not episode_titles:
                payload["episode_titles_incomplete"] = True
            elif old.get("episode_titles_incomplete") and episode_titles:
                # Titles preserved from cache; keep incomplete until a full Jikan pass.
                payload["episode_titles_incomplete"] = True
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    atomic_write_json(existing_path, payload, ensure_ascii=False, trailing_newline=False)


def fetch_animelist(access_token: str) -> list[MalAnimeEntry]:
    results: list[MalAnimeEntry] = []
    offset = 0
    limit = 100

    while True:
        path = (
            f"/users/@me/animelist?fields={ANIMELIST_FIELDS}"
            f"&limit={limit}&offset={offset}&nsfw=true"
        )
        payload = _api_get_raw(access_token, path)
        batch = payload.get("data") or []
        for row in batch:
            parsed = _parse_animelist_row(row)
            if parsed:
                results.append(parsed)
        paging = payload.get("paging") or {}
        if not paging.get("next"):
            break
        offset += limit

    return results


def fetch_mangalist(access_token: str) -> list[MalMangaEntry]:
    results: list[MalMangaEntry] = []
    offset = 0
    limit = 100

    while True:
        path = (
            f"/users/@me/mangalist?fields={MANGALIST_FIELDS}"
            f"&limit={limit}&offset={offset}&nsfw=true"
        )
        payload = _api_get_raw(access_token, path)
        batch = payload.get("data") or []
        for row in batch:
            parsed = _parse_mangalist_row(row)
            if parsed:
                results.append(parsed)
        paging = payload.get("paging") or {}
        if not paging.get("next"):
            break
        offset += limit

    return results


def load_cached_manga(mal_id: int) -> MalMangaEntry | None:
    path = MANGA_CACHE_DIR / f"{mal_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    title_en, title_ja, title_ger, title_synonyms = _parse_alternative_titles(data)
    return MalMangaEntry(
        mal_id=int(data["mal_id"]),
        title=data["title"],
        synopsis=data.get("synopsis", ""),
        poster_url=data.get("poster_url"),
        genres=data.get("genres", []),
        num_volumes=int(data.get("num_volumes", 0)),
        num_chapters=int(data.get("num_chapters", 0)),
        # Personal list fields come from per-user overlay (defaults here).
        list_status="plan_to_read",
        num_volumes_read=0,
        num_chapters_read=0,
        manga_status=data.get("manga_status"),
        score=0,
        mean_score=data.get("mean_score"),
        media_type=(data.get("media_type") or None),
        release_year=data.get("release_year"),
        title_en=title_en,
        title_ja=title_ja,
        title_ger=title_ger,
        title_synonyms=title_synonyms,
    )


def _write_manga_cache(entries: list[MalMangaEntry]) -> None:
    MANGA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for item in entries:
        write_cached_manga(item)


def write_cached_manga(entry: MalMangaEntry) -> None:
    MANGA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = MANGA_CACHE_DIR / f"{entry.mal_id}.json"
    release_year = entry.release_year
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if release_year is None and old.get("release_year"):
                release_year = old.get("release_year")
            if not entry.title_en and not entry.title_ja and not entry.title_synonyms:
                old_en, old_ja, old_ger, old_syn = _parse_alternative_titles(old)
                entry.title_en = entry.title_en or old_en
                entry.title_ja = entry.title_ja or old_ja
                entry.title_ger = entry.title_ger or old_ger
                if not entry.title_synonyms:
                    entry.title_synonyms = list(old_syn)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    payload = {
        "mal_id": entry.mal_id,
        "title": entry.title,
        "synopsis": entry.synopsis,
        "poster_url": entry.poster_url,
        "genres": entry.genres,
        "num_volumes": entry.num_volumes,
        "num_chapters": entry.num_chapters,
        "manga_status": entry.manga_status,
        "mean_score": entry.mean_score,
        "media_type": entry.media_type,
        "release_year": release_year,
        "title_en": entry.title_en,
        "title_ja": entry.title_ja,
        "title_ger": entry.title_ger,
        "title_synonyms": list(entry.title_synonyms or []),
    }
    atomic_write_json(path, payload, ensure_ascii=False, trailing_newline=False)


def _parse_mangalist_row(row: dict[str, Any]) -> MalMangaEntry | None:
    node = row.get("node") or {}
    mal_id = node.get("id")
    title = node.get("title")
    if not mal_id or not title:
        return None
    picture = node.get("main_picture") or {}
    genres = [g.get("name", "") for g in (node.get("genres") or []) if g.get("name")]
    list_status = row.get("list_status") or {}
    media_type = node.get("media_type")
    title_en, title_ja, title_ger, title_synonyms = _parse_alternative_titles(node)
    return MalMangaEntry(
        mal_id=int(mal_id),
        title=str(title),
        synopsis=(node.get("synopsis") or "").strip(),
        poster_url=picture.get("large") or picture.get("medium"),
        genres=genres[:5],
        num_volumes=int(node.get("num_volumes") or 0),
        num_chapters=int(node.get("num_chapters") or 0),
        list_status=str(list_status.get("status") or "plan_to_read"),
        num_volumes_read=int(list_status.get("num_volumes_read") or 0),
        num_chapters_read=int(list_status.get("num_chapters_read") or 0),
        manga_status=node.get("status"),
        score=int(list_status.get("score") or 0),
        mean_score=node.get("mean"),
        media_type=str(media_type) if media_type else None,
        release_year=parse_mal_start_year(node),
        title_en=title_en,
        title_ja=title_ja,
        title_ger=title_ger,
        title_synonyms=title_synonyms,
    )


def prefer_large_mal_picture_url(url: str | None) -> str | None:
    """Upgrade MAL CDN picture URLs from tiny/medium to the large variant.

    MAL serves ``…/123.jpg`` (medium), ``…/123t.jpg`` (tiny), ``…/123l.jpg`` (large).
    Leaves non-MAL URLs unchanged.
    """
    if not url:
        return None
    text = str(url).strip()
    if "myanimelist.net/images/" not in text:
        return text
    if re.search(r"l\.(?:jpe?g|webp|png)(?:\?|$)", text, re.IGNORECASE):
        return text
    tiny = re.sub(
        r"t\.(jpe?g|webp|png)(\?.*)?$",
        r"l.\1\2",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    if tiny != text:
        return tiny
    return re.sub(
        r"(\d+)\.(jpe?g|webp|png)(\?.*)?$",
        r"\1l.\2\3",
        text,
        count=1,
        flags=re.IGNORECASE,
    )


def load_cached_anime(mal_id: int) -> MalAnimeEntry | None:
    path = CACHE_DIR / f"{mal_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    title_en, title_ja, title_ger, title_synonyms = _parse_alternative_titles(data)
    return MalAnimeEntry(
        mal_id=int(data["mal_id"]),
        title=data["title"],
        synopsis=data.get("synopsis", ""),
        poster_url=data.get("poster_url"),
        genres=data.get("genres", []),
        num_episodes=int(data.get("num_episodes", 0)),
        # Personal list fields come from per-user overlay (defaults here).
        list_status="plan_to_watch",
        num_episodes_watched=0,
        anime_status=data.get("anime_status"),
        score=0,
        mean_score=data.get("mean_score"),
        related_anime=_related_anime_from_cache(data.get("related_anime") or []),
        broadcast_day=data.get("broadcast_day"),
        broadcast_time=data.get("broadcast_time"),
        episode_titles=_episode_titles_from_cache(data.get("episode_titles") or {}),
        media_type=(data.get("media_type") or None),
        release_year=data.get("release_year"),
        studios=_parse_studio_names(data),
        title_en=title_en,
        title_ja=title_ja,
        title_ger=title_ger,
        title_synonyms=title_synonyms,
    )


def _episode_titles_from_cache(raw: dict[str, Any] | list) -> dict[int, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[int, str] = {}
    for key, value in raw.items():
        try:
            num = int(key)
        except (TypeError, ValueError):
            continue
        title = str(value or "").strip()
        if title:
            out[num] = title
    return out


def _write_cache(entries: list[MalAnimeEntry]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for item in entries:
        write_cached_anime(item)


def _parse_animelist_row(row: dict[str, Any]) -> MalAnimeEntry | None:
    node = row.get("node") or {}
    mal_id = node.get("id")
    title = node.get("title")
    if not mal_id or not title:
        return None

    picture = node.get("main_picture") or {}
    genres = [g.get("name", "") for g in (node.get("genres") or []) if g.get("name")]
    list_status = row.get("list_status") or {}
    day, btime = _parse_broadcast(node)
    media_type = node.get("media_type")

    title_en, title_ja, title_ger, title_synonyms = _parse_alternative_titles(node)
    return MalAnimeEntry(
        mal_id=int(mal_id),
        title=str(title),
        synopsis=(node.get("synopsis") or "").strip(),
        poster_url=picture.get("large") or picture.get("medium"),
        genres=genres[:5],
        num_episodes=int(node.get("num_episodes") or 0),
        list_status=str(list_status.get("status") or "plan_to_watch"),
        num_episodes_watched=int(list_status.get("num_episodes_watched") or 0),
        anime_status=node.get("status"),
        score=int(list_status.get("score") or 0),
        mean_score=node.get("mean"),
        related_anime=[],
        broadcast_day=day,
        broadcast_time=btime,
        media_type=str(media_type) if media_type else None,
        release_year=parse_mal_start_year(node),
        studios=_parse_studio_names(node),
        title_en=title_en,
        title_ja=title_ja,
        title_ger=title_ger,
        title_synonyms=title_synonyms,
    )


def _parse_broadcast(node: dict[str, Any]) -> tuple[str | None, str | None]:
    raw = node.get("broadcast")
    if not isinstance(raw, dict):
        return None, None
    day = (raw.get("day_of_the_week") or "").strip().lower() or None
    start = (raw.get("start_time") or "").strip() or None
    if day and day not in {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }:
        day = None
    if start and len(start) >= 4 and ":" in start:
        start = start[:5]
    else:
        start = None
    return day, start


def _parse_related_anime(node: dict[str, Any]) -> list[RelatedAnime]:
    related: list[RelatedAnime] = []
    for item in node.get("related_anime") or []:
        rel_node = item.get("node") or {}
        mal_id = rel_node.get("id")
        title = rel_node.get("title")
        relation_type = item.get("relation_type")
        if mal_id and title and relation_type:
            related.append(
                RelatedAnime(
                    mal_id=int(mal_id),
                    title=str(title),
                    relation_type=str(relation_type),
                )
            )
    return related


def _related_anime_from_cache(items: list[dict[str, Any]]) -> list[RelatedAnime]:
    related: list[RelatedAnime] = []
    for item in items:
        mal_id = item.get("mal_id")
        title = item.get("title")
        relation_type = item.get("relation_type")
        if mal_id and title and relation_type:
            related.append(
                RelatedAnime(
                    mal_id=int(mal_id),
                    title=str(title),
                    relation_type=str(relation_type),
                )
            )
    return related


def _exchange_code(cfg: MalConfig, code: str, code_verifier: str) -> MalTokens:
    # MAL Scheme 1: HTTP Basic auth — client_secret must NOT be in the body.
    body = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg.redirect_uri,
            "code_verifier": code_verifier,
        }
    ).encode("utf-8")
    payload = _token_request(cfg, body)
    return _tokens_from_payload(payload)


def _refresh_tokens(cfg: MalConfig, refresh_token: str, user_id: str) -> MalTokens:
    body = urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")
    payload = _token_request(cfg, body)
    tokens = _tokens_from_payload(payload)
    old = load_tokens(user_id)
    if old and old.username:
        tokens.username = old.username
    return tokens


def _tokens_from_payload(payload: dict[str, Any]) -> MalTokens:
    expires_in = int(payload.get("expires_in", 3600))
    return MalTokens(
        access_token=str(payload["access_token"]),
        refresh_token=str(payload["refresh_token"]),
        expires_at=time.time() + expires_in,
    )


def _token_request(cfg: MalConfig, body: bytes) -> dict[str, Any]:
    auth = base64.b64encode(f"{cfg.client_id}:{cfg.client_secret}".encode()).decode()
    req = Request(
        MAL_TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth}",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        if exc.code == 401 and "invalid_client" in detail:
            raise MalError(
                "Client authentication failed — check MAL_CLIENT_ID (32 chars, no spaces) "
                "and MAL_CLIENT_SECRET match myanimelist.net/apiconfig exactly."
            ) from exc
        raise MalError(f"Token request failed ({exc.code}): {detail}") from exc


def _api_get(cfg: MalConfig, access_token: str, path: str) -> dict[str, Any]:
    return _api_get_raw(access_token, path)


def _api_get_raw(access_token: str, path: str, timeout: float = 30) -> dict[str, Any]:
    url = f"{MAL_API_URL}{path}"
    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except TimeoutError as exc:
        raise MalError(f"MAL API timeout for {path}") from exc
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise MalError(f"MAL API error ({exc.code}): {detail}") from exc


def _api_form_raw(access_token: str, path: str, form: dict[str, str], method: str = "PATCH") -> None:
    url = f"{MAL_API_URL}{path}"
    body = urlencode(form).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
        method=method,
    )
    try:
        with urlopen(req, timeout=30) as resp:
            resp.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise MalError(f"MAL API error ({exc.code}): {detail}") from exc
