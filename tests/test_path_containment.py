"""S1: media path resolution must stay under the media root."""

from __future__ import annotations

from pathlib import Path

from kostream.app import _path_is_under, _resolve_local_path, _resolve_local_poster


def test_path_is_under_rejects_escape(tmp_path: Path):
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    assert _path_is_under(outside, root) is False
    child = root / "Show" / "S01E01.mp4"
    child.parent.mkdir()
    child.write_text("x", encoding="utf-8")
    assert _path_is_under(child, root) is True


def test_resolve_rejects_dotdot_filename(tmp_path: Path):
    root = tmp_path / "media"
    show = root / "Demo"
    show.mkdir(parents=True)
    (show / "S01E01.mp4").write_bytes(b"x")
    assert _resolve_local_path(root, "demo", "../S01E01.mp4") is None
    assert _resolve_local_path(root, "demo", "..\\..\\Windows\\win.ini") is None


def test_resolve_accepts_normal_file(tmp_path: Path):
    root = tmp_path / "media"
    show = root / "Demo Show"
    show.mkdir(parents=True)
    ep = show / "S01E01.mp4"
    ep.write_bytes(b"video")
    found = _resolve_local_path(root, "demo-show", "S01E01.mp4")
    assert found is not None
    assert found.resolve() == ep.resolve()


def test_resolve_poster_stays_under_root(tmp_path: Path):
    root = tmp_path / "media"
    show = root / "Demo"
    show.mkdir(parents=True)
    poster = show / "poster.jpg"
    poster.write_bytes(b"jpg")
    found = _resolve_local_poster(root, "demo")
    assert found is not None
    assert found.resolve() == poster.resolve()
