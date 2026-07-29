from unittest.mock import patch

from kostream.catalog import CatalogEntry, CatalogState, load_catalog, save_catalog
from kostream.mal import MalAnimeEntry, MalMangaEntry, sync_animelist_to_catalog, sync_mangalist_to_catalog
from kostream.manga_catalog import load_manga_catalog


def test_sync_animelist_upserts_without_removing_others(tmp_path, monkeypatch):
    """Sync enriches the shared catalog; titles not on this user's list stay put."""
    from kostream import mal as mal_mod

    catalog_path = tmp_path / "selected.json"
    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path / "mal")
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(id="local-1", enabled=True, source="local", folder="Anime"),
                CatalogEntry(
                    id="mal-21",
                    enabled=False,
                    source="mal",
                    folder="One Piece Local",
                    anilist_id=21,
                    mal_id=21,
                    title="Old MAL",
                    added_at="2026-01-15T10:00:00Z",
                ),
                CatalogEntry(
                    id="mal-31240",
                    enabled=True,
                    source="mal",
                    folder="Re Zero Season 1",
                    mal_id=31240,
                    title="Re:Zero",
                    added_at="2026-02-01T00:00:00Z",
                ),
                CatalogEntry(id="mal-99", enabled=True, source="mal", mal_id=99, title="Other User Show"),
            ]
        ),
        catalog_path,
    )

    # Smaller list (e.g. Blerta): only One Piece — must not wipe Re:Zero / mal-99.
    fake_entries = [
        MalAnimeEntry(
            mal_id=21,
            title="One Piece",
            synopsis="Pirates.",
            poster_url="https://example.com/op.jpg",
            genres=["Action"],
            num_episodes=1000,
            list_status="watching",
            num_episodes_watched=500,
            anime_status="currently_airing",
            score=10,
            mean_score=8.7,
        ),
        MalAnimeEntry(
            mal_id=20,
            title="Naruto",
            synopsis="Ninja.",
            poster_url="https://example.com/n.jpg",
            genres=["Action"],
            num_episodes=220,
            list_status="completed",
            num_episodes_watched=220,
            anime_status="finished_airing",
            score=8,
            mean_score=8.0,
        ),
    ]

    class FakeCfg:
        client_id = "x"
        client_secret = "y"
        redirect_uri = "http://127.0.0.1:5001/auth/mal/callback"

    with patch("kostream.mal.get_valid_access_token", return_value="token"):
        with patch("kostream.mal.fetch_animelist", return_value=fake_entries):
            with patch("kostream.mal.enrich_catalog_mal_details", return_value=0):
                count = sync_animelist_to_catalog(FakeCfg(), catalog_path, user_id="u_blerta")

    assert count == 2
    state = load_catalog(catalog_path)
    ids = {s.id for s in state.shows}
    assert "local-1" in ids
    assert "mal-21" in ids
    assert "mal-31240" in ids
    assert "mal-99" in ids
    assert "mal-20" in ids

    mal21 = state.get("mal-21")
    assert mal21 is not None
    assert mal21.added_at == "2026-01-15T10:00:00Z"
    assert mal21.folder == "One Piece Local"
    assert mal21.anilist_id == 21
    assert mal21.enabled is False
    assert mal21.title == "One Piece"

    rezero = state.get("mal-31240")
    assert rezero is not None
    assert rezero.folder == "Re Zero Season 1"
    assert rezero.enabled is True
    assert rezero.title == "Re:Zero"
    assert rezero.added_at == "2026-02-01T00:00:00Z"

    other = state.get("mal-99")
    assert other is not None
    assert other.enabled is True
    assert other.title == "Other User Show"

    new_show = state.get("mal-20")
    assert new_show is not None
    assert new_show.enabled is True
    assert new_show.title == "Naruto"
    assert new_show.folder is None

    import json

    cache_raw = json.loads((tmp_path / "cache" / "21.json").read_text(encoding="utf-8"))
    assert "num_episodes_watched" not in cache_raw
    assert "list_status" not in cache_raw
    overlay = mal_mod.load_anime_list_state("u_blerta")
    assert overlay["21"]["num_episodes_watched"] == 500
    assert overlay["21"]["score"] == 10
    assert overlay["20"]["list_status"] == "completed"


