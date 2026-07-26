from pathlib import Path

from flask import Flask

from kostream.library import scan_library
from kostream.models import Episode, is_strm_episode, strm_target_url
from kostream.streaming import stream_file_with_range


def test_range_request_returns_partial_content(tmp_path: Path):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"0123456789abcdef")

    app = Flask(__name__)

    with app.test_request_context(headers={"Range": "bytes=0-3"}):
        from flask import request

        resp = stream_file_with_range(video, request)
        assert resp.status_code == 206
        assert resp.headers.get("Content-Range") == "bytes 0-3/16"
        data = b"".join(resp.response)
        assert data == b"0123"


def test_strm_scan(tmp_path: Path):
    show_dir = tmp_path / "Demo Show"
    show_dir.mkdir()
    (show_dir / "S01E01.strm").write_text("https://example.com/ep1.mp4\n", encoding="utf-8")

    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    shows = scan_library(tmp_path, catalog)
    assert len(shows) == 1
    ep = shows[0].episodes[0]
    assert is_strm_episode(ep)
    assert strm_target_url(ep) == "https://example.com/ep1.mp4"
