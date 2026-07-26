"""Tests for explicit URL → ffmpeg local fetch + registry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from kostream.catalog import CatalogEntry, CatalogState, save_catalog
from kostream.episode_fetch import fetch_episode_from_url
from kostream.local_media import LocalMediaError
from kostream.local_registry import get_local, list_for_show, mark_local
from kostream.models import Episode, Show
from kostream.stream_fetch import StreamFetchError, fetch_into_storage, validate_stream_url


def test_validate_stream_url():
    assert validate_stream_url("https://cdn.example/a.m3u8").startswith("https://")
    with pytest.raises(StreamFetchError):
        validate_stream_url("not-a-url")


def test_registry_roundtrip(tmp_path: Path):
    reg = tmp_path / "local_registry.json"
    mark_local(
        "mal-1",
        "mal-1-s04e03",
        path=str(tmp_path / "S04E03.mp4"),
        filename="S04E03.mp4",
        source_url="https://cdn.example/x.m3u8",
        registry_path=reg,
    )
    entry = get_local("mal-1", "mal-1-s04e03", registry_path=reg)
    assert entry is not None
    assert entry["filename"] == "S04E03.mp4"
    assert len(list_for_show("mal-1", registry_path=reg)) == 1


def test_fetch_into_storage_calls_ffmpeg(tmp_path: Path, monkeypatch):
    def fake_run(cmd, **kwargs):
        dest = Path(cmd[-1])
        dest.write_bytes(b"fake-mp4")

        class R:
            returncode = 0
            stderr = ""
            stdout = ""

        return R()

    monkeypatch.setattr("kostream.stream_fetch.shutil.which", lambda _: "/usr/bin/ffmpeg")
    with patch("kostream.stream_fetch.subprocess.run", side_effect=fake_run):
        out = fetch_into_storage(
            "https://cdn.example/ep.m3u8",
            "clip.mp4",
            storage_dir=tmp_path / "media_assets",
        )
    assert out.is_file()
    assert out.name == "clip.mp4"


def test_fetch_episode_from_url(tmp_path: Path, monkeypatch):
    media = tmp_path / "shows"
    catalog = tmp_path / "selected.json"
    reg = tmp_path / "registry.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-1",
                    enabled=True,
                    source="mal",
                    folder="Demo",
                    mal_id=1,
                    title="Demo",
                )
            ]
        ),
        catalog,
    )
    ep = Episode("mal-1-s04e03", "mal-1", 4, 3, "Episode 3", "demo.mp4")
    show = Show(id="mal-1", title="Demo", description="", mal_id=1, episodes=[ep])

    def fake_fetch(url, dest, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"vid")
        return dest

    monkeypatch.setattr("kostream.episode_fetch.fetch_stream_to_file", fake_fetch)
    result = fetch_episode_from_url(
        show,
        ep,
        "https://cdn.example/ep.m3u8",
        media,
        catalog_path=catalog,
        registry_path=reg,
    )
    assert result["ok"] is True
    assert result["filename"] == "S04E03.mp4"
    assert (media / "Demo" / "S04E03.mp4").is_file()
    assert get_local("mal-1", "mal-1-s04e03", registry_path=reg) is not None


def test_fetch_rejects_bad_url(tmp_path: Path):
    ep = Episode("a-s01e01", "a", 1, 1, "Episode 1", "demo.mp4")
    show = Show(id="a", title="A", description="", episodes=[ep])
    with pytest.raises(LocalMediaError):
        fetch_episode_from_url(show, ep, "ftp://nope", tmp_path / "shows")


def test_fetch_episode_from_local_path(tmp_path: Path):
    media = tmp_path / "shows"
    catalog = tmp_path / "selected.json"
    reg = tmp_path / "registry.json"
    src = tmp_path / "test.mp4"
    src.write_bytes(b"dummy-video")
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="mal-1",
                    enabled=True,
                    source="mal",
                    folder="Demo",
                    mal_id=1,
                    title="Demo",
                )
            ]
        ),
        catalog,
    )
    ep = Episode("mal-1-s04e03", "mal-1", 4, 3, "Episode 3", "demo.mp4")
    show = Show(id="mal-1", title="Demo", description="", mal_id=1, episodes=[ep])

    result = fetch_episode_from_url(
        show,
        ep,
        str(src),
        media,
        catalog_path=catalog,
        registry_path=reg,
    )
    assert result["ok"] is True
    assert result["registry_updated"] is True
    assert result["source_kind"] == "local"
    assert (media / "Demo" / "S04E03.mp4").read_bytes() == b"dummy-video"
    assert get_local("mal-1", "mal-1-s04e03", registry_path=reg) is not None