def test_sync_mangalist_to_catalog(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from kostream.manga_catalog import MangaCatalogEntry, MangaCatalogState, save_manga_catalog

    media = tmp_path / "manga"
    (media / "Berserk").mkdir(parents=True)
    catalog = tmp_path / "manga_selected.json"
    save_manga_catalog(
        MangaCatalogState(
            titles=[
                MangaCatalogEntry(
                    id="mal-manga-2",
                    enabled=False,
                    source="mal",
                    folder="Berserk",
                    mal_id=2,
                    title="Old",
                    added_at="2026-01-01T00:00:00Z",
                ),
                MangaCatalogEntry(
                    id="mal-manga-50",
                    enabled=True,
                    source="mal",
                    mal_id=50,
                    title="Gone",
                ),
            ]
        ),
        catalog,
    )
    cache = tmp_path / "manga_cache"
    monkeypatch.setattr(mal_mod, "MANGA_CACHE_DIR", cache)
    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path / "mal")

    fake = [
        MalMangaEntry(
            mal_id=2,
            title="Berserk",
            synopsis="Dark.",
            poster_url="https://example.com/b.jpg",
            genres=["Action"],
            num_volumes=40,
            num_chapters=364,
            list_status="reading",
            num_volumes_read=1,
            num_chapters_read=10,
            manga_status="currently_publishing",
            score=10,
            mean_score=9.4,
        )
    ]

    class FakeCfg:
        client_id = "x"
        client_secret = "y"
        redirect_uri = "http://127.0.0.1:5001/auth/mal/callback"

    with patch("kostream.mal.get_valid_access_token", return_value="token"):
        with patch("kostream.mal.fetch_mangalist", return_value=fake):
            count = sync_mangalist_to_catalog(
                FakeCfg(),
                user_id="u_test",
                manga_catalog_path=catalog,
                manga_media_root=media,
            )

    assert count == 1
    state = load_manga_catalog(catalog)
    ids = {t.id for t in state.titles}
    assert "mal-manga-2" in ids
    assert "mal-manga-50" not in ids
    entry = state.get("mal-manga-2")
    assert entry is not None
    assert entry.enabled is False
    assert entry.folder == "Berserk"
    assert entry.added_at == "2026-01-01T00:00:00Z"
    assert entry.title == "Berserk"
    cached = mal_mod.load_cached_manga(2)
    assert cached is not None
    assert cached.title == "Berserk"
    assert cached.num_chapters_read == 0
    overlay = mal_mod.load_manga_list_state("u_test")
    assert overlay["2"]["num_chapters_read"] == 10
    import json

    raw = json.loads((cache / "2.json").read_text(encoding="utf-8"))
    assert "list_status" not in raw
    assert "num_chapters_read" not in raw


def test_load_cached_anime(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "21.json").write_text(
        '{"mal_id":21,"title":"One Piece","synopsis":"Pirates","poster_url":"https://x/y.jpg","genres":["Action"],"num_episodes":10,"list_status":"watching","num_episodes_watched":3,"anime_status":"currently_airing","score":9,"mean_score":8.5,"episode_titles":{"1":"I\'m Luffy!"}}',
        encoding="utf-8",
    )
    item = mal_mod.load_cached_anime(21)
    assert item is not None
    assert item.title == "One Piece"
    # Shared cache ignores personal list fields (overlay owns them).
    assert item.num_episodes_watched == 0
    assert item.anime_status == "currently_airing"
    assert item.episode_titles[1] == "I'm Luffy!"


def test_ensure_episode_titles_stores_jikan_payload(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "1.json").write_text(
        '{"mal_id":1,"title":"Cowboy Bebop","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":26,"list_status":"completed","num_episodes_watched":26,'
        '"anime_status":"finished_airing","score":10,"mean_score":8.7}',
        encoding="utf-8",
    )

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                b'{"pagination":{"has_next_page":false},"data":['
                b'{"mal_id":1,"title":"Asteroid Blues"},'
                b'{"mal_id":2,"title":"Stray Dog Strut"}'
                b"]}"
            )

    with patch("kostream.mal.urlopen", return_value=FakeResp()):
        assert mal_mod.ensure_episode_titles(1) is True

    cached = mal_mod.load_cached_anime(1)
    assert cached is not None
    assert cached.episode_titles[1] == "Asteroid Blues"
    assert cached.episode_titles[2] == "Stray Dog Strut"
    assert mal_mod.episode_titles_need_fetch(1) is False


