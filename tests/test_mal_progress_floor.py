"""B1: MAL progress sync is upward-only (never overwrite MAL downward)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from kostream.mal import MalAnimeEntry, update_episodes_watched
from kostream.models import Episode, Show
from kostream.watch_progress import apply_mal_metadata, load_completed, reconcile_anime_progress


def _cached(mal_id: int, watched: int) -> MalAnimeEntry:
    return MalAnimeEntry(
        mal_id=mal_id,
        title="Test",
        synopsis="",
        poster_url=None,
        genres=[],
        num_episodes=12,
        list_status="watching",
        num_episodes_watched=watched,
        anime_status="currently_airing",
        score=0,
        mean_score=None,
    )


def test_update_episodes_watched_never_below_cache_floor(monkeypatch, tmp_path):
    sent: list[dict] = []

    def fake_api(token, path, form, method="POST"):
        sent.append(dict(form))
        return b"{}"

    monkeypatch.setattr("kostream.mal.get_valid_access_token", lambda cfg, user_id: "tok")
    monkeypatch.setattr(
        "kostream.mal.get_anime_list_row",
        lambda user_id, mal_id: {"num_episodes_watched": 8, "list_status": "watching", "score": 0},
    )
    monkeypatch.setattr("kostream.mal.upsert_anime_list_row", lambda *a, **k: {})
    monkeypatch.setattr("kostream.mal._api_form_raw", fake_api)

    cfg = MagicMock()
    update_episodes_watched(cfg, 21, 3, user_id="u_test")  # try to send below floor
    assert sent
    assert sent[0]["num_watched_episodes"] == "8"


def test_apply_mal_metadata_keeps_higher_local():
    show = Show(
        id="s",
        title="T",
        description="",
        episodes_watched=10,
        episodes=[],
    )
    apply_mal_metadata(show, _cached(1, 4))
    assert show.episodes_watched == 10


def test_reconcile_raises_local_when_mal_ahead(tmp_path, monkeypatch):
    completed = tmp_path / "completed.json"
    completed.write_text("{}", encoding="utf-8")
    show = Show(
        id="show-a",
        title="A",
        description="",
        mal_id=99,
        episodes_watched=2,
        episodes=[
            Episode(f"show-a-e{n}", "show-a", 1, n, f"Ep {n}", "demo.mp4")
            for n in range(1, 6)
        ],
    )
    monkeypatch.setattr(
        "kostream.mal.load_cached_anime", lambda mid: _cached(99, 4)
    )
    merged = reconcile_anime_progress(show, completed_path=completed, mal_cfg=None)
    assert merged == 4
    assert load_completed(completed)["show-a"] == 4
    assert show.episodes_watched == 4


def test_reconcile_patches_mal_upward_only(tmp_path, monkeypatch):
    completed = tmp_path / "completed.json"
    completed.write_text('{"show-b": 7}', encoding="utf-8")
    show = Show(
        id="show-b",
        title="B",
        description="",
        mal_id=42,
        episodes_watched=7,
        episodes=[
            Episode(f"show-b-e{n}", "show-b", 1, n, f"Ep {n}", "demo.mp4")
            for n in range(1, 13)
        ],
    )
    monkeypatch.setattr(
        "kostream.mal.load_cached_anime", lambda mid: _cached(42, 3)
    )
    patched: list[tuple] = []

    def fake_update(cfg, mal_id, num, status=None, *, user_id):
        patched.append((mal_id, num, status, user_id))

    monkeypatch.setattr("kostream.mal.update_episodes_watched", fake_update)
    cfg = MagicMock()
    merged = reconcile_anime_progress(
        show, completed_path=completed, mal_cfg=cfg, user_id="u_test"
    )
    assert merged == 7
    assert patched == [(42, 7, None, "u_test")]
