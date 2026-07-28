"""Local manga library — scan manga root and serve page images (folders + CBZ).

Default root: ``D:\\Media\\Ko-Stream\\manga`` (override with ``KOSTREAM_MANGA_ROOT``).

Chapter display titles prefer local filenames / CBZ ``ComicInfo.xml`` when
meaningful; otherwise Sync-populated MangaDex titles overlay by chapter number
(see ``apply_mangadex_chapter_titles`` / ``kostream.mangadex``).
"""

from __future__ import annotations

import copy
import os
import re
import threading
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

_REPO_MANGA = Path(__file__).resolve().parents[2] / "media" / "manga"
_DEFAULT_MANGA = Path(os.environ.get("KOSTREAM_MANGA_ROOT", r"D:\Media\Ko-Stream\manga"))


def default_manga_root() -> Path:
    """Manga/manhwa library root (env ``KOSTREAM_MANGA_ROOT``)."""
    env = (os.environ.get("KOSTREAM_MANGA_ROOT") or "").strip()
    if env:
        return Path(env)
    if _DEFAULT_MANGA.exists() or _DEFAULT_MANGA.parent.exists():
        return _DEFAULT_MANGA
    return _REPO_MANGA


MANGA_ROOT = default_manga_root()

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"}
CBZ_EXTENSIONS = {".cbz", ".zip"}

# Split on integers *or* decimals so "7.5" sorts as one number (not 7 then 5).
_NAT_SPLIT = re.compile(r"(\d+(?:\.\d+)?)")
_NUM_TOKEN = re.compile(r"^\d+(?:\.\d+)?$")

# "Chapter 01 - Title", "Ch.2: Title", "c012 — Title", "012 - Title"
_CHAPTER_TITLE_SPLIT = re.compile(
    r"""(?ix)
    ^
    (?:
        (?:chapter|ch\.?|c(?=\d))\s*\#?\s*(?P<num>\d+(?:\.\d+)?)
        |(?P<num2>\d+(?:\.\d+)?)
    )
    \s*[-–—:|]\s*
    (?P<title>.+)
    $
    """
)
_COMICINFO_TITLE_RE = re.compile(
    r"<Title[^>]*>(.*?)</Title>", re.IGNORECASE | re.DOTALL
)


@dataclass(frozen=True)
class MangaChapter:
    id: str
    title: str
    page_count: int
    kind: str  # "dir" | "cbz"
    # Relative path under manga title folder (or "." for title-root images)
    relative: str


def chapter_list_parts(
    display_title: str,
    *,
    relative: str = "",
) -> tuple[str, str]:
    """Split a chapter label into ``(number, name)`` for list UI (like episodes).

    Number stays on the left even when MangaDex supplies a real title. When no
    chapter number can be parsed, number is ``\"\"`` and name is the full title.
    """
    t = (display_title or "").strip()
    stem = relative if relative not in (".", "") else t
    num = _chapter_number_from_stem(stem) or _chapter_number_from_stem(t)
    if num is not None:
        from kostream.mangadex import normalize_chapter_key

        label_num = normalize_chapter_key(num) or num
    else:
        label_num = ""

    named = re.match(
        r"(?i)^(?:chapter|ch\.?)\s*\#?\s*\d+(?:\.\d+)?\s*:\s*(.+)$",
        t,
    )
    if named and named.group(1).strip():
        return label_num, named.group(1).strip()
    if label_num and local_chapter_title_is_meaningful(t):
        return label_num, t
    if label_num:
        # Generic \"Chapter N\" — number alone; avoid duplicating on the right.
        return label_num, ""
    return "", t or "Chapter"


def chapter_payload_row(chapter: MangaChapter) -> dict:
    """JSON row for overview/reader chapter lists."""
    number, name = chapter_list_parts(chapter.title, relative=chapter.relative)
    return {
        "id": chapter.id,
        "title": chapter.title,
        "number": number,
        "name": name,
        "page_count": chapter.page_count,
    }