def test_fetch_episode_titles_pages_past_40(monkeypatch):
    """Long series must page beyond the old page<=40 safety limit."""
    from kostream import mal as mal_mod
    from urllib.parse import parse_qs, urlparse

    calls: list[int] = []

    class FakeResp:
        def __init__(self, page: int):
            self.page = page

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            ep = self.page
            has_next = "true" if self.page < 45 else "false"
            body = (
                '{"pagination":{"has_next_page":%s},"data":[{"mal_id":%d,"title":"Ep %d"}]}'
                % (has_next, ep, ep)
            )
            return body.encode()

    def fake_urlopen(req, timeout=20):
        qs = parse_qs(urlparse(req.full_url).query)
        page = int(qs.get("page", ["1"])[0])
        calls.append(page)
        return FakeResp(page)

    monkeypatch.setattr(mal_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)

    titles, complete = mal_mod.fetch_episode_titles(21)
    assert complete is True
    assert len(calls) == 45
    assert max(calls) == 45
    assert len(titles) == 45
    assert titles[45] == "Ep 45"


def test_fetch_episode_titles_retries_transient_http_errors(monkeypatch):
    from kostream import mal as mal_mod
    from urllib.error import HTTPError
    from io import BytesIO

    attempts = {"n": 0}
    sleeps: list[float] = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                b'{"pagination":{"has_next_page":false},"data":['
                b'{"mal_id":1,"title":"The End Start"}'
                b"]}"
            )

    def fake_urlopen(req, timeout=20):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise HTTPError(req.full_url, 504, "Gateway Time-out", hdrs=None, fp=BytesIO())
        return FakeResp()

    monkeypatch.setattr(mal_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(mal_mod.random, "uniform", lambda a, b: 0.2)

    titles, complete = mal_mod.fetch_episode_titles(31240)
    assert complete is True
    assert attempts["n"] == 2
    assert titles[1] == "The End Start"
    assert any(s >= 2.5 for s in sleeps)  # 504 backoff base + jitter


def test_fetch_episode_titles_retries_multiple_504_then_success(monkeypatch):
    """504 storms: several gateway failures then success within retry budget."""
    from kostream import mal as mal_mod
    from urllib.error import HTTPError
    from io import BytesIO

    attempts = {"n": 0}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                b'{"pagination":{"has_next_page":false},"data":['
                b'{"mal_id":1,"title":"After Storm"}'
                b"]}"
            )

    def fake_urlopen(req, timeout=20):
        attempts["n"] += 1
        if attempts["n"] <= 3:
            raise HTTPError(req.full_url, 504, "Gateway Time-out", hdrs=None, fp=BytesIO())
        return FakeResp()

    monkeypatch.setattr(mal_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(mal_mod, "JIKAN_MIN_INTERVAL", 0.0)

    titles, complete = mal_mod.fetch_episode_titles(2001)
    assert complete is True
    assert attempts["n"] == 4
    assert titles[1] == "After Storm"


def test_jikan_respects_retry_after_header(monkeypatch):
    from kostream import mal as mal_mod
    from urllib.error import HTTPError
    from email.message import EmailMessage
    from io import BytesIO

    hdrs = EmailMessage()
    hdrs["Retry-After"] = "7"
    sleeps: list[float] = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"pagination":{"has_next_page":false},"data":[]}'

    attempts = {"n": 0}

    def fake_urlopen(req, timeout=20):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise HTTPError(req.full_url, 429, "Too Many Requests", hdrs=hdrs, fp=BytesIO())
        return FakeResp()

    monkeypatch.setattr(mal_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(mal_mod.random, "uniform", lambda a, b: 0.3)
    monkeypatch.setattr(mal_mod, "JIKAN_MIN_INTERVAL", 0.0)

    mal_mod.fetch_episode_titles(1)
    assert any(abs(s - 7.55) < 0.01 for s in sleeps)  # 7 + 0.25 + 0.3 jitter


def test_ensure_episode_titles_preserves_cache_on_jikan_504(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from urllib.error import HTTPError
    from io import BytesIO
    import json

    monkeypatch.setenv("KOSTREAM_MAL_HTML_SCRAPE", "0")
    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod, "JIKAN_MIN_INTERVAL", 0.0)
    (tmp_path / "2167.json").write_text(
        '{"mal_id":2167,"title":"Clannad","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":23,"list_status":"completed","num_episodes_watched":23,'
        '"anime_status":"finished_airing","score":10,"mean_score":8.0,'
        '"episode_titles":{"1":"On the Hillside Path Where the Cherry Blossoms Flutter"},'
        '"episode_titles_incomplete":true}',
        encoding="utf-8",
    )

    def boom(req, timeout=20):
        raise HTTPError(req.full_url, 504, "Gateway Time-out", hdrs=None, fp=BytesIO())

    monkeypatch.setattr(mal_mod, "urlopen", boom)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)

    assert mal_mod.ensure_episode_titles(2167) is False
    cached = mal_mod.load_cached_anime(2167)
    assert cached is not None
    assert cached.episode_titles[1].startswith("On the Hillside")
    raw = json.loads((tmp_path / "2167.json").read_text(encoding="utf-8"))
    assert raw.get("episode_titles_incomplete") is True
    assert "episode_titles_walk_complete" not in raw


