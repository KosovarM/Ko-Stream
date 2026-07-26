from pathlib import Path

from kostream.catalog import (
    CatalogEntry,
    CatalogState,
    load_catalog,
    save_catalog,
    toggle_entry,
    upsert_entry,
)
from kostream.library import scan_library


def test_catalog_only_loads_enabled(tmp_path: Path):
    media = tmp_path / "shows"
    (media / "Alpha").mkdir(parents=True)
    (media / "Alpha" / "S01E01.mp4").write_bytes(b"video")
    (media / "Beta").mkdir()
    (media / "Beta" / "S01E01.mp4").write_bytes(b"video")

    catalog_path = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(id="alpha", enabled=True, source="local", folder="Alpha"),
                CatalogEntry(id="beta", enabled=False, source="local", folder="Beta"),
            ]
        ),
        catalog_path,
    )

    shows = scan_library(media, catalog_path)
    assert len(shows) == 1
    assert shows[0].id == "alpha"


def test_catalog_toggle(tmp_path: Path):
    catalog_path = tmp_path / "selected.json"
    state = CatalogState(shows=[CatalogEntry(id="x", enabled=True, source="demo", title="X")])
    save_catalog(state, catalog_path)

    loaded = load_catalog(catalog_path)
    updated = toggle_entry(loaded, "x", False)
    save_catalog(updated, catalog_path)

    assert load_catalog(catalog_path).enabled == []


def test_catalog_upsert(tmp_path: Path):
    state = CatalogState()
    state = upsert_entry(state, CatalogEntry(id="a", enabled=True, source="demo", title="A"))
    assert len(state.shows) == 1
    assert state.shows[0].added_at is not None
    first_added = state.shows[0].added_at

    state = upsert_entry(
        state,
        CatalogEntry(id="a", enabled=True, source="local", folder="A", title="A local"),
    )
    assert len(state.shows) == 1
    assert state.shows[0].source == "local"
    assert state.shows[0].added_at == first_added


def test_catalog_roundtrip_added_at(tmp_path: Path):
    catalog_path = tmp_path / "selected.json"
    state = CatalogState(
        shows=[CatalogEntry(id="x", enabled=True, source="demo", title="X", added_at="2026-07-20T12:00:00Z")]
    )
    save_catalog(state, catalog_path)
    loaded = load_catalog(catalog_path)
    assert loaded.shows[0].added_at == "2026-07-20T12:00:00Z"
