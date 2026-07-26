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


def test_search_genre_filter(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    resp = client.get("/search?genre=Adventure")
    assert resp.status_code == 200
    assert b"Adventure" in resp.data


def test_catalog_page(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    resp = client.get("/catalog")
    assert resp.status_code == 200
    assert b"Catalog" in resp.data