def test_ensure_episode_titles_falls_back_to_mal_site(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from urllib.error import HTTPError
    from io import BytesIO

    monkeypatch.setenv("KOSTREAM_MAL_HTML_SCRAPE", "1")
    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod, "JIKAN_MIN_INTERVAL", 0.0)
    (tmp_path / "31240.json").write_text(
        '{"mal_id":31240,"title":"Re:Zero","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":25,"list_status":"completed","num_episodes_watched":25,'
        '"anime_status":"finished_airing","score":10,"mean_score":8.2,"episode_titles":{}}',
        encoding="utf-8",
    )

    def boom(req, timeout=20):
        raise HTTPError(req.full_url, 504, "Gateway Time-out", hdrs=None, fp=BytesIO())

    monkeypatch.setattr(mal_mod, "urlopen", boom)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        mal_mod,
        "fetch_episode_titles_from_mal_site",
        lambda _mid: ({1: "The End of the Beginning and the Beginning of the End", 2: "Reunion with the Witch"}, True),
    )

    assert mal_mod.ensure_episode_titles(31240) is True
    cached = mal_mod.load_cached_anime(31240)
    assert cached is not None
    assert cached.episode_titles[1].startswith("The End of the Beginning")


def test_ensure_episode_titles_skips_html_scrape_when_disabled(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from urllib.error import HTTPError
    from io import BytesIO
    import json

    monkeypatch.setenv("KOSTREAM_MAL_HTML_SCRAPE", "0")
    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod, "JIKAN_MIN_INTERVAL", 0.0)
    (tmp_path / "1.json").write_text(
        '{"mal_id":1,"title":"X","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":2,"list_status":"watching","num_episodes_watched":0,'
        '"anime_status":"finished_airing","score":0,"mean_score":null,"episode_titles":{}}',
        encoding="utf-8",
    )

    def boom(req, timeout=20):
        raise HTTPError(req.full_url, 504, "Gateway Time-out", hdrs=None, fp=BytesIO())

    called = {"n": 0}

    def scrape(_mid):
        called["n"] += 1
        return {1: "Nope"}, True

    monkeypatch.setattr(mal_mod, "urlopen", boom)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(mal_mod, "fetch_episode_titles_from_mal_site", scrape)

    assert mal_mod.ensure_episode_titles(1) is False
    assert called["n"] == 0
    cached = mal_mod.load_cached_anime(1)
    assert cached is not None
    assert cached.episode_titles == {}
    raw = json.loads((tmp_path / "1.json").read_text(encoding="utf-8"))
    assert raw.get("episode_titles_incomplete") is True


def test_mal_site_parser_unescapes_entities():
    from kostream import mal as mal_mod

    sample = (
        '<td class="episode-title fs12">'
        '<a href="https://myanimelist.net/anime/31240/x/episode/7" class="fl-l fw-b ">'
        "Natsuki Subaru&#039;s Restart</a></td>"
    )
    hits = mal_mod.MAL_EPISODE_TITLE_RE.findall(sample)
    assert hits == [("7", "Natsuki Subaru&#039;s Restart")]
    assert mal_mod.html_lib.unescape(hits[0][1]) == "Natsuki Subaru's Restart"


