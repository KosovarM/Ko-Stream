"""Local manga library — scan media/manga and serve page images (folders + CBZ).

Chapter display titles come from local filenames / CBZ ``ComicInfo.xml`` only.
MAL and Jikan expose manga ``num_chapters`` but not per-chapter titles (unlike
anime episode lists), so Sync cannot populate chapter names the way it does for
anime. See ``chapter_display_title`` / ``_comicinfo_title_from_cbz``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MANGA_ROOT = Path(__file__).resolve().parents[2] / "media" / "manga"

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
        return [
            {"id": c.id, "title": c.title, "page_count": c.page_count}
            for c in self.chapters
        ]

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
            row: dict = {
                "id": c.id,
                "title": c.title,
                "page_count": c.page_count,
                "done": done,
            }
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


def _comicinfo_title_from_cbz(path: Path) -> str | None:
    """Read ``<Title>`` from ComicInfo.xml inside a CBZ/ZIP, if present."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            comicinfo_name = next(
                (
                    n
                    for n in zf.namelist()
                    if Path(n.replace("\\", "/")).name.casefold() == "comicinfo.xml"
                ),
                None,
            )
            if not comicinfo_name:
                return None
            raw = zf.read(comicinfo_name)
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    # Prefer ElementTree; fall back to a light regex for slightly broken XML.
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
    names: list[str] = []
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if name.startswith("__MACOSX") or "/." in f"/{name}":
                continue
            suffix = Path(name).suffix.lower()
            if suffix in IMAGE_EXTENSIONS:
                names.append(name)
    return sorted(names, key=_natural_key)


def scan_manga_library(root: Path | None = None) -> list[MangaTitle]:
    base = (root or MANGA_ROOT).resolve()
    if not base.is_dir():
        return []

    titles: list[MangaTitle] = []

    # Loose CBZ at manga root → one title each
    for path in sorted(base.iterdir(), key=lambda p: _natural_key(p.name)):
        if path.is_file() and path.suffix.lower() in CBZ_EXTENSIONS:
            pages = _list_images_in_cbz(path)
            if not pages:
                continue
            title_id = f"file-{_slugify(path.stem)}"
            comic_title = _comicinfo_title_from_cbz(path)
            chapter = MangaChapter(
                id="main",
                title=chapter_display_title(path.name, comic_title=comic_title),
                page_count=len(pages),
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
    return titles


def load_manga_library(
    root: Path | None = None,
    catalog_path: Path | None = None,
) -> list[MangaTitle]:
    """Merge MAL manga catalog with local media/manga folders."""
    from kostream.mal import load_cached_manga
    from kostream.manga_catalog import load_manga_catalog

    base = (root or MANGA_ROOT).resolve()
    local = scan_manga_library(base)
    local_by_folder = {t.folder: t for t in local}
    catalog = load_manga_catalog(catalog_path)
    enabled_mal = [e for e in catalog.enabled if e.source == "mal" and e.mal_id]

    if not enabled_mal:
        return local

    claimed_folders: set[str] = set()
    merged: list[MangaTitle] = []

    for entry in enabled_mal:
        cached = load_cached_manga(entry.mal_id) if entry.mal_id else None
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

        title_name = (
            (cached.title if cached else None)
            or entry.title
            or (local_title.title if local_title else None)
            or entry.id
        )
        status = cached.list_status if cached else None
        chapters = local_title.chapters if local_title else []
        # Prefer MAL poster over first page (often credits/scan pages)
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
                folder=folder or (local_title.folder if local_title else ""),
                chapters=list(chapters),
                cover_chapter_id=cover,
                poster_url=poster,
                mal_id=entry.mal_id,
                list_status=status,
                num_chapters_mal=cached.num_chapters if cached else 0,
                num_chapters_read=cached.num_chapters_read if cached else 0,
                manga_status=cached.manga_status if cached else None,
                synopsis=(cached.synopsis[:400] if cached and cached.synopsis else ""),
                source="mal",
                media_type=media_type,
                genres=genres,
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

    # CBZ inside title folder
    for path in sorted(folder.iterdir(), key=lambda p: _natural_key(p.name)):
        if not path.is_file() or path.suffix.lower() not in CBZ_EXTENSIONS:
            continue
        pages = _list_images_in_cbz(path)
        if not pages:
            continue
        comic_title = _comicinfo_title_from_cbz(path)
        chapters.append(
            MangaChapter(
                id=f"cbz-{_slugify(path.stem)}",
                title=chapter_display_title(path.name, comic_title=comic_title),
                page_count=len(pages),
                kind="cbz",
                relative=path.name,
            )
        )

    # Interleave dirs + CBZs by chapter number (6 < 7 < 7.5 < 8).
    chapters.sort(key=_chapter_sort_key)
    return chapters


def get_manga(
    manga_id: str,
    root: Path | None = None,
    catalog_path: Path | None = None,
) -> MangaTitle | None:
    for title in load_manga_library(root, catalog_path):
        if title.id == manga_id:
            return title
    return None


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
        cbz_path = title_path if title_path.is_file() else (title_path / chapter.relative)
        cbz_path = cbz_path.resolve()
        if not _is_under(cbz_path, root.resolve()):
            raise MangaError("CBZ escapes manga root")
        names = _list_images_in_cbz(cbz_path)
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
        cbz_path = title_path if title_path.is_file() else (title_path / chapter.relative)
        cbz_path = cbz_path.resolve()
        if not _is_under(cbz_path, root.resolve()):
            raise MangaError("CBZ escapes manga root")
        names = _list_images_in_cbz(cbz_path)
        if index < 0 or index >= len(names):
            raise MangaError("Page out of range")
        name = names[index]
        with zipfile.ZipFile(cbz_path, "r") as zf:
            data = zf.read(name)
        mime = _mime_for_suffix(Path(name).suffix.lower())
        return data, mime

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
