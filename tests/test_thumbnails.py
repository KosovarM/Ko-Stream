"""Local thumbnail cache."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from kostream.thumbnails import (
    download_thumbnail,
    ensure_thumbnail_dirs,
    find_thumbnail_file,
    thumbnail_public_url,
)


def test_ensure_dirs_and_skip_existing(tmp_path: Path):
    root = tmp_path / "Thumbnail"
    ensure_thumbnail_dirs(root)
    assert (root / "anime").is_dir()
    assert (root / "manga").is_dir()

    existing = root / "anime" / "123.jpg"
    existing.write_bytes(b"abc")
    assert find_thumbnail_file("anime", 123, root) == existing
    assert thumbnail_public_url("anime", 123, root) == "/media/thumbnail/anime/123"


def test_download_thumbnail_writes_file(tmp_path: Path):
    root = tmp_path / "Thumbnail"
    ensure_thumbnail_dirs(root)

    body = b"\xff\xd8\xfffakejpeg"
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.headers = {"Content-Type": "image/jpeg"}
    mock_resp.geturl.return_value = "https://cdn.example/poster.jpg"
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    with patch("kostream.thumbnails.urlopen", return_value=mock_resp):
        path = download_thumbnail(
            "anime",
            42,
            "https://cdn.example/poster.jpg",
            root=root,
        )
    assert path is not None
    assert path.is_file()
    assert path.read_bytes() == body
    # Second call skips download
    with patch("kostream.thumbnails.urlopen") as again:
        path2 = download_thumbnail(
            "anime",
            42,
            "https://cdn.example/poster.jpg",
            root=root,
        )
        again.assert_not_called()
    assert path2 == path
