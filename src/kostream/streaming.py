"""HTTP Range streaming for on-demand playback without copying files."""

from __future__ import annotations

import re
from pathlib import Path

from flask import Request, Response, send_file

_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


def stream_file_with_range(path: Path, request: Request, mimetype: str | None = None) -> Response:
    """Stream a file using HTTP 206 Range requests (seek-friendly, zero extra storage)."""
    if not path.is_file():
        raise FileNotFoundError(path)

    file_size = path.stat().st_size
    mime = mimetype or _guess_mimetype(path)
    range_header = request.headers.get("Range")

    if not range_header:
        response = send_file(path, mimetype=mime, conditional=True)
        response.headers["Accept-Ranges"] = "bytes"
        return response

    match = _RANGE_RE.match(range_header.strip())
    if not match:
        response = send_file(path, mimetype=mime, conditional=True)
        response.headers["Accept-Ranges"] = "bytes"
        return response

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1
    end = min(end, file_size - 1)

    if start >= file_size or start > end:
        return Response(status=416, headers={"Content-Range": f"bytes */{file_size}"})

    length = end - start + 1

    def generate():
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            chunk_size = 1024 * 512
            while remaining > 0:
                chunk = handle.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    response = Response(generate(), status=206, mimetype=mime, direct_passthrough=True)
    response.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Length"] = str(length)
    return response


def _guess_mimetype(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".vtt": "text/vtt",
    }.get(ext, "application/octet-stream")
