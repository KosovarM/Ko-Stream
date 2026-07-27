"""Tests for media request wishlist store (upsert / dedupe)."""

from __future__ import annotations

from pathlib import Path

from kostream.models import Episode, Show, slugify
from kostream.manga import MangaChapter, MangaTitle
from kostream.requests_store import (
    KIND_SERIES,
    clear_fulfilled_requests,
    has_request,
    load_requests,
    manga_needs_request,
    remove_request,
    show_needs_request,
    upsert_request,
)


def test_upsert_dedupes_same_title(tmp_path: Path):
    path = tmp_path / "requests.json"
    first, created = upsert_request(
        kind="series",
        media_id="mal-1",
        title="Demo",
        path=path,
        local_count=0,
        expected_count=12,
    )
    assert created is True
    assert first["id"] == "series:mal-1"

    second, created2 = upsert_request(
        kind="series",
        media_id="mal-1",
        title="Demo Updated",
        path=path,
        local_count=3,
        expected_count=12,
        poster_url="https://example.com/p.jpg",
    )
    assert created2 is False
    assert second["title"] == "Demo Updated"
    assert second["local_count"] == 3
    assert second["poster_url"] == "https://example.com/p.jpg"

    rows = load_requests(path)
    assert len(rows) == 1
    assert rows[0]["id"] == "series:mal-1"


def test_remove_request(tmp_path: Path):
    path = tmp_path / "requests.json"
    upsert_request(kind="manga", media_id="mal-9", title="M", path=path)
    assert remove_request("manga:mal-9", path) is True
    assert load_requests(path) == []
    assert remove_request("manga:mal-9", path) is False


def test_show_needs_request_when_incomplete():
    show = Show(
        id="mal-1",
        title="Demo",
        description="",
        episodes=[
            Episode("e1", "mal-1", 1, 1, "Ep 1", "demo.mp4"),
            Episode("e2", "mal-1", 1, 2, "Ep 2", "S01E02.mp4"),
        ],
    )
    assert show_needs_request(show) is True

    complete = Show(
        id="mal-2",
        title="Done",
        description="",
        episodes=[
            Episode("e1", "mal-2", 1, 1, "Ep 1", "S01E01.mp4"),
        ],
    )
    assert show_needs_request(complete) is False


def test_show_needs_request_airing_only_when_no_local():
    # Airing + 0 local episodes → allow Request
    airing_empty = Show(
        id="mal-air",
        title="Airing",
        description="",
        media_type="tv",
        type_label="TV",
        anime_status="currently_airing",
        list_status="watching",
        episodes=[
            Episode("e1", "mal-air", 1, 1, "Ep 1", "demo.mp4"),
            Episode("e2", "mal-air", 1, 2, "Ep 2", "demo.mp4"),
        ],
    )
    assert show_needs_request(airing_empty) is True

    # Airing + ≥1 local episode → hide Request (partial downloads expected)
    airing_partial = Show(
        id="mal-air-partial",
        title="Airing Partial",
        description="",
        media_type="tv",
        type_label="TV",
        anime_status="currently_airing",
        list_status="watching",
        episodes=[
            Episode("e1", "mal-air-partial", 1, 1, "Ep 1", "S01E01.mp4"),
            Episode("e2", "mal-air-partial", 1, 2, "Ep 2", "demo.mp4"),
        ],
    )
    assert show_needs_request(airing_partial) is False

    finished = Show(
        id="mal-fin",
        title="Finished",
        description="",
        media_type="tv",
        type_label="TV",
        anime_status="finished_airing",
        list_status="watching",
        episodes=[
            Episode("e1", "mal-fin", 1, 1, "Ep 1", "demo.mp4"),
            Episode("e2", "mal-fin", 1, 2, "Ep 2", "demo.mp4"),
        ],
    )
    assert show_needs_request(finished) is True

    # Movies stay eligible even if MAL marks currently_airing
    movie = Show(
        id="mal-mov",
        title="Movie",
        description="",
        media_type="movie",
        type_label="Movie",
        anime_status="currently_airing",
        list_status="watching",
        episodes=[Episode("e1", "mal-mov", 1, 1, "Movie", "demo.mp4")],
    )
    assert show_needs_request(movie) is True


def test_manga_needs_request_vs_mal_total():
    incomplete = MangaTitle(
        id="mal-m1",
        title="Comic",
        folder="Comic",
        chapters=[
            MangaChapter("c1", "Ch 1", 10, "dir", "1"),
        ],
        num_chapters_mal=20,
    )
    assert manga_needs_request(incomplete) is True

    complete = MangaTitle(
        id="mal-m2",
        title="Full",
        folder="Full",
        chapters=[
            MangaChapter("c1", "Ch 1", 10, "dir", "1"),
            MangaChapter("c2", "Ch 2", 10, "dir", "2"),
        ],
        num_chapters_mal=2,
    )
    assert manga_needs_request(complete) is False


def test_has_request(tmp_path: Path):
    path = tmp_path / "requests.json"
    upsert_request(kind="series", media_id="mal-1", title="Demo", path=path)
    assert has_request("series", "mal-1", path) is True
    assert has_request("series", "mal-2", path) is False


def test_clear_fulfilled_requests_removes_complete_shows(tmp_path: Path):
    media = tmp_path / "media" / "shows"
    show_dir = media / "Complete Show"
    show_dir.mkdir(parents=True)
    (show_dir / "S01E01.mp4").write_bytes(b"x")

    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")

    req_path = tmp_path / "requests.json"
    complete_id = slugify("Complete Show")
    upsert_request(
        kind="series",
        media_id=complete_id,
        title="Complete Show",
        path=req_path,
        local_count=0,
        expected_count=1,
    )
    upsert_request(
        kind="series",
        media_id="missing-show",
        title="Still Missing",
        path=req_path,
        local_count=0,
        expected_count=12,
    )

    removed = clear_fulfilled_requests(
        path=req_path,
        media_root=media,
        catalog_path=catalog,
        manga_root=tmp_path / "manga",
        manga_catalog_path=tmp_path / "manga_selected.json",
    )
    assert removed == 1
    left = load_requests(req_path)
    assert len(left) == 1
    assert left[0]["media_id"] == "missing-show"


def test_api_create_dedupes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOSTREAM_CSRF", "0")
    from kostream.app import create_app

    from conftest import bootstrap_test_users, login_client

    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    req_path = tmp_path / "requests.json"
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        requests_path=req_path,
        users_path=users,
        user_data_base=user_data,
    )
    client = app.test_client()
    login_client(client)

    payload = {
        "kind": KIND_SERIES,
        "media_id": "mal-42",
        "title": "Askeladd",
        "local_count": 0,
        "expected_count": 24,
    }
    r1 = client.post("/api/requests", json=payload)
    assert r1.status_code == 200
    assert r1.get_json()["created"] is True

    r2 = client.post("/api/requests", json=payload)
    assert r2.status_code == 200
    assert r2.get_json()["created"] is False
    assert len(load_requests(req_path)) == 1

    rid = r1.get_json()["request"]["id"]
    d = client.delete(f"/api/requests/{rid}")
    assert d.status_code == 200
    assert load_requests(req_path) == []
