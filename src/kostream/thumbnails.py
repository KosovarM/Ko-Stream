"""Local MAL poster/thumbnail cache under the Ko-Stream media tree.

Layout::

    D:\\Media\\Ko-Stream\\Thumbnail\\
      anime\\<mal_id>.jpg
      manga\\<mal_id>.jpg

Downloaded during anime/manga sync when missing. Page loads prefer these
files over MAL CDN URLs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kostream.library import MEDIA_ROOT

Kind = Literal["anime", "manga"]

_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif)(?:\?|$)", re.IGNORECASE)


def default_thumbnail_root() -> Path:
    env = (os.environ.get("KOSTREAM_THUMBNAIL_ROOT") or "").strip()
    if env:
        return Path(env)
    # Sibling of anime root: D:\Media\Ko-Stream\Thumbnail
    anime = MEDIA_ROOT
    parent = anime.parent if anime.name.lower() in ("anime", "shows") else anime
    return parent / "Thumbnail"


THUMBNAIL_ROOT = default_thumbnail_root()


def thumbnail_dir(kind: Kind, root: Path | None = None) -> Path:
    return (root or THUMBNAIL_ROOT) / kind


def find_thumbnail_file(kind: Kind, mal_id: int, root: Path | None = None) -> Path | None:
    base = thumbnail_dir(kind, root)
    if not base.is_dir():
        return None
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        path = base / f"{int(mal_id)}{ext}"
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def thumbnail_public_url(kind: Kind, mal_id: int, root: Path | None = None) -> str | None:
    """App-relative URL if a local file exists."""
    if find_thumbnail_file(kind, mal_id, root) is None:
        return None
    return f"/media/thumbnail/{kind}/{int(mal_id)}"


def ensure_thumbnail_dirs(root: Path | None = None) -> Path:
    base = root or THUMBNAIL_ROOT
    (base / "anime").mkdir(parents=True, exist_ok=True)
    (base / "manga").mkdir(parents=True, exist_ok=True)
    return base


def _guess_ext(url: str, content_type: str | None) -> str:
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in ("image/jpeg", "image/jpg"):
            return ".jpg"
        if ct == "image/png":
            return ".png"
        if ct == "image/webp":
            return ".webp"
        if ct == "image/gif":
            return ".gif"
    m = _EXT_RE.search(url or "")
    if m:
        ext = m.group(1).lower()
        return ".jpg" if ext == "jpeg" else f".{ext}"
    return ".jpg"


def download_thumbnail(
    kind: Kind,
    mal_id: int,
    remote_url: str,
    *,
    root: Path | None = None,
    timeout: float = 30.0,
) -> Path | None:
    """Download ``remote_url`` into Thumbnail/<kind>/<mal_id>.* if missing.

    Returns the local path (existing or newly written), or None on failure.
    """
    url = (remote_url or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return None
    mid = int(mal_id)
    existing = find_thumbnail_file(kind, mid, root)
    if existing is not None:
        return existing

    ensure_thumbnail_dirs(root)
    dest_dir = thumbnail_dir(kind, root)
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "Ko-Stream/0.2 (local library thumbnail cache)",
                "Accept": "image/*,*/*",
            },
        )
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type")
            final_url = getattr(resp, "geturl", lambda: url)()
    except (HTTPError, URLError, TimeoutError, OSError):
        return None
    if not data:
        return None

    ext = _guess_ext(final_url or url, ctype)
    dest = dest_dir / f"{mid}{ext}"
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return None
    return dest


def sync_anime_thumbnails_from_cache(
    *,
    root: Path | None = None,
    limit: int | None = None,
) -> int:
    """Download missing anime posters from MAL anime cache. Returns new downloads."""
    from kostream.mal import CACHE_DIR, load_cached_anime

    ensure_thumbnail_dirs(root)
    if not CACHE_DIR.is_dir():
        return 0
    downloaded = 0
    for path in sorted(CACHE_DIR.glob("*.json")):
        if limit is not None and downloaded >= limit:
            break
        try:
            mal_id = int(path.stem)
        except ValueError:
            continue
        if find_thumbnail_file("anime", mal_id, root):
            continue
        entry = load_cached_anime(mal_id)
        if not entry or not entry.poster_url:
            continue
        result = download_thumbnail("anime", mal_id, entry.poster_url, root=root)
        if result is not None:
            downloaded += 1
    return downloaded


def sync_manga_thumbnails_from_cache(
    *,
    root: Path | None = None,
    limit: int | None = None,
) -> int:
    """Download missing manga posters from MAL manga cache. Returns new downloads."""
    from kostream.mal import MANGA_CACHE_DIR, load_cached_manga

    ensure_thumbnail_dirs(root)
    if not MANGA_CACHE_DIR.is_dir():
        return 0
    downloaded = 0
    for path in sorted(MANGA_CACHE_DIR.glob("*.json")):
        if limit is not None and downloaded >= limit:
            break
        try:
            mal_id = int(path.stem)
        except ValueError:
            continue
        if find_thumbnail_file("manga", mal_id, root):
            continue
        entry = load_cached_manga(mal_id)
        if not entry or not entry.poster_url:
            continue
        before = find_thumbnail_file("manga", mal_id, root)
        result = download_thumbnail("manga", mal_id, entry.poster_url, root=root)
        if result is not None and before is None:
            downloaded += 1
    return downloaded
