from kostream.models import Episode, Show


def test_is_metadata_only_true_for_demo_episodes():
    show = Show(
        id="mal-1",
        title="Test",
        description="",
        episodes=[Episode("e1", "mal-1", 1, 1, "EP1", "demo.mp4")],
    )
    assert show.is_metadata_only is True
    assert show.has_local_files is False
    assert show.is_stream_only is True


def test_is_metadata_only_false_for_real_file():
    show = Show(
        id="local-1",
        title="Test",
        description="",
        episodes=[Episode("e1", "local-1", 1, 1, "EP1", "S01E01.mp4")],
    )
    assert show.is_metadata_only is False
    assert show.has_local_files is True
    assert show.is_stream_only is False


def test_stream_only_includes_strm_and_jellyfin():
    show = Show(
        id="remote-1",
        title="Remote",
        description="",
        episodes=[
            Episode("e1", "remote-1", 1, 1, "EP1", "strm:https://example.com/a.m3u8"),
            Episode("e2", "remote-1", 1, 2, "EP2", "jellyfin:abc123"),
        ],
    )
    assert show.is_metadata_only is False
    assert show.has_local_files is False
    assert show.is_stream_only is True
