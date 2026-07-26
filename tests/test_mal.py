from unittest.mock import patch

from kostream.catalog import CatalogEntry, CatalogState, load_catalog, save_catalog
from kostream.mal import MalAnimeEntry, MalMangaEntry, sync_animelist_to_catalog, sync_mangalist_to_catalog
from kostream.manga_catalog import load_manga_catalog


def test_sync_animelist_replaces_mal_entries(tmp_path):
    catalog_path = tmp_path / "selected.json"
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
                CatalogEntry(id="mal-99", enabled=True, source="mal", mal_id=99, title="Removed"),
            ]
        ),
        catalog_path,
    )

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
        )
    ]

    class FakeCfg:
        client_id = "x"
        client_secret = "y"
        redirect_uri = "http://127.0.0.1:5001/auth/mal/callback"

    with patch("kostream.mal.get_valid_access_token", return_value="token"):
        with patch("kostream.mal.fetch_animelist", return_value=fake_entries):
            count = sync_animelist_to_catalog(FakeCfg(), catalog_path)

    assert count == 1
    state = load_catalog(catalog_path)
    ids = {s.id for s in state.shows}
    assert "local-1" in ids
    assert "mal-21" in ids
    assert "mal-99" not in ids
    mal21 = state.get("mal-21")
    assert mal21 is not None
    assert mal21.added_at == "2026-01-15T10:00:00Z"
    assert mal21.folder == "One Piece Local"
    assert mal21.anilist_id == 21
    assert mal21.enabled is False
    assert mal21.title == "One Piece"


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
                FakeCfg(), manga_catalog_path=catalog, manga_media_root=media
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
    assert item.num_episodes_watched == 3
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

    def fake_urlopen(req, timeout=25):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise HTTPError(req.full_url, 504, "Gateway Time-out", hdrs=None, fp=BytesIO())
        return FakeResp()

    monkeypatch.setattr(mal_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)

    titles, complete = mal_mod.fetch_episode_titles(31240)
    assert complete is True
    assert attempts["n"] == 2
    assert titles[1] == "The End Start"


def test_ensure_episode_titles_falls_back_to_mal_site(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from urllib.error import HTTPError
    from io import BytesIO

    monkeypatch.setattr(mal_mod, "CACHE_DIR", tmp_path)
    (tmp_path / "31240.json").write_text(
        '{"mal_id":31240,"title":"Re:Zero","synopsis":"","poster_url":null,"genres":[],'
        '"num_episodes":25,"list_status":"completed","num_episodes_watched":25,'
        '"anime_status":"finished_airing","score":10,"mean_score":8.2,"episode_titles":{}}',
        encoding="utf-8",
    )

    def boom(req, timeout=25):
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

    def fake_urlopen(req, timeout=25):
        page = int(parse_qs(urlparse(req.full_url).query).get("page", ["1"])[0])
        if page == 1:
            return FakeResp(
                b'{"pagination":{"has_next_page":true},"data":[{"mal_id":1,"title":"A"}]}'
            )
        raise HTTPError(req.full_url, 429, "Too Many Requests", hdrs=None, fp=BytesIO())

    monkeypatch.setattr(mal_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(mal_mod.time, "sleep", lambda _s: None)

    titles, complete = mal_mod.fetch_episode_titles(21)
    assert complete is False
    assert titles == {1: "A"}


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
    assert updated == 2
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
        (2, {"1": "A"}, "2026-01-01T00:00:00Z"),  # fresh
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
    assert updated == 2
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
    assert mal_mod.sync_catalog_episode_titles(catalog_path) == 0

