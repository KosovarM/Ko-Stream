"""Family recommendations store + API."""

from __future__ import annotations

import json
from pathlib import Path

from kostream.recommendations import (
    RECOMMEND_BLOCKED_ALL_COMPLETED,
    RecommendationConflict,
    all_users_completed_manga,
    all_users_completed_show,
    clear_recommendation,
    list_family_recommendations,
    load_recommendations,
    set_recommendation,
    user_recommended_this,
)
from kostream.users import User
from kostream.user_paths import user_data_paths


def _user(uid: str, *, restricted: bool = False) -> User:
    return User(
        id=uid,
        username=uid.removeprefix("u_"),
        password_hash="x",
        role="user",
        display_name=uid,
        created_at="2026-01-01T00:00:00+00:00",
        restricted=restricted,
    )


def _write_completed(user_data: Path, user_id: str, show_id: str, watched: int) -> None:
    paths = user_data_paths(user_id, user_data)
    paths["completed"].parent.mkdir(parents=True, exist_ok=True)
    paths["completed"].write_text(
        json.dumps({show_id: watched}, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_manga_completed(user_data: Path, user_id: str, manga_id: str, read: int) -> None:
    paths = user_data_paths(user_id, user_data)
    paths["manga_completed"].parent.mkdir(parents=True, exist_ok=True)
    paths["manga_completed"].write_text(
        json.dumps({manga_id: read}, indent=2) + "\n",
        encoding="utf-8",
    )


def test_set_recommendation_and_swap(tmp_path: Path):
    path = tmp_path / "recommendations.json"
    pick, swapped = set_recommendation(
        "u_a",
        "series",
        title="Vinland Saga",
        show_id="mal-28701",
        mal_id=28701,
        path=path,
    )
    assert swapped is False
    assert pick["show_id"] == "mal-28701"
    assert pick["title"] == "Vinland Saga"
    assert pick["mal_id"] == 28701
    assert pick["set_at"]

    try:
        set_recommendation(
            "u_a",
            "series",
            title="Other",
            show_id="mal-2",
            path=path,
        )
        assert False, "expected RecommendationConflict"
    except RecommendationConflict as exc:
        assert exc.current["show_id"] == "mal-28701"

    new_pick, swapped2 = set_recommendation(
        "u_a",
        "series",
        title="Other",
        show_id="mal-2",
        replace=True,
        path=path,
    )
    assert swapped2 is True
    assert new_pick["show_id"] == "mal-2"
    slots = load_recommendations(path)["u_a"]
    assert slots["series"]["title"] == "Other"
    assert slots["movie"] is None


def test_user_isolation(tmp_path: Path):
    path = tmp_path / "recommendations.json"
    set_recommendation(
        "u_a",
        "series",
        title="A pick",
        show_id="mal-1",
        path=path,
    )
    set_recommendation(
        "u_b",
        "series",
        title="B pick",
        show_id="mal-2",
        path=path,
    )
    data = load_recommendations(path)
    assert data["u_a"]["series"]["show_id"] == "mal-1"
    assert data["u_b"]["series"]["show_id"] == "mal-2"


def test_clear_recommendation(tmp_path: Path):
    path = tmp_path / "recommendations.json"
    set_recommendation(
        "u_a",
        "manga",
        title="Comic",
        manga_id="mal-manga-1",
        path=path,
    )
    assert clear_recommendation("u_a", "manga", path) is True
    assert load_recommendations(path) == {}
    assert clear_recommendation("u_a", "manga", path) is False


def test_user_recommended_this(tmp_path: Path):
    path = tmp_path / "recommendations.json"
    set_recommendation(
        "u_a",
        "series",
        title="Pick",
        show_id="mal-1",
        path=path,
    )
    assert user_recommended_this("u_a", "series", show_id="mal-1", path=path) is True
    assert user_recommended_this("u_a", "series", show_id="mal-2", path=path) is False
    assert user_recommended_this("u_b", "series", show_id="mal-1", path=path) is False


def test_all_users_completed_show_block_and_allow(tmp_path: Path):
    user_data = tmp_path / "user_data"
    users = [_user("u_a"), _user("u_b"), _user("u_restricted", restricted=True)]
    show_id = "mal-10"

    assert (
        all_users_completed_show(show_id, users, user_data, episode_total=12) is False
    )

    _write_completed(user_data, "u_a", show_id, 12)
    assert (
        all_users_completed_show(show_id, users, user_data, episode_total=12) is False
    )

    _write_completed(user_data, "u_b", show_id, 12)
    # Restricted user incomplete should not matter.
    assert (
        all_users_completed_show(show_id, users, user_data, episode_total=12) is True
    )

    # Partial progress is not completed.
    _write_completed(user_data, "u_b", show_id, 3)
    assert (
        all_users_completed_show(show_id, users, user_data, episode_total=12) is False
    )


def test_all_users_completed_show_single_user(tmp_path: Path):
    user_data = tmp_path / "user_data"
    users = [_user("u_solo")]
    show_id = "mal-99"
    assert all_users_completed_show(show_id, users, user_data, episode_total=1) is False
    _write_completed(user_data, "u_solo", show_id, 1)
    assert all_users_completed_show(show_id, users, user_data, episode_total=1) is True


def test_all_users_completed_manga(tmp_path: Path):
    user_data = tmp_path / "user_data"
    users = [_user("u_a"), _user("u_b")]
    manga_id = "mal-manga-5"
    assert (
        all_users_completed_manga(manga_id, users, user_data, chapter_total=10) is False
    )
    _write_manga_completed(user_data, "u_a", manga_id, 10)
    _write_manga_completed(user_data, "u_b", manga_id, 10)
    assert (
        all_users_completed_manga(manga_id, users, user_data, chapter_total=10) is True
    )


def test_list_family_includes_display_name(tmp_path: Path):
    path = tmp_path / "recommendations.json"
    set_recommendation(
        "u_sister",
        "movie",
        title="Your Name",
        show_id="mal-32281",
        path=path,
    )
    users = [
        User(
            id="u_sister",
            username="sister",
            password_hash="x",
            role="user",
            display_name="Sister",
            created_at="2026-01-01T00:00:00+00:00",
        )
    ]
    groups = list_family_recommendations(path, users=users)
    assert len(groups) == 1
    assert groups[0]["display_name"] == "Sister"
    assert groups[0]["username"] == "sister"
    assert groups[0]["picks"][0]["title"] == "Your Name"
    assert groups[0]["picks"][0]["kind"] == "movie"


def test_api_set_swap_isolation_and_homepage(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOSTREAM_CSRF", "0")
    from kostream.app import create_app
    from conftest import add_test_user, bootstrap_test_users, login_client

    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    rec_path = tmp_path / "recommendations.json"
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    add_test_user(users, "sister", "sisterpass", role="user")

    app = create_app(
        media_root=media,
        catalog_path=catalog,
        recommendations_path=rec_path,
        users_path=users,
        user_data_base=user_data,
    )
    client_a = app.test_client()
    login_client(client_a)

    r1 = client_a.post(
        "/api/recommendations",
        json={
            "kind": "series",
            "show_id": "mal-1",
            "title": "Master pick",
            "mal_id": 1,
        },
    )
    assert r1.status_code == 200
    assert r1.get_json()["ok"] is True

    r_conflict = client_a.post(
        "/api/recommendations",
        json={
            "kind": "series",
            "show_id": "mal-99",
            "title": "Replacement",
        },
    )
    assert r_conflict.status_code == 409
    body = r_conflict.get_json()
    assert body["needs_swap"] is True
    assert body["current"]["show_id"] == "mal-1"

    r_swap = client_a.post(
        "/api/recommendations",
        json={
            "kind": "series",
            "show_id": "mal-99",
            "title": "Replacement",
            "replace": True,
        },
    )
    assert r_swap.status_code == 200
    assert r_swap.get_json()["swapped"] is True

    client_b = app.test_client()
    login_client(client_b, username="sister", password="sisterpass")
    r_b = client_b.post(
        "/api/recommendations",
        json={
            "kind": "series",
            "show_id": "mal-2",
            "title": "Sister pick",
        },
    )
    assert r_b.status_code == 200
    data = load_recommendations(rec_path)
    assert data["u_testuser"]["series"]["show_id"] == "mal-99"
    assert data["u_sister"]["series"]["show_id"] == "mal-2"

    home = client_b.get("/")
    assert home.status_code == 200
    html = home.get_data(as_text=True)
    assert "Recommended by other Users" in html
    assert "Sister pick" in html
    assert "Replacement" in html
    # Recommender labels (display_name defaults to username)
    assert "sister" in html.lower()
    assert "testuser" in html.lower()

    cleared = client_b.delete("/api/recommendations/series")
    assert cleared.status_code == 200
    data_after = load_recommendations(rec_path)
    assert "u_sister" not in data_after or data_after["u_sister"]["series"] is None
    assert data_after["u_testuser"]["series"]["show_id"] == "mal-99"


def test_api_remove_own_recommendation_and_block_all_completed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOSTREAM_CSRF", "0")
    from kostream.app import create_app
    from conftest import add_test_user, bootstrap_test_users, login_client

    catalog = tmp_path / "selected.json"
    catalog.write_text(
        json.dumps(
            {
                "shows": [
                    {
                        "id": "mal-42",
                        "title": "Done Show",
                        "mal_id": 42,
                        "media_type": "tv",
                        "episode_count": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    rec_path = tmp_path / "recommendations.json"
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    add_test_user(users, "sister", "sisterpass", role="user")

    app = create_app(
        media_root=media,
        catalog_path=catalog,
        recommendations_path=rec_path,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)

    # Allow recommend while someone has not completed.
    ok = client.post(
        "/api/recommendations",
        json={"kind": "series", "show_id": "mal-42", "title": "Done Show", "mal_id": 42},
    )
    assert ok.status_code == 200

    show_page = client.get("/show/mal-42")
    assert show_page.status_code == 200
    html = show_page.get_data(as_text=True)
    assert "Remove recommendation" in html
    assert 'data-recommended="1"' in html

    removed = client.delete("/api/recommendations/series")
    assert removed.status_code == 200
    assert load_recommendations(rec_path) == {}

    show_after = client.get("/show/mal-42")
    assert show_after.status_code == 200
    html_after = show_after.get_data(as_text=True)
    assert 'data-recommended="0"' in html_after
    assert 'id="btn-recommend"' in html_after
    # Button label (not the JS helper strings) should be Recommend again.
    assert '>↻ Recommend</button>' in html_after

    # Both non-restricted users completed → block.
    _write_completed(user_data, "u_testuser", "mal-42", 1)
    _write_completed(user_data, "u_sister", "mal-42", 1)
    blocked = client.post(
        "/api/recommendations",
        json={"kind": "series", "show_id": "mal-42", "title": "Done Show", "mal_id": 42},
    )
    assert blocked.status_code == 400
    assert blocked.get_json()["error"] == RECOMMEND_BLOCKED_ALL_COMPLETED

    blocked_page = client.get("/show/mal-42")
    assert blocked_page.status_code == 200
    blocked_html = blocked_page.get_data(as_text=True)
    assert "Everyone has already completed this." in blocked_html
    assert 'data-blocked="1"' in blocked_html
    assert 'id="btn-recommend"' in blocked_html
    assert "disabled" in blocked_html


def test_manga_recommend_fills_poster_and_homepage_resolves_cover(
    tmp_path: Path, monkeypatch
):
    """Manga picks without poster_url still get a cover on the homepage."""
    monkeypatch.setenv("KOSTREAM_CSRF", "0")
    from kostream.app import create_app
    from conftest import bootstrap_test_users, login_client

    # Minimal local-only manga (no MAL poster_url).
    manga_root = tmp_path / "manga"
    title_dir = manga_root / "Dice"
    ch = title_dir / "Chapter 01"
    ch.mkdir(parents=True)
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415408d763f8ffff3f0005fe02fea5725f160000000049454e44ae426082"
    )
    (ch / "01.png").write_bytes(png)

    manga_catalog = tmp_path / "manga_selected.json"
    manga_catalog.write_text('{"titles": []}', encoding="utf-8")
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    rec_path = tmp_path / "recommendations.json"
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)

    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
        recommendations_path=rec_path,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)

    # Client omits poster_url — API should fill from local cover.
    r = client.post(
        "/api/recommendations",
        json={
            "kind": "manga",
            "manga_id": "dir-dice",
            "title": "Dice",
        },
    )
    assert r.status_code == 200
    pick = r.get_json()["recommendation"]
    assert pick["manga_id"] == "dir-dice"
    assert pick["poster_url"]
    assert "/manga-page/dir-dice/" in pick["poster_url"]

    # Old JSON without poster_url: homepage still resolves cover at display time.
    rec_path.write_text(
        json.dumps(
            {
                "u_testuser": {
                    "series": None,
                    "movie": None,
                    "manga": {
                        "title": "Dice",
                        "manga_id": "dir-dice",
                        "set_at": "2026-01-01T00:00:00+00:00",
                    },
                    "manhwa": None,
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    stored = load_recommendations(rec_path)["u_testuser"]["manga"]
    assert not stored.get("poster_url")

    home = client.get("/")
    assert home.status_code == 200
    html = home.get_data(as_text=True)
    assert "Recommended by other Users" in html
    assert "Dice" in html
    assert "/manga-page/dir-dice/" in html
    assert "card-poster-img" in html