@dataclass
class MangaTitle:
    id: str
    title: str
    folder: str
    chapters: list[MangaChapter] = field(default_factory=list)
    cover_chapter_id: str | None = None
    poster_url: str | None = None
    mal_id: int | None = None
    list_status: str | None = None
    num_chapters_mal: int = 0
    num_chapters_read: int = 0
    manga_status: str | None = None
    synopsis: str = ""
    source: str = "local"  # local | mal
    media_type: str | None = None  # manga | manhwa | manhua | …
    genres: list[str] = field(default_factory=list)
    release_year: int | None = None
    title_aliases: list[str] = field(default_factory=list)

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)

    @property
    def page_count(self) -> int:
        return sum(c.page_count for c in self.chapters)

    @property
    def has_local(self) -> bool:
        return bool(self.chapters)

    @property
    def is_manhwa(self) -> bool:
        return (self.media_type or "").casefold() == "manhwa"

    def chapters_payload(self) -> list[dict]:
        return [chapter_payload_row(c) for c in self.chapters]

    def chapters_payload_with_progress(
        self,
        completed: dict[str, int] | None = None,
        page_progress: dict | None = None,
    ) -> list[dict]:
        from kostream.manga_progress import chapter_completed

        pages_map: dict = {}
        if page_progress and isinstance(page_progress, dict):
            entry = page_progress.get(self.id) or {}
            if isinstance(entry, dict):
                pages_map = entry.get("pages") or {}

        payload = []
        for c in self.chapters:
            done = chapter_completed(
                self, c.id, completed, self.num_chapters_read
            )
            row = chapter_payload_row(c)
            row["done"] = done
            if not done and c.id in pages_map:
                try:
                    idx = int(pages_map[c.id])
                except (TypeError, ValueError):
                    idx = -1
                if idx > 0:
                    row["page_index"] = idx
            payload.append(row)
        return payload


class MangaError(Exception):
    """Invalid manga path or missing chapter."""


def _natural_key(name: str) -> list:
    """Sort key: decimal chapter numbers as floats (6 < 7 < 7.5 < 8)."""
    parts = _NAT_SPLIT.split(name)
    key: list = []
    for part in parts:
        if not part:
            continue
        if _NUM_TOKEN.fullmatch(part):
            key.append(float(part))
        else:
            key.append(part.casefold())
    return key


def _chapter_sort_key(chapter: MangaChapter) -> tuple:
    """Order chapters by numeric chapter number (float), then natural name."""
    name = chapter.relative if chapter.relative not in (".", "") else chapter.title
    num_s = _chapter_number_from_stem(name)
    if num_s is not None:
        return (0, float(num_s), _natural_key(name))
    return (1, 0.0, _natural_key(name))


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    slug = re.sub(r"[-\s]+", "-", slug.strip()).casefold()
    return slug or "manga"


def local_chapter_title_is_meaningful(display_title: str) -> bool:
    """True when a local label already has a real name (not just ``Chapter N``)."""
    t = (display_title or "").strip()
    if not t:
        return False
    named = re.match(
        r"(?i)^(?:chapter|ch\.?)\s*\#?\s*\d+(?:\.\d+)?\s*:\s*(.+)$",
        t,
    )
    if named:
        return bool(named.group(1).strip())
    if re.fullmatch(r"(?i)(?:chapter|ch\.?|c)?\s*\#?\s*\d+(?:\.\d+)?", t):
        return False
    return True


def apply_mangadex_chapter_titles(
    chapters: list[MangaChapter],
    mdx_titles: dict[str, str] | None,
) -> list[MangaChapter]:
    """Overlay MangaDex titles onto chapters that lack a meaningful local name."""
    if not mdx_titles or not chapters:
        return chapters
    from kostream.mangadex import normalize_chapter_key

    out: list[MangaChapter] = []
    for ch in chapters:
        if local_chapter_title_is_meaningful(ch.title):
            out.append(ch)
            continue
        stem = ch.relative if ch.relative not in (".", "") else ch.title
        num_s = _chapter_number_from_stem(stem)
        key = normalize_chapter_key(num_s) if num_s is not None else None
        name = (mdx_titles.get(key) or "").strip() if key else ""
        if not name:
            out.append(ch)
            continue
        label_num = key or num_s or "?"
        out.append(
            MangaChapter(
                id=ch.id,
                title=f"Chapter {label_num}: {name}",
                page_count=ch.page_count,
                kind=ch.kind,
                relative=ch.relative,
            )
        )
    return out


