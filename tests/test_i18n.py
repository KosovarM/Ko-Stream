"""Locale cookie and English-only UI helpers."""

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
    assert normalize_lang("en") == "en"
    assert normalize_lang("DE") == DEFAULT_LANG
    assert normalize_lang("fr") == DEFAULT_LANG
    assert DEFAULT_LANG == "en"
    assert LANG_COOKIE == "kostream_lang"
    assert LANG_COOKIE_MAX_AGE >= 365 * 24 * 60 * 60


def test_translate_is_identity(tmp_path: Path):
    app = _test_app(tmp_path)
    with app.test_request_context("/"):
        set_request_locale("en")
        assert get_locale() == "en"
        assert _("Home") == "Home"
        assert _("Catalog") == "Catalog"
        set_request_locale("de")
        assert get_locale() == "en"
        assert _("Home") == "Home"


def test_set_locale_sets_cookie_and_redirects(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)

    resp = client.get("/locale?lang=en&next=/search", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/search")
    cookies = resp.headers.getlist("Set-Cookie")
    assert any(c.startswith("kostream_lang=en") for c in cookies)
    assert any("Path=/" in c for c in cookies if c.startswith("kostream_lang="))
    assert any("SameSite=Lax" in c for c in cookies if c.startswith("kostream_lang="))


def test_set_locale_rejects_de_and_external_next(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)
    resp = client.get(
        "/locale?lang=de&next=https://evil.example/phish",
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert "evil.example" not in (resp.headers.get("Location") or "")
    cookies = resp.headers.getlist("Set-Cookie")
    assert any(c.startswith("kostream_lang=en") for c in cookies)


def test_set_theme_sets_cookie_and_redirects(tmp_path: Path):
    from kostream.i18n import THEME_COOKIE

    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)

    resp = client.get("/theme?scheme=pink-light&next=/catalog", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/catalog")
    cookies = resp.headers.getlist("Set-Cookie")
    assert any(c.startswith("kostream_theme=pink-light") for c in cookies)
    assert any("Path=/" in c for c in cookies if c.startswith("kostream_theme="))
    assert any("SameSite=Lax" in c for c in cookies if c.startswith("kostream_theme="))

    client.set_cookie(THEME_COOKIE, "pink-light")
    page = client.get("/catalog")
    assert page.status_code == 200
    assert b'data-theme="pink-light"' in page.data
    assert b"Skip to content" in page.data
    assert b'id="main"' in page.data
    assert b"Color scheme" in page.data


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
    assert b">Home<" in home.data
    assert b"lang-switch" not in home.data
    assert b">Catalog<" in home.data
    assert b">Library<" not in home.data

    catalog = client.get("/catalog")
    assert catalog.status_code == 200
    assert b">Catalog<" in catalog.data
    assert b"Gold / Dark" in catalog.data
    assert b"Pink / Light" in catalog.data
    assert b"Blue / Green" in catalog.data


def test_locale_available_without_login(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    resp = client.get("/locale?lang=en&next=/login", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert any(
        c.startswith("kostream_lang=en")
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


def test_login_rejects_external_next(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    resp = client.post(
        "/login?next=https://evil.example/phish",
        data={"username": "testuser", "password": "testpass"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    loc = resp.headers.get("Location") or ""
    assert "evil.example" not in loc
    assert loc.endswith("/") or loc.rstrip("/").endswith("5001") or "/login" not in loc


def test_red_light_theme_alias_normalizes_to_pink(tmp_path: Path):
    from kostream.i18n import THEME_COOKIE, normalize_theme

    assert normalize_theme("red-light") == "pink-light"
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)
    client.set_cookie(THEME_COOKIE, "red-light")
    page = client.get("/catalog")
    assert page.status_code == 200
    assert b'data-theme="pink-light"' in page.data


def test_set_title_language_persists_per_user(tmp_path: Path):
    app = _test_app(tmp_path)
    client = app.test_client()
    login_client(client)

    resp = client.get("/title-language?lang=jp&next=/catalog", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/catalog")

    settings = tmp_path / "user_data" / "u_test" / "settings.json"
    # bootstrap may use different user id — discover from user_data
    user_dirs = list((tmp_path / "user_data").iterdir()) if (tmp_path / "user_data").exists() else []
    assert user_dirs, "expected per-user data dir"
    settings = user_dirs[0] / "settings.json"
    assert settings.exists()
    import json
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data.get("title_language") == "jp"

    page = client.get("/catalog")
    assert page.status_code == 200
    assert b"Title language" in page.data
    assert b"Japanese" in page.data
