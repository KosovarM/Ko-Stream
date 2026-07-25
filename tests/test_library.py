from pathlib import Path

from kostream.library import scan_library
from kostream.models import slugify


def test_slugify():
    assert slugify("One Piece") == "one-piece"


def test_scan_empty_uses_demo(tmp_path: Path):
    shows = scan_library(tmp_path)
    assert len(shows) >= 1