def test_fetch_episode_titles_partial_on_later_page_failure(monkeypatch):
    from kostream import mal as mal_mod
    from urllib.error import HTTPError
    from urllib.parse import parse_qs, urlparse
    from io import BytesIO

    class FakeResp:
        def __init__(self, body: bytes):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.body

    def fake_urlopen(req, timeout=20):
        page = int(parse_qs(urlparse(req.full_url).query).get("page", ["1"])[0])
        if page == 1:
            return FakeResp(
                b'{"pagination":{"has_next_page":true},"data":[{"mal_id":1,"title":"A"}]}'
            )
        raise HTTPError(req.full_url, 429, "Too Many Requests", hdrs=None, fp=BytesIO())

    monkeypatch.setattr(mal_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(mal_mod, "JIKAN_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(mal_mod, "JIKAN_MAX_RETRIES", 1)

    titles, complete = mal_mod.fetch_episode_titles(21)
    assert complete is False
    assert titles == {1: "A"}


def test_sync_catalog_episode_titles_reports_failed_and_skipped(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from kostream.catalog import CatalogEntry, CatalogState, save_catalog

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)
    catalog_path = tmp_path / "selected.json"

    for mid, titles, fetched, walk in (
        (1, {}, None, False),  # needs fetch → fail
        (2, {"1": "A"}, "2026-01-01T00:00:00Z", True),  # fresh → skipped
        (3, {}, None, False),  # needs fetch → succeed
    ):
        payload = {
            "mal_id": mid,
            "title": f"Show {mid}",
            "synopsis": "",
            "poster_url": None,
            "genres": [],
            "num_episodes": 12,
            "list_status": "completed",
            "num_episodes_watched": 12,
            "anime_status": "finished_airing",
            "score": 0,
            "mean_score": None,
            "episode_titles": titles,
        }
        if fetched:
            payload["episode_titles_fetched_at"] = fetched
        if walk:
            payload["episode_titles_walk_complete"] = True
        (tmp_path / f"{mid}.json").write_text(
            __import__("json").dumps(payload), encoding="utf-8"
        )

    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(id=f"mal-{mid}", enabled=True, source="mal", mal_id=mid, title=f"Show {mid}")
                for mid in (1, 2, 3)
            ]
        ),
        catalog_path,
    )

    def fake_ensure(mal_id, *, force=False):
        return mal_id == 3

    monkeypatch.setattr(mal_mod, "ensure_episode_titles", fake_ensure)
    # After "fail" for id 1, need_fetch still True (empty titles).
    result = mal_mod.sync_catalog_episode_titles(catalog_path, limit=10)
    assert result.updated == 1
    assert result.failed == 1
    assert result.skipped == 1
    assert result.attempted == 2
    assert result.last_error

def test_sync_catalog_episode_titles_prioritizes_folder_and_short(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from kostream.catalog import CatalogEntry, CatalogState, save_catalog

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)
    catalog_path = tmp_path / "selected.json"

    for mid, eps in ((21, 1000), (31240, 25), (99, 12)):
        (tmp_path / f"{mid}.json").write_text(
            __import__("json").dumps(
                {
                    "mal_id": mid,
                    "title": f"Show {mid}",
                    "synopsis": "",
                    "poster_url": None,
                    "genres": [],
                    "num_episodes": eps,
                    "list_status": "completed",
                    "num_episodes_watched": eps,
                    "anime_status": "finished_airing",
                    "score": 0,
                    "mean_score": None,
                    "episode_titles": {},
                }
            ),
            encoding="utf-8",
        )

    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(id="mal-21", enabled=True, source="mal", mal_id=21, title="One Piece"),
                CatalogEntry(
                    id="mal-31240",
                    enabled=True,
                    source="mal",
                    mal_id=31240,
                    title="Re:Zero",
                    folder="Re Zero Season 1",
                ),
                CatalogEntry(id="mal-99", enabled=True, source="mal", mal_id=99, title="Short"),
            ]
        ),
        catalog_path,
    )

    fetched_ids: list[int] = []

    def fake_ensure(mal_id, *, force=False):
        fetched_ids.append(mal_id)
        return True

    monkeypatch.setattr(mal_mod, "ensure_episode_titles", fake_ensure)
    updated = mal_mod.sync_catalog_episode_titles(catalog_path, limit=2)
    assert int(updated) == 2
    assert updated.attempted == 2
    # Folder-linked Re:Zero first, then shortest no-folder (99), One Piece last.
    assert fetched_ids == [31240, 99]


