"""Download an explicitly provided stream URL to a local file via ffmpeg.

No site scraping — caller must supply a direct .mp4 / .m3u8 (or similar) URL.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)

DEFAULT_STORAGE = Path(__file__).resolve().parents[2] / "media_assets"


class StreamFetchError(Exception):
    """URL or ffmpeg download failed."""


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def validate_stream_url(url: str) -> str:
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise StreamFetchError("URL must be an absolute http(s) address")
    return cleaned


def resolve_fetch_source(url: str) -> tuple[str, str | Path]:
    """Return ``(\"http\", url)`` or ``(\"local\", Path)`` for an explicit fetch source."""
    cleaned = (url or "").strip().strip('"').strip("'")
    if not cleaned:
        raise StreamFetchError("Empty source")

    parsed = urlparse(cleaned)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return "http", cleaned

    if parsed.scheme == "file":
        from urllib.request import url2pathname

        local = Path(url2pathname(parsed.path))
    else:
        # Plain path, or Windows drive path (urlparse treats "C:" as scheme).
        local = Path(cleaned)

    local = local.expanduser()
    if not local.is_file():
        raise StreamFetchError(f"Local file not found: {local}")
    return "local", local.resolve()


def fetch_stream_to_file(
    url: str,
    dest: Path,
    *,
    timeout_seconds: int = 60 * 60,
) -> Path:
    """Copy a local file or download ``url`` to ``dest`` (ffmpeg stream copy for http)."""
    kind, source = resolve_fetch_source(url)

    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

    if kind == "local":
        src = Path(source)
        log.info("local copy %s → %s", src, dest)
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            raise StreamFetchError(f"Local copy failed: {exc}") from exc
        if not dest.is_file() or dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
            raise StreamFetchError("Local copy produced an empty file")
        return dest

    cleaned = str(source)
    if not shutil.which("ffmpeg"):
        raise StreamFetchError("ffmpeg not found on PATH")

    # -c copy: remux only. aac_adtstoasc helps HLS → MP4 audio.
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        cleaned,
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        str(dest),
    ]
    log.info("ffmpeg fetch → %s", dest)
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise StreamFetchError("ffmpeg timed out") from exc
    except OSError as exc:
        raise StreamFetchError(f"ffmpeg failed to start: {exc}") from exc

    if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        err = (completed.stderr or completed.stdout or "").strip()
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise StreamFetchError(err or f"ffmpeg exited {completed.returncode}")

    return dest


def fetch_into_storage(
    url: str,
    filename: str,
    *,
    storage_dir: Path | str = DEFAULT_STORAGE,
) -> Path:
    """Save under ``storage_dir`` / ``filename`` (e.g. media_assets/S04E03.mp4)."""
    root = Path(storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    name = Path(filename).name
    if not name or name != Path(filename).name or "/" in filename or "\\" in filename:
        raise StreamFetchError("Invalid filename")
    if not name.lower().endswith((".mp4", ".mkv", ".webm", ".ts")):
        name = f"{Path(name).stem}.mp4"
    dest = (root / name).resolve()
    try:
        dest.relative_to(root.resolve())
    except ValueError as exc:
        raise StreamFetchError("Destination escapes storage_dir") from exc
    return fetch_stream_to_file(url, dest)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 3:
        print("Usage: python -m kostream.stream_fetch <url> <filename.mp4>")
        raise SystemExit(2)
    out = fetch_into_storage(sys.argv[1], sys.argv[2])
    print(out)
