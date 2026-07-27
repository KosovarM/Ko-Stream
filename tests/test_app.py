from pathlib import Path

from kostream.app import create_app
from kostream.catalog import CatalogEntry, load_catalog, save_catalog, upsert_entry


def _test_app(tmp_path: Path):
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    return create_app(media_root=media, catalog_path=catalog)


def test_home_loads(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Ko-Stream" in resp.data


def test_search(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    resp = client.get("/search?q=demo")
    assert resp.status_code == 200
    assert b"browse-grid" in resp.data
    assert b"browse-filters" in resp.data
    assert b"Animes" in resp.data


def test_search_genre_filter(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    resp = client.get("/search?genre=Adventure")
    assert resp.status_code == 200
    assert b"Adventure" in resp.data


def test_search_availability_tabs(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    resp = client.get("/search?avail=local")
    assert resp.status_code == 200
    assert b"browse-avail-tabs" in resp.data
    assert b"Stream only" in resp.data
    assert b'avail=local' in resp.data or b"avail=local" in resp.data


def test_movies_and_specials_nav_pages(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    home = client.get("/")
    assert home.status_code == 200
    assert b'href="/movies"' in home.data or b"/movies" in home.data
    assert b'href="/specials"' in home.data or b"/specials" in home.data

    movies = client.get("/movies")
    assert movies.status_code == 200
    assert b"Movies" in movies.data
    assert b"browse-grid" in movies.data or b"No titles match" in movies.data or b"browse-empty" in movies.data

    specials = client.get("/specials")
    assert specials.status_code == 200
    assert b"Specials" in specials.data


def test_catalog_page(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    resp = client.get("/catalog")
    assert resp.status_code == 200
    assert b"Library" in resp.data
    assert b'name="csrf-token"' in resp.data