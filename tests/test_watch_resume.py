from kostream.watch_progress import (
    resume_seconds_for_episode,
    should_persist_watch_progress,
)


def test_resume_seconds_skips_completed_and_past_threshold():
    entry = {"seconds": 120.0, "duration": 600.0}
    assert resume_seconds_for_episode(entry) == 120.0
    assert resume_seconds_for_episode(entry, is_completed=True) == 0.0
    assert resume_seconds_for_episode({"seconds": 540.0, "duration": 600.0}) == 0.0
    assert resume_seconds_for_episode({"seconds": 0}) == 0.0


def test_should_persist_watch_progress_rules():
    assert should_persist_watch_progress(100.0, 600.0) is True
    assert should_persist_watch_progress(540.0, 600.0) is False
    assert should_persist_watch_progress(100.0, 600.0, is_completed=True) is False
    assert should_persist_watch_progress(0.0, 600.0) is False
