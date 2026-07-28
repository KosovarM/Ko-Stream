from kostream.watch_progress import (
    episode_in_progress,
    format_duration,
    format_episode_progress,
    resume_seconds_for_episode,
    should_persist_watch_progress,
)
from kostream.models import Episode, Show
from pathlib import Path


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


def test_format_duration():
    assert format_duration(0) == "0:00"
    assert format_duration(59.4) == "0:59"
    assert format_duration(120) == "2:00"
    assert format_duration(3661) == "1:01:01"


def test_format_episode_progress():
    assert format_episode_progress({"seconds": 120, "duration": 1460}) == "2:00/24:20"
    assert format_episode_progress({"seconds": 90}) == "1:30"
    assert format_episode_progress(None) is None
    assert format_episode_progress({"seconds": 0}) is None


def _show(ep_count: int = 3) -> Show:
    show_id = "test-show"
    return Show(
        id=show_id,
        title="Test",
        description="",
        episodes=[
            Episode(f"{show_id}-e{n}", show_id, 1, n, f"Ep {n}", "S01E0{n}.mp4")
            for n in range(1, ep_count + 1)
        ],
    )


def test_episode_in_progress():
    show = _show()
    ep = show.episodes[1]
    progress = {ep.id: {"seconds": 120.0, "duration": 600.0}}
    assert episode_in_progress(show, ep, progress) is True
    assert episode_in_progress(show, ep, progress, completed={show.id: 2}) is False
    assert episode_in_progress(show, ep, {ep.id: {"seconds": 540, "duration": 600}}) is False


def test_api_progress_saves_and_clears_at_completion(tmp_path: Path):
    from kostream.app import create_app
    from kostream.catalog import CatalogEntry, CatalogState, save_catalog
    from kostream.library import load_progress
    from kostream.user_paths import user_data_paths
    from tests.conftest import bootstrap_test_users, login_client

    media = tmp_path / "media" / "shows"
    show_dir = media / "Demo Show"
    show_dir.mkdir(parents=True)
    (show_dir / "S01E01.mp4").write_bytes(b"x")

    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="demo-show",
                    enabled=True,
                    source="local",
                    folder="Demo Show",
                    title="Demo Show",
                )
            ]
        ),
        catalog,
    )
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)

    resp = client.post(
        "/api/progress",
        json={
            "show_id": "demo-show",
            "episode_id": "demo-show-s01e01",
            "seconds": 120.0,
            "duration": 1460.0,
        },
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "saved": True}

    paths = user_data_paths("u_testuser", user_data)
    saved = load_progress(paths["progress"])
    assert saved["demo-show-s01e01"] == {"seconds": 120.0, "duration": 1460.0}

    resp_clear = client.post(
        "/api/progress",
        json={
            "show_id": "demo-show",
            "episode_id": "demo-show-s01e01",
            "seconds": 1400.0,
            "duration": 1460.0,
        },
    )
    assert resp_clear.status_code == 200
    assert resp_clear.get_json() == {"ok": True, "saved": False}
    assert "demo-show-s01e01" not in load_progress(paths["progress"])


def test_show_page_displays_episode_progress(tmp_path: Path):
    from kostream.app import create_app
    from kostream.catalog import CatalogEntry, CatalogState, save_catalog
    from kostream.library import load_progress, save_progress
    from kostream.user_paths import user_data_paths
    from tests.conftest import bootstrap_test_users, login_client

    media = tmp_path / "media" / "shows"
    show_dir = media / "Demo Show"
    show_dir.mkdir(parents=True)
    (show_dir / "S01E01.mp4").write_bytes(b"x")
    (show_dir / "S01E02.mp4").write_bytes(b"x")

    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="demo-show",
                    enabled=True,
                    source="local",
                    folder="Demo Show",
                    title="Demo Show",
                )
            ]
        ),
        catalog,
    )
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )
    paths = user_data_paths("u_testuser", user_data)
    save_progress(
        paths["progress"],
        {"demo-show-s01e01": {"seconds": 120.0, "duration": 1460.0}},
    )

    client = app.test_client()
    login_client(client)
    resp = client.get("/show/demo-show")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2:00/24:20" in body
    assert "ep-progress-badge" in body
    assert "▶ Next" not in body or body.index("2:00/24:20") < body.index("▶ Next")
