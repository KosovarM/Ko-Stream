"""Basic CSRF protection (S2)."""

from __future__ import annotations

from pathlib import Path

from kostream.app import create_app


def _app(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOSTREAM_CSRF", "1")
    monkeypatch.setenv("KOSTREAM_SECRET_KEY", "test-secret-key-for-csrf")
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    return create_app(media_root=media, catalog_path=catalog)


def test_csrf_meta_present(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'name="csrf-token"' in resp.data


def test_post_without_csrf_rejected(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = app.test_client()
    client.get("/")  # establish session + token
    resp = client.post("/api/catalog/toggle", json={"id": "x", "enabled": True})
    assert resp.status_code == 403
    assert resp.get_json()["ok"] is False


def test_post_with_csrf_header_ok(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["csrf_token"] = "fixed-csrf-token"
    resp = client.post(
        "/api/catalog/toggle",
        json={"id": "missing", "enabled": True},
        headers={"X-CSRF-Token": "fixed-csrf-token"},
    )
    # Toggle of unknown id still returns 200 with ok (toggle_entry no-ops / keeps state)
    assert resp.status_code != 403
