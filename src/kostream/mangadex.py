"""MangaDex chapter-title metadata for local manga chapters.

Sync resolves a MangaDex UUID from MAL id (title search + ``links.mal``),
fetches the chapter feed (titles only — no images), and caches
``{chapter_number: title}`` under ``data/mangadex/``. Overlay onto local
chapters happens in ``kostream.manga`` (prefer ComicInfo/filename when
meaningful).

API: https://api.mangadex.org/docs/ — credit MangaDex; ~5 req/s.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MANGADEX_API = "https://api.mangadex.org"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "mangadex"
ID_MAP_FILE = DATA_DIR / "id_map.json"
CHAPTERS_DIR = DATA_DIR / "chapters"
USER_AGENT = (
    "Ko-Stream/0.2 (+https://github.com/KosovarM/Ko-Stream; "
    "MangaDex chapter metadata only)"
)
REQUEST_SLEEP = 0.2
REQUEST_TIMEOUT = 25
# Series processed per "Sync chapter titles" run (raise so one pass covers more).
CHAPTER_TITLE_BATCH_SIZE = 150
# English titles only — no es-la / pt-br / ja / other-lang gap fill.
FEED_LANGUAGES = ("en",)
FEED_PAGE_LIMIT = 100
# MangaDex rejects offset + limit > 10000 on /feed.
FEED_OFFSET_CAP = 10000
# Title search pagination when resolving MAL → MangaDex UUID.
SEARCH_PAGE_LIMIT = 100
SEARCH_MAX_PAGES = 5
# Re-try MAL→MDX resolution after a failed search (negative id_map cache).
UNRESOLVED_RETRY_DAYS = 7
# Bump when search/resolution logic changes so stale negative caches retry once.
RESOLUTION_VERSION = 2


class MangaDexError(Exception):
    """MangaDex HTTP or parse failure."""


def feed_languages_key(languages: tuple[str, ...] | None = None) -> str:
    """Stable fingerprint of the language preference used for a cache entry."""
    langs = languages if languages is not None else FEED_LANGUAGES
    return ",".join(langs)


def normalize_chapter_key(value: str | float | int | None) -> str | None:
    """Canonical chapter map key: ``\"1\"``, ``\"7.5\"`` (no leading zeros)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return s
    if not (f == f):  # NaN
        return None
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    # Keep a stable decimal form (7.50 → 7.5).
    text = f"{f:.6f}".rstrip("0").rstrip(".")
    return text or None


def chapter_titles_from_feed_rows(
    rows: list[dict[str, Any]],
    *,
    lang_preference: tuple[str, ...] = FEED_LANGUAGES,
) -> dict[str, str]:
    """Build ``{chapter_key: title}`` from preferred languages only (default: en).

    Empty titles and non-preferred languages are skipped. When the same chapter
    appears multiple times in a preferred language, the first non-empty title wins.
    """
    allowed = {lang.casefold() for lang in lang_preference}
    # Prefer earlier languages in *lang_preference* if more than one is allowed.
    by_lang: dict[str, dict[str, str]] = {lang.casefold(): {} for lang in lang_preference}
    for row in rows:
        attrs = row.get("attributes") or {}
        key = normalize_chapter_key(attrs.get("chapter"))
        if key is None:
            continue
        title = (attrs.get("title") or "").strip()
        if not title:
            continue
        lang = (attrs.get("translatedLanguage") or "").strip().casefold()
        if lang not in allowed:
            continue
        # First title wins per language (feed may have multiple scanlations).
        by_lang[lang].setdefault(key, title)

    merged: dict[str, str] = {}
    for lang in lang_preference:
        for key, title in by_lang[lang.casefold()].items():
            merged.setdefault(key, title)
    return merged


def known_chapter_keys_from_feed_rows(rows: list[dict[str, Any]]) -> list[str]:
    """All chapter numbers seen in the feed (titled or empty), normalized."""
    keys: set[str] = set()
    for row in rows:
        attrs = row.get("attributes") or {}
        key = normalize_chapter_key(attrs.get("chapter"))
        if key is not None:
            keys.add(key)
    return _sorted_chapter_keys(keys)