def chapter_display_title(
    raw_name: str,
    *,
    comic_title: str | None = None,
) -> str:
    """Best local chapter label from ComicInfo and/or folder/CBZ stem.

    Prefers ``ComicInfo.xml`` ``<Title>`` when present. Otherwise extracts a
    human title after a chapter-number prefix (``Chapter 01 - Foo`` →
    ``Chapter 01: Foo``). Plain stems like ``Chapter 01`` stay unchanged.
    """
    comic = (comic_title or "").strip()
    if comic:
        parsed = _CHAPTER_TITLE_SPLIT.match(comic)
        if parsed:
            num = parsed.group("num") or parsed.group("num2")
            name = (parsed.group("title") or "").strip(" .-–—:_")
            if num and name:
                return f"Chapter {num}: {name}"
        # ComicInfo often stores just the chapter name (no "Chapter N").
        if not re.fullmatch(r"(?i)(?:chapter|ch\.?|c)?\s*\#?\s*\d+(?:\.\d+)?", comic):
            stem_num = _chapter_number_from_stem(raw_name)
            if stem_num is not None:
                return f"Chapter {stem_num}: {comic}"
            return comic

    stem = _chapter_label_stem(raw_name) or "Chapter"
    parsed = _CHAPTER_TITLE_SPLIT.match(stem)
    if parsed:
        num = parsed.group("num") or parsed.group("num2")
        name = (parsed.group("title") or "").strip(" .-–—:_")
        if num and name:
            return f"Chapter {num}: {name}"
    return stem


def _chapter_label_stem(raw_name: str) -> str:
    """Basename without archive suffix only (keep dots in ``Ch.12``)."""
    name = (raw_name or "").strip()
    if not name:
        return ""
    # Path.name drops directories; avoid Path.stem which treats ``.12`` as a suffix.
    base = Path(name).name
    lower = base.casefold()
    for ext in (".cbz", ".zip", ".cbr"):
        if lower.endswith(ext):
            return base[: -len(ext)]
    return base


def _chapter_number_from_stem(raw_name: str) -> str | None:
    stem = _chapter_label_stem(raw_name)
    m = re.match(
        r"(?i)^(?:chapter|ch\.?|c(?=\d))\s*\#?\s*(\d+(?:\.\d+)?)\b",
        stem,
    )
    if m:
        return m.group(1)
    m = re.match(r"^(\d+(?:\.\d+)?)\b", stem)
    return m.group(1) if m else None