def test_episode_titles_need_fetch_when_incomplete(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    (tmp_path / "1.json").write_text(
        '{"mal_id":1,"title":"A","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":26,"list_status":"completed","num_episodes_watched":26,'
        '"anime_status":"finished_airing","score":0,"mean_score":null,'
        '"episode_titles":{"1":"Asteroid Blues"},"episode_titles_incomplete":true}',
        encoding="utf-8",
    )
    assert mal_mod.episode_titles_need_fetch(1) is True


def test_episode_titles_need_fetch_when_count_exceeds_cached(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "21.json").write_text(
        '{"mal_id":21,"title":"One Piece","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":1122,"list_status":"watching","num_episodes_watched":1000,'
        '"anime_status":"currently_airing","score":10,"mean_score":8.7,'
        '"episode_titles":{"1":"I\'m Luffy!"},"episode_titles_fetched_at":"2026-01-01T00:00:00Z"}',
        encoding="utf-8",
    )
    assert mal_mod.episode_titles_need_fetch(21) is True


def test_sync_catalog_episode_titles_skips_fresh_and_respects_limit(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from kostream.catalog import CatalogEntry, CatalogState, save_catalog

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)
    catalog_path = tmp_path / "selected.json"

    for mid, titles, fetched in (
        (1, {}, None),  # needs fetch
        (2, {"1": "A"}, "2026-01-01T00:00:00Z"),  # walk complete (accept partial)
        (3, {}, None),  # needs fetch
        (4, {}, None),  # needs fetch but over limit
    ):
        payload = {
            "mal_id": mid,
            "title": f"Show {mid}",
            "synopsis": "",
            "poster_url": None,
            "genres": [],
            "num_episodes": 12,
            "list_status": "completed",
            "num_episodes_watched": 12,
            "anime_status": "finished_airing",
            "score": 0,
            "mean_score": None,
            "episode_titles": titles,
        }
        if fetched:
            payload["episode_titles_fetched_at"] = fetched
            payload["episode_titles_walk_complete"] = True
        (tmp_path / f"{mid}.json").write_text(
            __import__("json").dumps(payload), encoding="utf-8"
        )

    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(id=f"mal-{mid}", enabled=True, source="mal", mal_id=mid, title=f"Show {mid}")
                for mid in (1, 2, 3, 4)
            ]
        ),
        catalog_path,
    )

    fetched_ids: list[int] = []

    def fake_ensure(mal_id, *, force=False):
        fetched_ids.append(mal_id)
        return True

    monkeypatch.setattr(mal_mod, "ensure_episode_titles", fake_ensure)
    updated = mal_mod.sync_catalog_episode_titles(catalog_path, limit=2)
    assert int(updated) == 2
    assert fetched_ids == [1, 3]


def test_sync_catalog_episode_titles_skips_disabled(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from kostream.catalog import CatalogEntry, CatalogState, save_catalog

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)
    catalog_path = tmp_path / "selected.json"
    (tmp_path / "1.json").write_text(
        '{"mal_id":1,"title":"A","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":1,"list_status":"completed","num_episodes_watched":1,'
        '"anime_status":"finished_airing","score":0,"mean_score":null,"episode_titles":{}}',
        encoding="utf-8",
    )
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(id="mal-1", enabled=False, source="mal", mal_id=1, title="A"),
            ]
        ),
        catalog_path,
    )
    monkeypatch.setattr(mal_mod, "ensure_episode_titles", lambda *_a, **_k: True)
    assert int(mal_mod.sync_catalog_episode_titles(catalog_path)) == 0


def test_episode_titles_need_fetch_legacy_partial_without_walk(tmp_path, monkeypatch):
    """Finished shows with partial titles + fetched_at (no walk_complete) must retry."""
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    (tmp_path / "21.json").write_text(
        '{"mal_id":21,"title":"Naruto","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":500,"list_status":"completed","num_episodes_watched":500,'
        '"anime_status":"finished_airing","score":10,"mean_score":8.0,'
        '"episode_titles":{"1":"Enter Naruto!"},"episode_titles_fetched_at":"2026-01-01T00:00:00Z"}',
        encoding="utf-8",
    )
    assert mal_mod.episode_titles_need_fetch(21) is True


def test_episode_titles_need_fetch_empty_fetched_retries(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    (tmp_path / "9.json").write_text(
        '{"mal_id":9,"title":"Empty","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":12,"list_status":"completed","num_episodes_watched":12,'
        '"anime_status":"finished_airing","score":0,"mean_score":null,'
        '"episode_titles":{},"episode_titles_fetched_at":"2026-01-01T00:00:00Z"}',
        encoding="utf-8",
    )
    assert mal_mod.episode_titles_need_fetch(9) is True


def test_episode_titles_walk_complete_stops_partial_retry(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    (tmp_path / "3.json").write_text(
        '{"mal_id":3,"title":"Partial","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":26,"list_status":"completed","num_episodes_watched":26,'
        '"anime_status":"finished_airing","score":0,"mean_score":null,'
        '"episode_titles":{"1":"A","2":"B"},'
        '"episode_titles_fetched_at":"2026-01-01T00:00:00Z",'
        '"episode_titles_walk_complete":true}',
        encoding="utf-8",
    )
    assert mal_mod.episode_titles_need_fetch(3) is False