def _sorted_chapter_keys(keys: set[str] | list[str]) -> list[str]:
    def _sort_key(item: str) -> tuple:
        try:
            return (0, float(item))
        except ValueError:
            return (1, item)

    return sorted(keys, key=_sort_key)


def load_id_map(path: Path | None = None) -> dict[str, Any]:
    file_path = path or ID_MAP_FILE
    if not file_path.exists():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_id_map(mapping: dict[str, Any], path: Path | None = None) -> None:
    file_path = path or ID_MAP_FILE
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(mapping, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_cached_chapter_titles(mal_id: int, *, root: Path | None = None) -> dict[str, str]:
    """Return cached chapter number → title for *mal_id* (empty if missing)."""
    base = root or CHAPTERS_DIR
    path = base / f"{int(mal_id)}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    raw = data.get("titles") or {}
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        key = normalize_chapter_key(k)
        name = (str(v) if v is not None else "").strip()
        if key and name:
            out[key] = name
    return out


def load_cached_known_chapters(mal_id: int, *, root: Path | None = None) -> list[str]:
    """Return sorted known chapter keys from MangaDex cache (may be empty)."""
    base = root or CHAPTERS_DIR
    path = base / f"{int(mal_id)}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    known_raw = data.get("known_chapters") or []
    keys: list[str] = []
    if isinstance(known_raw, list):
        for item in known_raw:
            key = normalize_chapter_key(item)
            if key:
                keys.append(key)
    # Titles keys are also known chapters
    titles = data.get("titles") or {}
    if isinstance(titles, dict):
        for k in titles.keys():
            key = normalize_chapter_key(k)
            if key and key not in keys:
                keys.append(key)
    return _sorted_chapter_keys(keys)


def chapter_titles_need_fetch(
    mal_id: int,
    *,
    root: Path | None = None,
    local_keys: set[str] | frozenset[str] | None = None,
) -> bool:
    """True when chapter-title cache is missing, incomplete, or outdated.

    Retries when:
    - cache file missing / unreadable
    - ``chapter_titles_incomplete`` (HTTP/pagination failure)
    - language preference fingerprint changed (e.g. multi-lang → en-only)
    - schema missing ``known_chapters`` / ``feed_languages`` (one-time migrate)
    - local chapter numbers exist that MDX has never recorded (optional *local_keys*)
    """
    base = root or CHAPTERS_DIR
    path = base / f"{int(mal_id)}.json"
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return True
    if data.get("chapter_titles_incomplete"):
        return True
    if data.get("mangadex_id") is False:
        if unresolved_resolution_due(mal_id):
            return True
        return False

    if data.get("feed_languages") != feed_languages_key():
        return True
    if "known_chapters" not in data:
        return True

    titles = data.get("titles") or {}
    fetched_at = data.get("fetched_at")
    if not titles and not data.get("known_chapters"):
        return not fetched_at

    if local_keys:
        known_raw = data.get("known_chapters") or []
        known: set[str] = set()
        if isinstance(known_raw, list):
            for item in known_raw:
                key = normalize_chapter_key(item)
                if key:
                    known.add(key)
        titled = {
            normalize_chapter_key(k)
            for k in (titles.keys() if isinstance(titles, dict) else [])
            if normalize_chapter_key(k)
        }
        # Only retry for local chapters MangaDex has never listed — new uploads.
        unseen = {k for k in local_keys if k} - known - titled
        if unseen:
            return True

    return False


def _store_chapter_titles(
    mal_id: int,
    titles: dict[str, str],
    *,
    mangadex_id: str | None,
    complete: bool = True,
    known_chapters: list[str] | None = None,
    languages: tuple[str, ...] | None = None,
    root: Path | None = None,
    replace_titles: bool = False,
) -> None:
    """Persist chapter titles.

    When *replace_titles* is True (successful en-only re-fetch), drop previous
    title strings so Spanish/other-lang leftovers cannot linger in the overlay.
    Incomplete/error stores keep *replace_titles* False and merge.
    """
    base = root or CHAPTERS_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{int(mal_id)}.json"
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            existing = {}
    merged: dict[str, str] = {} if replace_titles else dict(existing.get("titles") or {})
    for k, v in titles.items():
        key = normalize_chapter_key(k)
        name = (v or "").strip()
        if key and name:
            merged[key] = name

    known_set: set[str] = set()
    if not replace_titles:
        prev_known = existing.get("known_chapters") or []
        if isinstance(prev_known, list):
            for item in prev_known:
                key = normalize_chapter_key(item)
                if key:
                    known_set.add(key)
    if known_chapters is not None:
        for item in known_chapters:
            key = normalize_chapter_key(item)
            if key:
                known_set.add(key)
    known_set.update(merged.keys())

    payload: dict[str, Any] = {
        "mal_id": int(mal_id),
        "mangadex_id": mangadex_id,
        "fetched_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "feed_languages": feed_languages_key(languages),
        "known_chapters": _sorted_chapter_keys(known_set),
        "titles": {k: merged[k] for k in _sorted_chapter_keys(list(merged.keys()))},
    }
    if complete:
        payload.pop("chapter_titles_incomplete", None)
        existing.pop("chapter_titles_incomplete", None)
    else:
        payload["chapter_titles_incomplete"] = True
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _http_get_json(url: str, *, sleep: float = REQUEST_SLEEP) -> dict[str, Any]:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        raise MangaDexError(f"HTTP {exc.code} for {url}: {body}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise MangaDexError(f"Request failed for {url}: {exc}") from exc
    finally:
        if sleep > 0:
            time.sleep(sleep)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MangaDexError(f"Invalid JSON from {url}") from exc
    if not isinstance(data, dict):
        raise MangaDexError(f"Unexpected JSON from {url}")
    return data


def search_manga_by_title(
    title: str,
    *,
    limit: int = 25,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """``GET /manga`` title search; returns one page of data rows."""
    q = (title or "").strip()
    if not q:
        return []
    params = urllib.parse.urlencode(
        {
            "title": q,
            "limit": max(1, min(limit, 100)),
            "offset": max(0, offset),
        }
    )
    data = _http_get_json(f"{MANGADEX_API}/manga?{params}")
    rows = data.get("data") or []
    return rows if isinstance(rows, list) else []


def search_manga_paginated(
    title: str,
    *,
    limit: int = SEARCH_PAGE_LIMIT,
    max_pages: int = SEARCH_MAX_PAGES,
) -> list[dict[str, Any]]:
    """Walk title-search pages until exhausted or *max_pages* reached."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_limit = max(1, min(limit, 100))
    for page in range(max(1, max_pages)):
        offset = page * page_limit
        batch = search_manga_by_title(title, limit=page_limit, offset=offset)
        if not batch:
            break
        for row in batch:
            uuid = row.get("id")
            if uuid and uuid not in seen:
                seen.add(str(uuid))
                merged.append(row)
        if len(batch) < page_limit:
            break
    return merged


def title_search_queries(title: str) -> list[str]:
    """Build deduped MangaDex title-search strings (exact → normalized → shorter)."""
    raw = (title or "").strip()
    if not raw:
        return []

    queries: list[str] = []

    def add(value: str) -> None:
        text = re.sub(r"\s+", " ", (value or "").strip())
        if text and text not in queries:
            queries.append(text)

    add(raw)
    normalized = re.sub(r"[/:]", " ", raw)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    add(normalized)

    words = normalized.split()
    if len(words) > 5:
        add(" ".join(words[:5]))
    if len(words) > 3:
        add(" ".join(words[:3]))
    if len(words) > 2:
        add(" ".join(words[:2]))

    lower = normalized.casefold()
    if "fate" in lower and "extra" in lower:
        add("Fate Extra")
    if lower.startswith("re:zero") or lower.startswith("re zero"):
        add("Re:Zero")

    return queries


def find_mangadex_id_for_mal(
    mal_id: int,
    title: str,
    *,
    year: int | None = None,
) -> tuple[str | None, str | None]:
    """Search MangaDex with several title variants; return ``(uuid, query_used)``."""
    for query in title_search_queries(title):
        rows = search_manga_paginated(query)
        found = pick_mangadex_id_for_mal(rows, mal_id, year=year)
        if found:
            return found, query
    return None, None


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _id_map_entry(mal_id: int, id_map_path: Path | None = None) -> dict[str, Any] | None:
    mapping = load_id_map(id_map_path)
    cached = mapping.get(str(int(mal_id)))
    return cached if isinstance(cached, dict) else None


def unresolved_resolution_due(
    mal_id: int,
    *,
    id_map_path: Path | None = None,
) -> bool:
    """True when a prior failed MAL→MDX lookup may be retried."""
    entry = _id_map_entry(mal_id, id_map_path)
    if entry is None:
        return True
    if entry.get("mangadex_id") is not False:
        return False
    if int(entry.get("resolution_version") or 1) < RESOLUTION_VERSION:
        return True
    resolved_at = _parse_iso_utc(entry.get("resolved_at"))
    if resolved_at is None:
        return True
    age = datetime.now(timezone.utc) - resolved_at
    return age.days >= UNRESOLVED_RETRY_DAYS


def pick_mangadex_id_for_mal(
    rows: list[dict[str, Any]],
    mal_id: int,
    *,
    year: int | None = None,
) -> str | None:
    """Prefer row whose ``attributes.links.mal`` matches *mal_id*; optional year filter."""
    mal_s = str(int(mal_id))
    mal_matches: list[dict[str, Any]] = []
    for row in rows:
        attrs = row.get("attributes") or {}
        links = attrs.get("links") or {}
        link_mal = links.get("mal") if isinstance(links, dict) else None
        if link_mal is not None and str(link_mal).strip() == mal_s:
            mal_matches.append(row)

    candidates = mal_matches or []
    if year is not None and candidates:
        year_hits = [
            row
            for row in candidates
            if (row.get("attributes") or {}).get("year") == year
        ]
        if year_hits:
            candidates = year_hits

    if not candidates and year is not None:
        # No mal-link hit: try year + first result only when a single year match exists.
        year_hits = [
            row
            for row in rows
            if (row.get("attributes") or {}).get("year") == year
        ]
        if len(year_hits) == 1:
            candidates = year_hits

    if not candidates:
        return None
    uuid = candidates[0].get("id")
    return str(uuid) if uuid else None


def resolve_mangadex_id(
    mal_id: int,
    title: str,
    *,
    mangadex_id: str | None = None,
    year: int | None = None,
    id_map_path: Path | None = None,
    force: bool = False,
) -> str | None:
    """Resolve MangaDex UUID: override → id_map cache → title search + mal link."""
    override = (mangadex_id or "").strip()
    if override:
        mapping = load_id_map(id_map_path)
        mapping[str(int(mal_id))] = {
            "mangadex_id": override,
            "title": title,
            "source": "override",
            "resolution_version": RESOLUTION_VERSION,
            "resolved_at": _now_iso(),
        }
        save_id_map(mapping, id_map_path)
        return override

    mapping = load_id_map(id_map_path)
    cached = mapping.get(str(int(mal_id)))
    if isinstance(cached, str) and cached.strip():
        return cached.strip()
    if isinstance(cached, dict):
        if cached.get("mangadex_id") is False:
            if not force and not unresolved_resolution_due(mal_id, id_map_path=id_map_path):
                return None
        else:
            cid = cached.get("mangadex_id")
            if isinstance(cid, str) and cid.strip():
                return cid.strip()

    found, query_used = find_mangadex_id_for_mal(mal_id, title, year=year)
    mapping[str(int(mal_id))] = {
        "mangadex_id": found if found else False,
        "title": title,
        "source": "search",
        "search_query": query_used,
        "resolution_version": RESOLUTION_VERSION,
        "resolved_at": _now_iso(),
    }
    save_id_map(mapping, id_map_path)
    return found


@dataclass
class ChapterFeedResult:
    """Paginated MangaDex feed rows plus whether pagination finished."""

    rows: list[dict[str, Any]]
    complete: bool = True


def fetch_chapter_feed(
    mangadex_uuid: str,
    *,
    languages: tuple[str, ...] = FEED_LANGUAGES,
) -> ChapterFeedResult:
    """Paginate ``GET /manga/{uuid}/feed`` for preferred languages (metadata only).

    Walks every page until exhausted. Stops early (``complete=False``) only when
    MangaDex's ``offset + limit ≤ 10000`` cap would be exceeded.
    """
    uuid = (mangadex_uuid or "").strip()
    if not uuid:
        return ChapterFeedResult(rows=[], complete=True)
    rows: list[dict[str, Any]] = []
    offset = 0
    complete = True
    while True:
        # Valid feed order keys: chapter, createdAt, updatedAt, publishAt, volume.
        # order[translatedLanguage] is rejected by the API (HTTP 400).
        limit = FEED_PAGE_LIMIT
        if offset + limit > FEED_OFFSET_CAP:
            limit = FEED_OFFSET_CAP - offset
            if limit <= 0:
                complete = False
                break
        params: list[tuple[str, str]] = [
            ("limit", str(limit)),
            ("offset", str(offset)),
            ("order[chapter]", "asc"),
            ("contentRating[]", "safe"),
            ("contentRating[]", "suggestive"),
            ("contentRating[]", "erotica"),
            ("contentRating[]", "pornographic"),
            ("includeFutureUpdates", "0"),
        ]
        for lang in languages:
            params.append(("translatedLanguage[]", lang))
        query = urllib.parse.urlencode(params)
        data = _http_get_json(f"{MANGADEX_API}/manga/{urllib.parse.quote(uuid)}/feed?{query}")
        batch = data.get("data") or []
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        total = int(data.get("total") or 0)
        offset += len(batch)
        if offset >= total or len(batch) < limit:
            break
        if offset >= FEED_OFFSET_CAP:
            complete = False
            break
    return ChapterFeedResult(rows=rows, complete=complete)


def ensure_chapter_titles(
    mal_id: int,
    title: str,
    *,
    mangadex_id: str | None = None,
    year: int | None = None,
    force: bool = False,
    chapters_root: Path | None = None,
    id_map_path: Path | None = None,
    local_keys: set[str] | frozenset[str] | None = None,
) -> bool:
    """Fetch and cache MangaDex chapter titles. Returns True if titles were written."""
    if not force and not chapter_titles_need_fetch(
        mal_id, root=chapters_root, local_keys=local_keys
    ):
        return False

    uuid = resolve_mangadex_id(
        mal_id,
        title,
        mangadex_id=mangadex_id,
        year=year,
        id_map_path=id_map_path,
        force=force,
    )
    if not uuid:
        _store_chapter_titles(
            mal_id,
            {},
            mangadex_id=None,
            complete=True,
            known_chapters=[],
            root=chapters_root,
            replace_titles=True,
        )
        # Mark unresolved so need_fetch stays false (mangadex_id false in file).
        base = chapters_root or CHAPTERS_DIR
        path = base / f"{int(mal_id)}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["mangadex_id"] = False
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return False

    try:
        feed = fetch_chapter_feed(uuid)
        titles = chapter_titles_from_feed_rows(feed.rows)
        known_set = set(known_chapter_keys_from_feed_rows(feed.rows))
        # Mark local chapters as seen so en-only feeds without a title for that
        # number do not re-queue forever after a successful pass.
        if local_keys:
            known_set.update(k for k in local_keys if k)
        _store_chapter_titles(
            mal_id,
            titles,
            mangadex_id=uuid,
            complete=feed.complete,
            known_chapters=_sorted_chapter_keys(known_set),
            root=chapters_root,
            replace_titles=True,
        )
        return bool(titles)
    except MangaDexError:
        _store_chapter_titles(
            mal_id,
            {},
            mangadex_id=uuid,
            complete=False,
            root=chapters_root,
        )
        return False


def _chapter_title_sync_priority(entry: Any, has_folder: bool) -> tuple[int, int]:
    """Prefer folder-linked titles; stable by mal_id."""
    return (0 if has_folder else 1, int(getattr(entry, "mal_id", 0) or 0))


def _local_chapter_keys(title: Any) -> set[str]:
    """Chapter number keys from a scanned local manga title."""
    keys: set[str] = set()
    for ch in getattr(title, "chapters", None) or []:
        stem = getattr(ch, "relative", None) or getattr(ch, "title", None) or ""
        if stem in (".", ""):
            stem = getattr(ch, "title", "") or ""
        from kostream.manga import _chapter_number_from_stem

        num_s = _chapter_number_from_stem(stem)
        key = normalize_chapter_key(num_s) if num_s is not None else None
        if key:
            keys.add(key)
    return keys


@dataclass
class ChapterTitleSyncResult:
    """Outcome of a MangaDex chapter-title sync batch."""

    updated: int = 0
    attempted: int = 0
    unresolved: int = 0
    failed: int = 0
    last_error: str | None = None

    def __int__(self) -> int:
        return self.updated


def sync_catalog_chapter_titles(
    manga_catalog_path: Path | None = None,
    *,
    manga_media_root: Path | None = None,
    limit: int | None = CHAPTER_TITLE_BATCH_SIZE,
    enabled_only: bool = True,
    skip_mal_ids: set[int] | frozenset[int] | None = None,
) -> ChapterTitleSyncResult:
    """Fetch missing MangaDex chapter titles for local manga with a MAL id.

    Only considers catalog entries that have local chapters. Rate-limits via
    HTTP helper sleep. ``updated`` is how many caches gained at least one title.
    """
    from kostream.manga import MANGA_ROOT, scan_manga_library
    from kostream.mal import load_cached_manga
    from kostream.manga_catalog import load_manga_catalog, match_local_folder

    catalog = load_manga_catalog(manga_catalog_path)
    entries = catalog.enabled if enabled_only else catalog.titles
    media_root = manga_media_root or MANGA_ROOT
    local = scan_manga_library(media_root)
    local_by_folder = {t.folder: t for t in local if t.chapters}
    skip = {int(x) for x in skip_mal_ids} if skip_mal_ids else set()

    pending: list[tuple[Any, bool, set[str]]] = []
    seen: set[int] = set()
    for entry in entries:
        mid = entry.mal_id
        if not mid or mid in seen or int(mid) in skip:
            continue
        folder = entry.folder
        local_title = local_by_folder.get(folder) if folder else None
        has_local = local_title is not None
        if not has_local:
            matched = match_local_folder(
                media_root, entry.title or ""
            )
            if matched and matched in local_by_folder:
                has_local = True
                folder = matched
                local_title = local_by_folder[matched]
        if not has_local or local_title is None:
            continue
        local_keys = _local_chapter_keys(local_title)
        retry_unresolved = unresolved_resolution_due(int(mid))
        if not chapter_titles_need_fetch(mid, local_keys=local_keys) and not retry_unresolved:
            continue
        seen.add(int(mid))
        pending.append((entry, True, local_keys, retry_unresolved))

    pending.sort(key=lambda item: _chapter_title_sync_priority(item[0], item[1]))
    if limit is not None:
        pending = pending[: max(0, limit)]

    result = ChapterTitleSyncResult(attempted=len(pending))
    for entry, _, local_keys, retry_unresolved in pending:
        title = (entry.title or entry.folder or "").strip() or f"mal-{entry.mal_id}"
        override = getattr(entry, "mangadex_id", None)
        mid = int(entry.mal_id)
        cached_mal = load_cached_manga(mid)
        year = cached_mal.release_year if cached_mal else None
        force_resolve = retry_unresolved
        try:
            wrote = ensure_chapter_titles(
                mid,
                title,
                mangadex_id=override,
                year=year,
                local_keys=local_keys,
                force=force_resolve,
            )
            if wrote:
                result.updated += 1
            else:
                # Distinguish unresolved MAL→MDX map from feed/HTTP failures.
                path = CHAPTERS_DIR / f"{mid}.json"
                mdx_flag: Any = None
                incomplete = False
                if path.exists():
                    try:
                        meta = json.loads(path.read_text(encoding="utf-8"))
                        mdx_flag = meta.get("mangadex_id")
                        incomplete = bool(meta.get("chapter_titles_incomplete"))
                    except (OSError, json.JSONDecodeError, ValueError):
                        pass
                if mdx_flag is False:
                    result.unresolved += 1
                elif incomplete:
                    result.failed += 1
                    if result.last_error is None:
                        result.last_error = (
                            f"MangaDex feed failed for mal_id={mid}"
                        )
                # else: resolved UUID but no titled chapters on MangaDex
        except (MangaDexError, TimeoutError, OSError, ValueError) as exc:
            result.failed += 1
            result.last_error = str(exc)
            continue
    return result


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
