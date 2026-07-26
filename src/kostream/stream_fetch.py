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


def fetch_stream_to_file(
    url: str,
    dest: Path,
    *,
    timeout_seconds: int = 60 * 60,
) -> Path:
    """Download ``url`` to ``dest`` using ffmpeg stream copy (no re-encode)."""
    cleaned = validate_stream_url(url)
    if not shutil.which("ffmpeg"):
        raise StreamFetchError("ffmpeg not found on PATH")

    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

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
