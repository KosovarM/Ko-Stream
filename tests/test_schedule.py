"""Weekly schedule from MAL broadcast times."""

from datetime import datetime, timedelta, timezone

from kostream.models import Show
from kostream.schedule import build_weekly_schedule, jst_broadcast_to_local

_JST = timezone(timedelta(hours=9))


def test_jst_broadcast_converts():
    ref = datetime(2026, 7, 23, 12, 0, tzinfo=_JST)  # Thursday
    result = jst_broadcast_to_local("thursday", "19:30", reference=ref)
    assert result is not None
    local_day, local_time = result
    assert local_day in {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
    assert ":" in local_time


def test_jst_late_night_can_shift_weekday():
    ref = datetime(2026, 7, 26, 12, 0, tzinfo=_JST)  # Sunday
    result = jst_broadcast_to_local("sunday", "23:30", reference=ref)
    assert result is not None


def test_build_weekly_schedule_seven_days():
    shows = [
        Show(
            id="mal-1",
            title="Airing A",
            description="",
            anime_status="currently_airing",
            list_status="watching",
            broadcast_day="wednesday",
            broadcast_time="22:00",
            poster_url=None,
        ),
        Show(
            id="mal-2",
            title="No time",
            description="",
            anime_status="currently_airing",
            list_status="watching",
        ),
        Show(
            id="mal-3",
            title="Finished",
            description="",
            anime_status="finished_airing",
            list_status="completed",
            broadcast_day="monday",
            broadcast_time="12:00",
        ),
    ]
    days, unknown = build_weekly_schedule(shows)
    assert len(days) == 7
    assert {d.key for d in days} == {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
    assert any(e.title == "Airing A" for d in days for e in d.entries)
    assert len(unknown) == 1
    assert unknown[0].title == "No time"


def test_schedule_page_ok(tmp_path):
    from kostream.app import create_app

    media = tmp_path / "shows"
    media.mkdir()
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    app = create_app(media_root=media, catalog_path=catalog)
    client = app.test_client()
    resp = client.get("/schedule")
    assert resp.status_code == 200
    assert b"Schedule" in resp.data
    assert b"mode=anime" in resp.data
    assert b"mode=manga" in resp.data
    assert b"mode=manhwa" in resp.data
    assert b"is-active" in resp.data


def test_schedule_modes_split_manga_and_manhwa(tmp_path, monkeypatch):
    from kostream.app import create_app
    from kostream import mal as mal_mod
    from kostream.mal import MalMangaEntry
    from kostream.manga_catalog import MangaCatalogEntry, MangaCatalogState, save_manga_catalog

    media = tmp_path / "shows"
    media.mkdir()
    manga_root = tmp_path / "manga"
    manga_root.mkdir()
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    manga_catalog = tmp_path / "manga_selected.json"
    save_manga_catalog(
        MangaCatalogState(
            titles=[
                MangaCatalogEntry(
                    id="mal-manga-1",
                    enabled=True,
                    source="mal",
                    mal_id=1,
                    title="Solo Leveling",
                    media_type="manhwa",
                ),
                MangaCatalogEntry(
                    id="mal-manga-2",
                    enabled=True,
                    source="mal",
                    mal_id=2,
                    title="Berserk",
                    media_type="manga",
                ),
            ]
        ),
        manga_catalog,
    )
    cache = tmp_path / "manga_cache"
    monkeypatch.setattr(mal_mod, "MANGA_CACHE_DIR", cache)
    mal_mod.write_cached_manga(
        MalMangaEntry(
            mal_id=1,
            title="Solo Leveling",
            synopsis="",
            poster_url=None,
            genres=[],
            num_volumes=0,
            num_chapters=10,
            list_status="reading",
            num_volumes_read=0,
            num_chapters_read=1,
            manga_status="currently_publishing",
            score=0,
            mean_score=None,
            media_type="manhwa",
        )
    )
    mal_mod.write_cached_manga(
        MalMangaEntry(
            mal_id=2,
            title="Berserk",
            synopsis="",
            poster_url=None,
            genres=[],
            num_volumes=40,
            num_chapters=100,
            list_status="reading",
            num_volumes_read=0,
            num_chapters_read=1,
            manga_status="currently_publishing",
            score=0,
            mean_score=None,
            media_type="manga",
        )
    )
    app = create_app(
        media_root=media,
        catalog_path=catalog,
        manga_root=manga_root,
        manga_catalog_path=manga_catalog,
    )
    client = app.test_client()

    manga = client.get("/schedule?mode=manga")
    assert manga.status_code == 200
    assert b"Berserk" in manga.data
    assert b"Solo Leveling" not in manga.data
    assert b"mangalist" in manga.data

    manhwa = client.get("/schedule?mode=manhwa")
    assert manhwa.status_code == 200
    assert b"Solo Leveling" in manhwa.data
    assert b"Berserk" not in manhwa.data
    assert b"manhwa list" in manhwa.data

    anime = client.get("/schedule?mode=anime")
    assert anime.status_code == 200
    assert b"Berserk" not in anime.data
    assert b"Solo Leveling" not in anime.data
    assert b"episode drop day" in anime.data
