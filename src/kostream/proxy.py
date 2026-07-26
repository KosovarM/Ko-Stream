"""Proxy remote streams with HTTP Range support (no local copy)."""

from __future__ import annotations

from typing import Iterator
from urllib.error import HTTPError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from flask import Request, Response

_DEFAULT_CHUNK = 1024 * 512


def proxy_remote_stream(
    url: str,
    request: Request,
    *,
    headers: dict[str, str] | None = None,
    mimetype: str = "video/mp4",
) -> Response:
    """Forward Range requests to a remote URL and stream the response."""
    forward_headers = {"Accept": "*/*", **(headers or {})}
    range_header = request.headers.get("Range")
    if range_header:
        forward_headers["Range"] = range_header

    req = UrlRequest(url, headers=forward_headers, method="GET")
    try:
        remote = urlopen(req, timeout=60)
    except HTTPError as exc:
        if exc.code == 416:
            return Response(status=416)
        raise

    status = remote.status
    resp_headers = {
        "Accept-Ranges": remote.headers.get("Accept-Ranges", "bytes"),
        "Content-Type": remote.headers.get("Content-Type", mimetype),
    }
    content_length = remote.headers.get("Content-Length")
    content_range = remote.headers.get("Content-Range")
    if content_length:
        resp_headers["Content-Length"] = content_length
    if content_range:
        resp_headers["Content-Range"] = content_range

    def generate() -> Iterator[bytes]:
        try:
            while True:
                chunk = remote.read(_DEFAULT_CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            remote.close()

    return Response(generate(), status=status, headers=resp_headers)
