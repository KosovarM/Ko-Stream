"""English UI strings + theme preference cookies (no multi-locale translations).

``_()`` is an identity helper so templates can keep the familiar call shape.
Locale cookie ``kostream_lang`` is accepted for compatibility but only English
is supported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import g, has_request_context

if TYPE_CHECKING:
    from flask import Flask

LANG_COOKIE = "kostream_lang"
LANG_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year
DEFAULT_LANG = "en"
SUPPORTED_LANGS = frozenset({"en"})

THEME_COOKIE = "kostream_theme"
THEME_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year
DEFAULT_THEME = "gold-dark"
SUPPORTED_THEMES = frozenset({"gold-dark", "red-light", "blue-green"})
THEME_LABELS = {
    "gold-dark": "Gold / Dark",
    "red-light": "Red / Light",
    "blue-green": "Blue / Green",
}


def normalize_theme(value: str | None) -> str:
    v = (value or "").strip().casefold()
    if v in SUPPORTED_THEMES:
        return v
    return DEFAULT_THEME


def get_theme() -> str:
    if has_request_context() and hasattr(g, "theme"):
        return str(g.theme)
    return DEFAULT_THEME


def set_request_theme(cookie_value: str | None) -> str:
    """Resolve theme from cookie and store on ``g.theme``."""
    theme = normalize_theme(cookie_value)
    if has_request_context():
        g.theme = theme
    return theme


def normalize_lang(value: str | None) -> str:
    v = (value or "").strip().casefold()
    if v in SUPPORTED_LANGS:
        return v
    return DEFAULT_LANG


def get_locale() -> str:
    if has_request_context() and hasattr(g, "lang"):
        return str(g.lang)
    return DEFAULT_LANG


def set_request_locale(cookie_value: str | None) -> str:
    """Resolve locale from cookie and store on ``g.lang`` (English only)."""
    lang = normalize_lang(cookie_value)
    if has_request_context():
        g.lang = lang
    return lang


def _(message: str) -> str:
    """Return ``message`` unchanged (English-only UI)."""
    return message


def init_app(app: Flask) -> None:
    """Register ``_`` for all templates (Jinja globals + request locale helper)."""
    app.jinja_env.globals["_"] = _
    app.jinja_env.globals["THEME_LABELS"] = THEME_LABELS
    app.jinja_env.globals["SUPPORTED_THEMES"] = sorted(SUPPORTED_THEMES)
