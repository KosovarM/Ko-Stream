from pathlib import Path
from unittest.mock import patch

from kostream.app import create_app
from kostream.catalog import CatalogEntry, load_catalog, save_catalog, upsert_entry
from kostream.models import Show

from conftest import bootstrap_test_users, login_client


def _test_app(tmp_path: Path):
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    return create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )


def _logged_in_client(app):
    client = app.test_client()
    login_client(client)
    return client


def test_home_loads(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Ko-Stream" in resp.data


def test_search(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)
    resp = client.get("/search?q=demo")
    assert resp.status_code == 200
    assert b"browse-grid" in resp.data
    assert b"browse-filters" in resp.data
    assert b"Animes" in resp.data


def test_search_genre_filter(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)
    resp = client.get("/search?genre=Adventure")
    assert resp.status_code == 200
    assert b"Adventure" in resp.data


def test_search_availability_tabs(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)
    resp = client.get("/search?avail=local")
    assert resp.status_code == 200
    assert b"browse-avail-tabs" in resp.data
    assert b"Stream only" in resp.data
    assert b"avail=local" in resp.data
    assert b'name="avail" value="local"' in resp.data
    assert b"browse-page" in resp.data
    set_cookies = resp.headers.getlist("Set-Cookie")
    assert any(c.startswith("kostream_avail=local") for c in set_cookies)
    assert any("Path=/" in c for c in set_cookies if c.startswith("kostream_avail="))
    assert any("SameSite=Lax" in c for c in set_cookies if c.startswith("kostream_avail="))
    # Clear resets to All explicitly and updates the cookie.
    assert b"avail=all" in resp.data


def test_anime_browse_avail_cookie_default(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)

    set_resp = client.get("/search?avail=stream")
    assert set_resp.status_code == 200
    assert any(
        c.startswith("kostream_avail=stream")
        for c in set_resp.headers.getlist("Set-Cookie")
    )

    # Bare browse URLs pick up the cookie without a client redirect.
    for path in ("/search", "/movies", "/specials"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert b'name="avail" value="stream"' in resp.data
        assert not any(
            c.startswith("kostream_avail=")
            for c in resp.headers.getlist("Set-Cookie")
        )

    clear = client.get("/search?avail=all")
    assert clear.status_code == 200
    assert any(
        c.startswith("kostream_avail=all")
        for c in clear.headers.getlist("Set-Cookie")
    )
    after = client.get("/movies")
    assert after.status_code == 200
    assert b'name="avail" value="all"' in after.data


def test_movies_and_specials_nav_pages(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)
    home = client.get("/")
    assert home.status_code == 200
    assert b'href="/movies"' in home.data or b"/movies" in home.data
    assert b'href="/specials"' in home.data or b"/specials" in home.data
    assert b"kostream.catalog.availability" not in home.data
    assert b"KoStreamCatalogAvail" not in home.data

    movies = client.get("/movies")
    assert movies.status_code == 200
    assert b"Movies" in movies.data
    assert b"browse-grid" in movies.data or b"No titles match" in movies.data or b"browse-empty" in movies.data
    assert b'name="avail" value="all"' in movies.data

    specials = client.get("/specials")
    assert specials.status_code == 200
    assert b"Specials" in specials.data


def test_catalog_page(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)
    resp = client.get("/catalog")
    assert resp.status_code == 200
    assert b"Catalog" in resp.data
    assert b'name="csrf-token"' in resp.data


def test_header_search_empty_q_scope_all_shows_everything(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)
    fake = [
        Show(
            id="s1",
            title="Alpha Series",
            description="x",
            media_type="tv",
            type_label="TV",
        ),
        Show(
            id="m1",
            title="Beta Movie",
            description="x",
            media_type="movie",
            type_label="Movie",
        ),
        Show(
            id="o1",
            title="Gamma OVA",
            description="x",
            media_type="ova",
            type_label="OVA",
        ),
    ]
    with patch("kostream.app.scan_library", return_value=fake):
        empty = client.get("/search?scope=all")
        assert empty.status_code == 200
        assert b"All titles" in empty.data
        assert b"Alpha Series" in empty.data
        assert b"Beta Movie" in empty.data
        assert b"Gamma OVA" in empty.data
        assert b"No titles match" not in empty.data

        blank_q = client.get("/search?scope=all&q=")
        assert blank_q.status_code == 200
        assert b"Alpha Series" in blank_q.data
        assert b"Beta Movie" in blank_q.data
        assert b"Gamma OVA" in blank_q.data


def test_browse_studio_filter(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)
    fake = [
        Show(
            id="mad-1",
            title="Madhouse Hit",
            description="",
            media_type="tv",
            type_label="TV",
            studios=["Madhouse"],
            genres=["Action"],
        ),
        Show(
            id="kyo-1",
            title="Kyo Hit",
            description="",
            media_type="tv",
            type_label="TV",
            studios=["Kyoto Animation"],
            genres=["Action"],
        ),
        Show(
            id="mad-movie",
            title="Madhouse Film",
            description="",
            media_type="movie",
            type_label="Movie",
            studios=["Madhouse"],
            genres=["Action"],
        ),
    ]
    with patch("kostream.app.scan_library", return_value=fake):
        series = client.get("/search?studio=Madhouse")
        assert series.status_code == 200
        assert b"Madhouse Hit" in series.data
        assert b"Kyo Hit" not in series.data
        assert b'name="studio"' in series.data
        assert b"studio=Madhouse" in series.data or b"selected" in series.data

        movies = client.get("/movies?studio=Madhouse")
        assert movies.status_code == 200
        assert b"Madhouse Film" in movies.data
        assert b"Madhouse Hit" not in movies.data


def test_header_search_scope_all_includes_movies_and_specials(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)
    fake = [
        Show(
            id="s1",
            title="Zeta Probe Series",
            description="x",
            media_type="tv",
            type_label="TV",
        ),
        Show(
            id="m1",
            title="Zeta Probe Movie",
            description="x",
            media_type="movie",
            type_label="Movie",
        ),
        Show(
            id="o1",
            title="Zeta Probe OVA",
            description="x",
            media_type="ova",
            type_label="OVA",
        ),
        Show(
            id="other",
            title="Unrelated Title",
            description="x",
            media_type="tv",
            type_label="TV",
        ),
    ]
    with patch("kostream.app.scan_library", return_value=fake):
        scoped = client.get("/search?q=Zeta+Probe&scope=all")
        assert scoped.status_code == 200
        assert b"Search results" in scoped.data
        assert b"Zeta Probe Series" in scoped.data
        assert b"Zeta Probe Movie" in scoped.data
        assert b"Zeta Probe OVA" in scoped.data
        assert b"Unrelated Title" not in scoped.data
        assert b"card-kind" in scoped.data
        assert b'name="scope" value="all"' in scoped.data

        # Series browse without scope stays TV-only.
        series_only = client.get("/search?q=Zeta+Probe")
        assert series_only.status_code == 200
        assert b"Zeta Probe Series" in series_only.data
        assert b"Zeta Probe Movie" not in series_only.data
        assert b"Zeta Probe OVA" not in series_only.data

    home = client.get("/")
    assert home.status_code == 200
    assert b'name="scope" value="all"' in home.data


def test_browse_pages_expose_studio_control(tmp_path: Path):
    app = _test_app(tmp_path)
    client = _logged_in_client(app)
    for path in ("/search", "/movies", "/specials"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert b'name="studio"' in resp.data
        assert b"All studios" in resp.data