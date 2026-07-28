"""Locale cookie and German/English UI translations."""

from __future__ import annotations

from pathlib import Path

from kostream.app import create_app
from kostream.i18n import (
    DEFAULT_LANG,
    LANG_COOKIE,
    LANG_COOKIE_MAX_AGE,
    _,
    get_locale,
    normalize_lang,
    set_request_locale,
)

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


def test_normalize_lang():
    assert normalize_lang(None) == DEFAULT_LANG
    assert normalize_lang("DE") == "de"
    assert normalize_lang("en") == "en"
    assert normalize_lang("fr") == DEFAULT_LANG
    assert DEFAULT_LANG == "en"
    assert LANG_COOKIE == "kostream_lang"
    assert LANG_COOKIE_MAX_AGE >= 365 * 24 * 60 * 60


def test_translate_with_request_locale(tmp_path: Path):
    app = _test_app(tmp_path)
    with app.test_request_context("/"):
        set_request_locale("de")
        assert get_locale() == "de"
        assert _("Home") == "Start"
        assert _("Catalog") == "Katalog"
        assert _("Stream only") == "Nur Stream"
        assert _("Log in") == "Anmelden"
        set_request_locale("en")
        assert _("Home") == "Home"
        assert _("Catalog") == "Catalog"


def test_set_locale_sets_cookie_and_redirects(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)

    resp = client.get("/locale?lang=de&next=/search", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/search")
    cookies = resp.headers.getlist("Set-Cookie")
    assert any(c.startswith("kostream_lang=de") for c in cookies)
    assert any("Path=/" in c for c in cookies if c.startswith("kostream_lang="))
    assert any("SameSite=Lax" in c for c in cookies if c.startswith("kostream_lang="))

    resp_en = client.get("/locale?lang=en&next=/", follow_redirects=False)
    assert resp_en.status_code in (302, 303)
    assert any(
        c.startswith("kostream_lang=en")
        for c in resp_en.headers.getlist("Set-Cookie")
    )


def test_set_locale_rejects_external_next(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.get(
        "/locale?lang=de&next=https://evil.example/phish",
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert "evil.example" not in (resp.headers.get("Location") or "")


def test_german_nav_and_browse_strings(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)
    client.set_cookie(LANG_COOKIE, "de")

    home = client.get("/")
    assert home.status_code == 200
    assert b'lang="de"' in home.data
    assert b">Start<" in home.data
    assert "Katalog".encode() in home.data
    assert b"lang-switch" in home.data
    assert "Weiterschauen".encode() in home.data or "Höchste MAL-Bewertung".encode() in home.data

    search = client.get("/search")
    assert search.status_code == 200
    assert "Nur Stream".encode() in search.data
    assert "Verfügbar".encode() in search.data
    assert b">Suche<" in search.data


def test_set_theme_sets_cookie_and_redirects(tmp_path: Path):
    from kostream.i18n import THEME_COOKIE

    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)

    resp = client.get("/theme?scheme=red-light&next=/catalog", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/catalog")
    cookies = resp.headers.getlist("Set-Cookie")
    assert any(c.startswith("kostream_theme=red-light") for c in cookies)
    assert any("Path=/" in c for c in cookies if c.startswith("kostream_theme="))
    assert any("SameSite=Lax" in c for c in cookies if c.startswith("kostream_theme="))

    client.set_cookie(THEME_COOKIE, "red-light")
    page = client.get("/catalog")
    assert page.status_code == 200
    assert b'data-theme="red-light"' in page.data
    assert b"Skip to content" in page.data or "Zum Inhalt".encode() in page.data
    assert b'id="main"' in page.data
    assert b"Color scheme" in page.data or "Farbschema".encode() in page.data


def test_set_theme_rejects_external_next(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.get(
        "/theme?scheme=blue-green&next=https://evil.example/phish",
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert "evil.example" not in (resp.headers.get("Location") or "")
    assert any(
        c.startswith("kostream_theme=blue-green")
        for c in resp.headers.getlist("Set-Cookie")
    )


def test_skip_link_and_catalog_label(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)
    home = client.get("/")
    assert home.status_code == 200
    assert b'href="#main"' in home.data
    assert b'id="main"' in home.data
    assert b">Catalog<" in home.data
    assert b">Library<" not in home.data

    catalog = client.get("/catalog")
    assert catalog.status_code == 200
    assert b">Catalog<" in catalog.data
    assert b"Gold / Dark" in catalog.data
    assert b"Red / Light" in catalog.data
    assert b"Blue / Green" in catalog.data


def test_german_login_page(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    client.set_cookie(LANG_COOKIE, "de")
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Anmelden".encode() in resp.data
    assert "Benutzername".encode() in resp.data
    assert "Passwort".encode() in resp.data
    assert "private lokale Bibliothek".encode() in resp.data


def test_german_login_error(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    client.set_cookie(LANG_COOKIE, "de")
    resp = client.post(
        "/login",
        data={"username": "nope", "password": "wrong"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Ungültiger Benutzername oder Passwort.".encode() in resp.data


def test_locale_available_without_login(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    resp = client.get("/locale?lang=de&next=/login", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert any(
        c.startswith("kostream_lang=de")
        for c in resp.headers.getlist("Set-Cookie")
    )


def test_default_locale_is_english(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'lang="en"' in resp.data
    assert b">Home<" in resp.data
    assert b">Start<" not in resp.data
