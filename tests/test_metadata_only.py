from kostream.models import Episode, Show


def test_is_metadata_only_true_for_demo_episodes():
    show = Show(
        id="mal-1",
        title="Test",
        description="",
        episodes=[Episode("e1", "mal-1", 1, 1, "EP1", "demo.mp4")],
    )
    assert show.is_metadata_only is True


def test_is_metadata_only_false_for_real_file():
    show = Show(
        id="local-1",
        title="Test",
        description="",
        episodes=[Episode("e1", "local-1", 1, 1, "EP1", "S01E01.mp4")],
    )
    assert show.is_metadata_only is False
