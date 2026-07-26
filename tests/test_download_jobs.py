"""Tests for download-missing job hook."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from kostream.app import create_app
from kostream.catalog import CatalogEntry, CatalogState, save_catalog
from kostream.download_jobs import (
    build_download_payload,
    missing_episodes,
    start_download_missing,
)
from kostream.library import get_show
from kostream.local_media import LocalMediaError
from kostream.models import Episode, Show


def test_missing_episodes_filters_local():
    show = Show(
        id="s",
        title="S",
        description="",
        episodes=[
            Episode("s-s01e01", "s", 1, 1, "Episode 1", "S01E01.mp4"),
            Episode("s-s01e02", "s", 1, 2, "Episode 2", "demo.mp4"),
        ],
    )
    missing = missing_episodes(show)
    assert len(missing) == 1
    assert missing[0].number == 2


def test_start_without_cmd_raises(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("KOSTREAM_DOWNLOAD_CMD", raising=False)
    media = tmp_path / "shows"
    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[CatalogEntry(id="demo-show", enabled=True, source="demo", title="Demo")]
        ),
        catalog,
    )
    show = Show(
        id="demo-show",
        title="Demo",
        description="",
        episodes=[Episode("demo-show-demo", "demo-show", 1, 1, "Episode 1", "demo.mp4")],
    )
    try:
        start_download_missing(show, media, catalog_path=catalog)
        assert False, "expected LocalMediaError"
    except LocalMediaError as exc:
        assert "KOSTREAM_DOWNLOAD_CMD" in str(exc)


def test_start_download_runs_external_script(tmp_path: Path, monkeypatch):
    media = tmp_path / "shows"
    catalog = tmp_path / "selected.json"
    save_catalog(
        CatalogState(
            shows=[
                CatalogEntry(
                    id="demo-show",
                    enabled=True,
                    source="demo",
                    title="Demo Show",
                )
            ]
        ),
        catalog,
    )
    script = tmp_path / "dl.py"
    script.write_text(
        "import json,sys\n"
        "p=json.load(sys.stdin)\n"
        "print(json.dumps({'ok':True,'completed':len(p.get('episodes',[])),'message':'ok'}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KOSTREAM_DOWNLOAD_CMD", f'"{sys.executable}" "{script}"')

    app = create_app(media_root=media, catalog_path=catalog)
    client = app.test_client()
    show = get_show("demo-show", media, catalog)
    assert show is not None

    resp = client.post(f"/api/show/{show.id}/download-missing")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["missing"] >= 1

    # Wait briefly for background thread
    import time

    for _ in range(40):
        st = client.get(f"/api/show/{show.id}/download-missing/status").get_json()
        if not st.get("running"):
            break
        time.sleep(0.05)
    assert st["status"] == "done"
    assert st["completed"] >= 1


def test_payload_includes_targets():
    ep = Episode("mal-1-s04e03", "mal-1", 4, 3, "Episode 3", "demo.mp4")
    show = Show(id="mal-1", title="T", description="", episodes=[ep])
    payload = build_download_payload(
        show, [ep], folder="T Season 4", folder_path=Path("C:/media/T Season 4")
    )
    assert payload["episodes"][0]["expected_filename"] == "S04E03.mp4"
    assert payload["episodes"][0]["target_path"].endswith("S04E03.mp4")