def _is_under(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _list_images_in_dir(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS and not p.name.startswith(".")
    ]
    return sorted(files, key=lambda p: _natural_key(p.name))


def _list_images_in_cbz(path: Path) -> list[str]:
    names, _comic = _read_cbz_listing(path)
    return names


def _read_cbz_listing(path: Path) -> tuple[list[str], str | None]:
    """Return ``(image names, ComicInfo title)`` from one zip open."""
    names: list[str] = []
    comic_title: str | None = None
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                if name.startswith("__MACOSX") or "/." in f"/{name}":
                    continue
                base = Path(name).name.casefold()
                if base == "comicinfo.xml" and comic_title is None:
                    try:
                        raw = zf.read(info)
                    except KeyError:
                        continue
                    comic_title = _comicinfo_title_from_bytes(raw)
                    continue
                suffix = Path(name).suffix.lower()
                if suffix in IMAGE_EXTENSIONS:
                    names.append(name)
    except (OSError, zipfile.BadZipFile):
        return [], None
    return sorted(names, key=_natural_key), comic_title


def _comicinfo_title_from_bytes(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(text)
        for el in root.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag.casefold() == "title" and (el.text or "").strip():
                return el.text.strip()
    except ET.ParseError:
        m = _COMICINFO_TITLE_RE.search(text)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip() or None
    return None



# Process-level cache: opening every CBZ for page counts / ComicInfo made home
# and library routes take ~60s with large local libraries. Scan only lists files;
# page counts resolve lazily when a chapter is opened.
_SCAN_CACHE_LOCK = threading.Lock()
_SCAN_CACHE: dict[str, tuple[tuple, list[MangaTitle]]] = {}


def _library_signature(base: Path) -> tuple:
    """Fingerprint title dirs / chapter files via name+mtime+size (no zip I/O)."""
    parts: list[tuple] = []
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        return ()
    for entry in entries:
        try:
            st = entry.stat()
        except OSError:
            continue
        if entry.is_file():
            if entry.suffix.lower() in CBZ_EXTENSIONS:
                parts.append(("file", entry.name, st.st_mtime_ns, st.st_size))
            continue
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        parts.append(("dir", entry.name, st.st_mtime_ns, st.st_size))
        try:
            children = sorted(entry.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            continue
        for child in children:
            try:
                cst = child.stat()
            except OSError:
                continue
            if child.is_file() and child.suffix.lower() in CBZ_EXTENSIONS:
                parts.append(("cbz", entry.name, child.name, cst.st_mtime_ns, cst.st_size))
            elif child.is_dir() and not child.name.startswith("."):
                parts.append(("subdir", entry.name, child.name, cst.st_mtime_ns, cst.st_size))
            elif child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS:
                parts.append(("img", entry.name, child.name, cst.st_mtime_ns, cst.st_size))
    return tuple(parts)


def clear_manga_scan_cache() -> None:
    """Drop cached scan results (tests / after external library edits)."""
    with _SCAN_CACHE_LOCK:
        _SCAN_CACHE.clear()


def scan_manga_library(root: Path | None = None) -> list[MangaTitle]:
    """Scan local manga root for title folders and loose CBZ files.

    CBZ archives are listed by filename only — page counts and ComicInfo titles
    are resolved lazily via ``enrich_manga_chapter`` / ``list_page_refs``.
    """
    base = (root or MANGA_ROOT).resolve()
    if not base.is_dir():
        return []

    cache_key = str(base)
    signature = _library_signature(base)
    with _SCAN_CACHE_LOCK:
        cached = _SCAN_CACHE.get(cache_key)
        if cached and cached[0] == signature:
            return copy.deepcopy(cached[1])

    titles: list[MangaTitle] = []

    # Loose CBZ at manga root → one title each (no zip open during scan)
    for path in sorted(base.iterdir(), key=lambda p: _natural_key(p.name)):
        if path.is_file() and path.suffix.lower() in CBZ_EXTENSIONS:
            title_id = f"file-{_slugify(path.stem)}"
            chapter = MangaChapter(
                id="main",
                title=chapter_display_title(path.name),
                page_count=0,
                kind="cbz",
                relative=path.name,
            )
            titles.append(
                MangaTitle(
                    id=title_id,
                    title=path.stem,
                    folder=path.name,
                    chapters=[chapter],
                    cover_chapter_id="main",
                )
            )

    for folder in sorted(base.iterdir(), key=lambda p: _natural_key(p.name)):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        chapters = _scan_title_folder(folder)
        if not chapters:
            continue
        title_id = f"dir-{_slugify(folder.name)}"
        titles.append(
            MangaTitle(
                id=title_id,
                title=folder.name,
                folder=folder.name,
                chapters=chapters,
                cover_chapter_id=chapters[0].id,
            )
        )

    titles.sort(key=lambda t: t.title.casefold())
    with _SCAN_CACHE_LOCK:
        _SCAN_CACHE[cache_key] = (signature, copy.deepcopy(titles))
    return copy.deepcopy(titles)


def enrich_manga_chapter(
    root: Path,
    manga: MangaTitle,
    chapter: MangaChapter,
) -> tuple[MangaChapter, list[str]]:
    """Fill CBZ page_count / ComicInfo title; return ``(chapter, image names)``."""
    if chapter.kind != "cbz":
        return chapter, []

    title_path = resolve_title_path(root, manga)
    cbz_path = title_path if title_path.is_file() else (title_path / chapter.relative)
    cbz_path = cbz_path.resolve()
    if not _is_under(cbz_path, root.resolve()):
        raise MangaError("CBZ escapes manga root")

    if chapter.page_count > 0 and local_chapter_title_is_meaningful(chapter.title):
        return chapter, _list_images_in_cbz(cbz_path)

    pages, comic_title = _read_cbz_listing(cbz_path)
    enriched = MangaChapter(
        id=chapter.id,
        title=chapter_display_title(chapter.relative or cbz_path.name, comic_title=comic_title),
        page_count=len(pages),
        kind=chapter.kind,
        relative=chapter.relative,
    )
    manga.chapters = [enriched if c.id == chapter.id else c for c in manga.chapters]
    return enriched, pages


def load_manga_library(
    root: Path | None = None,
    catalog_path: Path | None = None,
    *,
    user_id: str | None = None,
) -> list[MangaTitle]:
    """Merge MAL manga catalog with local media/manga folders."""
    from kostream.mal import load_cached_manga, load_manga_list_state
    from kostream.manga_catalog import load_manga_catalog

    base = (root or MANGA_ROOT).resolve()
    local = scan_manga_library(base)
    local_by_folder = {t.folder: t for t in local}
    catalog = load_manga_catalog(catalog_path)
    enabled_mal = [e for e in catalog.enabled if e.source == "mal" and e.mal_id]

    if not enabled_mal:
        return local

    # Load list state once instead of re-reading the JSON per catalog title.
    list_state = load_manga_list_state(user_id) if user_id else {}

    claimed_folders: set[str] = set()
    merged: list[MangaTitle] = []

    for entry in enabled_mal:
        cached = load_cached_manga(entry.mal_id) if entry.mal_id else None
        list_row = None
        if user_id and entry.mal_id:
            raw = list_state.get(str(int(entry.mal_id)))
            list_row = dict(raw) if isinstance(raw, dict) else None
        local_title = None
        folder = entry.folder
        if folder and folder in local_by_folder:
            local_title = local_by_folder[folder]
            claimed_folders.add(folder)
        else:
            # Rematch by title when folder missing / renamed after local import
            from kostream.manga_catalog import match_local_folder

            matched = match_local_folder(base, entry.title or (cached.title if cached else "") or "")
            if matched and matched in local_by_folder and matched not in claimed_folders:
                folder = matched
                local_title = local_by_folder[matched]
                claimed_folders.add(matched)
            elif folder:
                claimed_folders.add(folder)

        from kostream.titles import (
            all_searchable_titles,
            merge_title_variants,
            pick_display_title,
            variants_from_mal_fields,
        )
        from kostream.titles import resolve_title_language

        mal_variants = None
        if cached:
            mal_variants = variants_from_mal_fields(
                title=cached.title,
                title_en=cached.title_en,
                title_ja=cached.title_ja,
                title_ger=cached.title_ger,
                synonyms=cached.title_synonyms,
            )
        variants = merge_title_variants(
            mal_variants,
            variants_from_mal_fields(
                title=entry.title
                or (local_title.title if local_title else None)
                or entry.id
            ),
        )
        title_name = pick_display_title(variants, resolve_title_language())
        title_aliases = all_searchable_titles(variants)
        status = (list_row or {}).get("list_status") if list_row else None
        if status is None:
            status = cached.list_status if cached else None
        chapters_read = int((list_row or {}).get("num_chapters_read") or 0) if list_row else (
            cached.num_chapters_read if cached else 0
        )
        chapters = list(local_title.chapters) if local_title else []
        if chapters and entry.mal_id:
            from kostream.mangadex import load_cached_chapter_titles

            chapters = apply_mangadex_chapter_titles(
                chapters, load_cached_chapter_titles(entry.mal_id)
            )
        # Prefer local Thumbnail cache, then MAL CDN, then first page
        poster = None
        if entry.mal_id:
            try:
                from kostream.thumbnails import thumbnail_public_url

                poster = thumbnail_public_url("manga", int(entry.mal_id))
            except (OSError, TypeError, ValueError):
                poster = None
        if not poster:
            poster = cached.poster_url if cached else None
        cover = None if poster else (local_title.cover_chapter_id if local_title else None)
        media_type = (
            (cached.media_type if cached else None)
            or entry.media_type
            or "manga"
        )
        genres = list(cached.genres) if cached and cached.genres else []
        merged.append(
            MangaTitle(
                id=entry.id,
                title=title_name,
                title_aliases=title_aliases,
                folder=folder or (local_title.folder if local_title else ""),
                chapters=chapters,
                cover_chapter_id=cover,
                poster_url=poster,
                mal_id=entry.mal_id,
                list_status=status,
                num_chapters_mal=cached.num_chapters if cached else 0,
                num_chapters_read=chapters_read,
                manga_status=cached.manga_status if cached else None,
                synopsis=(cached.synopsis[:400] if cached and cached.synopsis else ""),
                source="mal",
                media_type=media_type,
                genres=genres,
                release_year=cached.release_year if cached else None,
            )
        )

    for local_title in local:
        if local_title.folder in claimed_folders:
            continue
        merged.append(local_title)

    merged.sort(key=lambda t: t.title.casefold())
    return merged


def filter_library_format(
    titles: list[MangaTitle],
    *,
    kind: str = "manga",
) -> list[MangaTitle]:
    """Split library into Manga vs Manhwa pages (MAL media_type)."""
    want = (kind or "manga").casefold()
    if want == "manhwa":
        return [t for t in titles if t.is_manhwa]
    # Manga tab: everything that is not manhwa (manga, novel, one_shot, manhua, …)
    return [t for t in titles if not t.is_manhwa]


def collect_manga_genres(titles: list[MangaTitle]) -> list[str]:
    """Unique MAL genres across titles, sorted case-insensitively."""
    found: set[str] = set()
    for title in titles:
        for genre in title.genres or []:
            name = (genre or "").strip()
            if name:
                found.add(name)
    return sorted(found, key=str.casefold)


def title_matches_genre(title: MangaTitle, genre: str | None) -> bool:
    g = (genre or "").strip()
    if not g:
        return True
    return g in (title.genres or [])


def _scan_title_folder(folder: Path) -> list[MangaChapter]:
    chapters: list[MangaChapter] = []

    # Images directly in title folder → single chapter
    root_images = _list_images_in_dir(folder)
    if root_images:
        chapters.append(
            MangaChapter(
                id="root",
                title="Chapter 1",
                page_count=len(root_images),
                kind="dir",
                relative=".",
            )
        )

    # Subfolders = chapters
    for sub in sorted(folder.iterdir(), key=lambda p: _natural_key(p.name)):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        images = _list_images_in_dir(sub)
        if not images:
            continue
        chapters.append(
            MangaChapter(
                id=f"dir-{_slugify(sub.name)}",
                title=chapter_display_title(sub.name),
                page_count=len(images),
                kind="dir",
                relative=sub.name,
            )
        )

    # CBZ inside title folder — list only; open zip lazily when reading
    for path in sorted(folder.iterdir(), key=lambda p: _natural_key(p.name)):
        if not path.is_file() or path.suffix.lower() not in CBZ_EXTENSIONS:
            continue
        chapters.append(
            MangaChapter(
                id=f"cbz-{_slugify(path.stem)}",
                title=chapter_display_title(path.name),
                page_count=0,
                kind="cbz",
                relative=path.name,
            )
        )

    # Interleave dirs + CBZs by chapter number (6 < 7 < 7.5 < 8).
    chapters.sort(key=_chapter_sort_key)
    return chapters


def find_manga_in_library(
    titles: list[MangaTitle],
    *,
    manga_id: str | None = None,
    mal_id: int | None = None,
    title: str | None = None,
) -> MangaTitle | None:
    """Locate a library title by id, MAL id, legacy local id, or title.

    After MAL catalog merge, local ``dir-*`` / ``file-*`` ids are replaced by
    ``mal-manga-*``; recommendations may still store the old id.
    """
    mid = (manga_id or "").strip()
    if mid:
        for entry in titles:
            if entry.id == mid:
                return entry

    if mal_id is not None:
        try:
            mid_i = int(mal_id)
        except (TypeError, ValueError):
            mid_i = None
        if mid_i is not None:
            for entry in titles:
                if entry.mal_id == mid_i:
                    return entry

    if mid.startswith("dir-") or mid.startswith("file-"):
        for entry in titles:
            folder = (entry.folder or "").strip()
            if not folder:
                continue
            folder_name = Path(folder).name
            stem = Path(folder).stem
            if mid == f"dir-{_slugify(folder)}" or mid == f"dir-{_slugify(folder_name)}":
                return entry
            if mid == f"file-{_slugify(stem)}":
                return entry

    name = (title or "").strip().casefold()
    if name:
        for entry in titles:
            if entry.title.casefold() == name:
                return entry
            if (entry.folder or "").casefold() == name:
                return entry
    return None


def get_manga(
    manga_id: str,
    root: Path | None = None,
    catalog_path: Path | None = None,
) -> MangaTitle | None:
    return find_manga_in_library(
        load_manga_library(root, catalog_path),
        manga_id=manga_id,
    )


def get_chapter(manga: MangaTitle, chapter_id: str) -> MangaChapter | None:
    return next((c for c in manga.chapters if c.id == chapter_id), None)


def resolve_title_path(root: Path, manga: MangaTitle) -> Path:
    base = root.resolve()
    if not manga.folder:
        raise MangaError("No local manga folder linked")
    path = (base / manga.folder).resolve()
    if not _is_under(path, base) and path.parent != base and path != base:
        raise MangaError("Title path escapes manga root")
    # Allow files directly under manga root (loose CBZ)
    if path.is_file():
        if path.parent.resolve() != base:
            raise MangaError("Title file escapes manga root")
        return path
    if not path.exists():
        raise MangaError("Manga folder not found")
    if not _is_under(path, base):
        raise MangaError("Title path escapes manga root")
    return path


def list_page_refs(root: Path, manga: MangaTitle, chapter: MangaChapter) -> list[dict]:
    """Return [{index, url_path}] for reader (0-based index)."""
    title_path = resolve_title_path(root, manga)
    pages: list[dict] = []

    if chapter.kind == "dir":
        folder = title_path if chapter.relative in (".", "") else (title_path / chapter.relative)
        folder = folder.resolve()
        if not _is_under(folder, root.resolve()) and folder != title_path:
            raise MangaError("Chapter folder escapes manga root")
        images = _list_images_in_dir(folder)
        for i, _img in enumerate(images):
            pages.append({"index": i, "url": f"/manga-page/{manga.id}/{chapter.id}/{i}"})
        return pages

    if chapter.kind == "cbz":
        chapter, names = enrich_manga_chapter(root, manga, chapter)
        for i, _name in enumerate(names):
            pages.append({"index": i, "url": f"/manga-page/{manga.id}/{chapter.id}/{i}"})
        return pages

    raise MangaError(f"Unknown chapter kind: {chapter.kind}")


def read_page_bytes(root: Path, manga: MangaTitle, chapter: MangaChapter, index: int) -> tuple[bytes, str]:
    """Return (bytes, mimetype) for page index."""
    title_path = resolve_title_path(root, manga)

    if chapter.kind == "dir":
        folder = title_path if chapter.relative in (".", "") else (title_path / chapter.relative)
        images = _list_images_in_dir(folder.resolve())
        if index < 0 or index >= len(images):
            raise MangaError("Page out of range")
        path = images[index]
        if not _is_under(path.resolve(), root.resolve()):
            raise MangaError("Page escapes manga root")
        suffix = path.suffix.lower()
        mime = _mime_for_suffix(suffix)
        return path.read_bytes(), mime

    if chapter.kind == "cbz":
        chapter, names = enrich_manga_chapter(root, manga, chapter)
        if index < 0 or index >= len(names):
            raise MangaError("Page out of range")
        name = names[index]
        cbz_path = title_path if title_path.is_file() else (title_path / chapter.relative)
        cbz_path = cbz_path.resolve()
        if not _is_under(cbz_path, root.resolve()):
            raise MangaError("CBZ escapes manga root")
        with zipfile.ZipFile(cbz_path, "r") as zf:
            data = zf.read(name)
        mime = _mime_for_suffix(Path(name).suffix.lower())
        return data, mime

    raise MangaError(f"Unknown chapter kind: {chapter.kind}")

    raise MangaError(f"Unknown chapter kind: {chapter.kind}")


def _mime_for_suffix(suffix: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".avif": "image/avif",
        ".bmp": "image/bmp",
    }.get(suffix, "application/octet-stream")
