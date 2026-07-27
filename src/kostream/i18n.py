"""Lightweight German/English UI translations (no Flask-Babel dependency).

Preference cookie: ``kostream_lang=en|de`` (same shape as ``kostream_avail``).
Default locale is English when the cookie is missing or invalid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import g, has_request_context

if TYPE_CHECKING:
    from flask import Flask

LANG_COOKIE = "kostream_lang"
LANG_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year
DEFAULT_LANG = "en"
SUPPORTED_LANGS = frozenset({"en", "de"})

# English msgid → German. English UI uses the msgid as-is.
_DE: dict[str, str] = {
    # Nav / chrome
    "Home": "Start",
    "Schedule": "Zeitplan",
    "Animes": "Animes",
    "Series": "Serien",
    "Movies": "Filme",
    "Specials": "Specials",
    "Manga": "Manga",
    "Manhwa": "Manhwa",
    "Library": "Bibliothek",
    "Admin": "Admin",
    "Log out": "Abmelden",
    "Log in": "Anmelden",
    "Menu": "Menü",
    "Open search": "Suche öffnen",
    "Close search": "Suche schließen",
    "Search anime...": "Anime suchen…",
    "Language": "Sprache",
    "Notifications": "Benachrichtigungen",
    "Mark all read": "Alle als gelesen markieren",
    "No notifications yet.": "Noch keine Benachrichtigungen.",
    "Notification": "Benachrichtigung",
    "Ko-Stream · private local library · MAL metadata · your own files only": (
        "Ko-Stream · private lokale Bibliothek · MAL-Metadaten · nur eigene Dateien"
    ),
    "Jellyfin connected": "Jellyfin verbunden",
    "MAL connected": "MAL verbunden",
    # Login
    "Your private local library": "Deine private lokale Bibliothek",
    "Username": "Benutzername",
    "Password": "Passwort",
    "No accounts yet. Create the first master account on the server:": (
        "Noch keine Konten. Erstelle das erste Master-Konto auf dem Server:"
    ),
    "Invalid username or password.": "Ungültiger Benutzername oder Passwort.",
    "This account is restricted. Contact the master user.": (
        "Dieses Konto ist gesperrt. Kontaktiere den Master-Benutzer."
    ),
    "Account restricted after too many failed login attempts. Contact the master user.": (
        "Konto nach zu vielen fehlgeschlagenen Anmeldeversuchen gesperrt. "
        "Kontaktiere den Master-Benutzer."
    ),
    "Session expired. Please try logging in again.": (
        "Sitzung abgelaufen. Bitte melde dich erneut an."
    ),
    "No accounts configured yet.": "Noch keine Konten konfiguriert.",
    "Your library": "Deine Bibliothek",
    # Home
    "Featured": "Empfohlen",
    "Metadata only": "Nur Metadaten",
    "Continue": "Weiter",
    "Open": "Öffnen",
    "Detail ›": "Details ›",
    "Highest MAL score": "Höchste MAL-Bewertung",
    "Currently Airing": "Aktuell im TV",
    "Continue Watching": "Weiterschauen",
    "Currently reading · Manga": "Aktuell am Lesen · Manga",
    "Currently reading · Manhwa": "Aktuell am Lesen · Manhwa",
    "Recently added": "Zuletzt hinzugefügt",
    # Browse / search
    "Availability": "Verfügbarkeit",
    "All": "Alle",
    "Available": "Verfügbar",
    "Stream only": "Nur Stream",
    "Search": "Suche",
    "Genre": "Genre",
    "All genres": "Alle Genres",
    "Apply": "Anwenden",
    "Clear": "Zurücksetzen",
    "filtered": "gefiltert",
    "Previous": "Zurück",
    "Next": "Weiter",
    "Page": "Seite",
    "of": "von",
    "title": "Titel",
    "titles": "Titel",
    "No titles match your filters.": "Keine Titel passen zu deinen Filtern.",
    "Show all titles": "Alle Titel anzeigen",
    "Add shows in Library or connect MyAnimeList to populate your library.": (
        "Füge Titel in der Bibliothek hinzu oder verbinde MyAnimeList."
    ),
    "Filter by title or description…": "Nach Titel oder Beschreibung filtern…",
    # Catalog / library chrome
    "Requests": "Anfragen",
    "Wishlist for titles with missing available episodes or chapters.": (
        "Wunschliste für Titel mit fehlenden verfügbaren Episoden oder Kapiteln."
    ),
    "open": "offen",
    "None yet": "Noch keine",
    "Showing your requests only.": "Nur deine Anfragen werden angezeigt.",
    "by": "von",
    "Unknown": "Unbekannt",
    "available": "verfügbar",
    "Fulfill": "Erledigen",
    "Dismiss": "Verwerfen",
    "Mark fulfilled": "Als erledigt markieren",
    "Remove request": "Anfrage entfernen",
    "No open requests. Use Request missing on a show or manga overview when available files are incomplete.": (
        "Keine offenen Anfragen. Nutze „Fehlende anfordern“ auf einer Serien- "
        "oder Manga-Übersicht, wenn verfügbare Dateien unvollständig sind."
    ),
    "Only enabled entries load on the home page — fast for local testing.": (
        "Nur aktivierte Einträge erscheinen auf der Startseite — schnell für lokale Tests."
    ),
    "Config file:": "Konfigurationsdatei:",
    "enabled": "aktiviert",
    "total": "gesamt",
    "from MAL": "von MAL",
    "Anime": "Anime",
    "Library totals": "Bibliotheksübersicht",
    "MyAnimeList": "MyAnimeList",
    "Connect MyAnimeList": "MyAnimeList verbinden",
    "Disconnect": "Trennen",
    "Sync animes": "Animes synchronisieren",
    "Sync mangas": "Mangas synchronisieren",
    "Manage Sync": "Sync verwalten",
    "Search AniList (metadata & posters)": "AniList durchsuchen (Metadaten & Poster)",
    "e.g. Frieren, One Piece": "z. B. Frieren, One Piece",
    # Show / manga actions
    "Open on MAL ↗": "Auf MAL öffnen ↗",
    "Request missing": "Fehlende anfordern",
    "Requested": "Angefordert",
    "Remove from catalog": "Aus Katalog entfernen",
    "Status": "Status",
    "Reading": "Am Lesen",
    "Completed": "Abgeschlossen",
    "New": "Neu",
    "All titles": "Alle Titel",
    "Available chapters": "Verfügbare Kapitel",
    "Filter by genre": "Nach Genre filtern",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": _DE,
}


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
    """Resolve locale from cookie and store on ``g.lang``."""
    lang = normalize_lang(cookie_value)
    if has_request_context():
        g.lang = lang
    return lang


def _(message: str) -> str:
    """Translate ``message`` for the active request locale."""
    lang = get_locale()
    if lang == DEFAULT_LANG:
        return message
    return TRANSLATIONS.get(lang, {}).get(message, message)


def init_app(app: Flask) -> None:
    """Register ``_`` for all templates (Jinja globals + request locale helper)."""
    app.jinja_env.globals["_"] = _
