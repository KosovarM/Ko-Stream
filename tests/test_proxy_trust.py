"""Production proxy / session cookie flags."""

from __future__ import annotations

from pathlib import Path

from kostream.app import create_app

from conftest import bootstrap_test_users, login_client


def _app(tmp_path: Path):
    media = tmp_path / "media" / "shows"
    media.mkdir(parents=True)
    catalog = tmp_path / "selected.json"
    catalog.write_text('{"shows": []}', encoding="utf-8")
    users = tmp_path / "users.json"
    user_data = tmp_path / "user_data"
    bootstrap_test_users(users)
    return create_app(
        media_root=media,
        catalog_path=catalog,
        users_path=users,
        user_data_base=user_data,
    )


def test_session_secure_off_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("KOSTREAM_SESSION_SECURE", raising=False)
    app = _app(tmp_path)
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_session_secure_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOSTREAM_SESSION_SECURE", "1")
    app = _app(tmp_path)
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_trust_proxy_off_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("KOSTREAM_TRUST_PROXY", raising=False)
    app = _app(tmp_path)
    assert app.config["TRUST_PROXY"] is False
    assert type(app.wsgi_app).__name__ != "ProxyFix"


def test_trust_proxy_honors_forwarded_proto_host(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOSTREAM_TRUST_PROXY", "1")
    app = _app(tmp_path)
    assert app.config["TRUST_PROXY"] is True

    @app.get("/_proxy_probe")
    def _proxy_probe():
        from flask import request

        return f"{request.scheme}|{request.host}"

    client = app.test_client()
    login_client(client)
    resp = client.get(
        "/_proxy_probe",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "kostream.example.com",
        },
    )
    assert resp.status_code == 200
    assert resp.data == b"https|kostream.example.com"
