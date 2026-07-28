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

THEME_COOKIE = "kostream_theme"
THEME_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year
DEFAULT_THEME = "gold-dark"
SUPPORTED_THEMES = frozenset({"gold-dark", "red-light", "blue-green"})
THEME_LABELS = {
    "gold-dark": "Gold / Dark",
    "red-light": "Red / Light",
    "blue-green": "Blue / Green",
}

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
    "Catalog": "Katalog",
    "Admin": "Admin",
    "Log out": "Abmelden",
    "Log in": "Anmelden",
    "Menu": "Menü",
    "Open search": "Suche öffnen",
    "Close search": "Suche schließen",
    "Search anime...": "Anime suchen…",
    "Language": "Sprache",
    "Skip to content": "Zum Inhalt springen",
    "Color scheme": "Farbschema",
    "Gold / Dark": "Gold / Dunkel",
    "Red / Light": "Rot / Hell",
    "Blue / Green": "Blau / Grün",
    "Notifications": "Benachrichtigungen",
    "New request": "Neue Anfrage",
    "Request available": "Anfrage verfügbar",
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
    "Studio": "Studio",
    "All studios": "Alle Studios",
    "Search results": "Suchergebnisse",
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
    "Clear filters": "Filter zurücksetzen",
    "Add shows in Catalog or connect MyAnimeList to populate your library.": (
        "Füge Titel im Katalog hinzu oder verbinde MyAnimeList."
    ),
    "Filter by title or description…": "Nach Titel oder Beschreibung filtern…",
    "All titles": "Alle Titel",
    "Show more": "Mehr anzeigen",
    "Show less": "Weniger anzeigen",
    "watched": "gesehen",
    "Progress": "Fortschritt",
    "Sync MAL": "MAL synchronisieren",
    "Go to Catalog": "Zum Katalog",
    "Back to Catalog": "Zurück zum Katalog",
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
    "Catalog totals": "Katalogübersicht",
    "MyAnimeList": "MyAnimeList",
    "Connect MyAnimeList": "MyAnimeList verbinden",
    "Disconnect": "Trennen",
    "Sync animes": "Animes synchronisieren",
    "Sync mangas": "Mangas synchronisieren",
    "Manage Sync": "Sync verwalten",
    "Search AniList (metadata & posters)": "AniList durchsuchen (Metadaten & Poster)",
    "Import from media library": "Aus Medienbibliothek importieren",
    "Import from media": "Aus Medien importieren",
    "Scan your anime media folder for titles with video files that are not in the catalog yet. Matches MAL where possible and sets Plan to Watch when connected.": (
        "Scanne deinen Anime-Medienordner nach Titeln mit Videodateien, die noch nicht im Katalog sind. "
        "Verknüpft MAL wo möglich und setzt Plan to Watch bei verbundenem Konto."
    ),
    "Master account required to import from media.": (
        "Master-Konto erforderlich, um aus Medien zu importieren."
    ),
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
    "Available chapters": "Verfügbare Kapitel",
    "Filter by genre": "Nach Genre filtern",
    "No manga yet. Sync MyAnimeList from Catalog, and/or add folders under media/manga.": (
        "Noch kein Manga. Synchronisiere MyAnimeList im Katalog und/oder lege Ordner unter media/manga an."
    ),
    "No manhwa yet. Sync MyAnimeList from Catalog, and/or add folders under media/manga.": (
        "Noch kein Manhwa. Synchronisiere MyAnimeList im Katalog und/oder lege Ordner unter media/manga an."
    ),
    "No titles match these filters.": "Keine Titel passen zu diesen Filtern.",
    # Schedule
    "Schedule type": "Zeitplan-Typ",
    "Currently airing titles from your library — episode drop day & time in your local timezone (MAL times are JST).": (
        "Aktuell laufende Titel aus deiner Bibliothek — Erscheinungstag & -zeit in deiner lokalen Zeitzone "
        "(MAL-Zeiten sind JST)."
    ),
    "No currently airing shows in the library yet. Sync MAL or enable airing titles in Catalog.": (
        "Noch keine aktuell laufenden Serien in der Bibliothek. Synchronisiere MAL oder aktiviere "
        "laufende Titel im Katalog."
    ),
    "No currently publishing manga in your library yet. Sync MAL or enable publishing titles in Catalog.": (
        "Noch kein aktuell erscheinender Manga in der Bibliothek. Synchronisiere MAL oder aktiviere "
        "erscheinende Titel im Katalog."
    ),
    "No currently publishing manhwa in your library yet. Sync MAL or enable publishing titles in Catalog.": (
        "Noch kein aktuell erscheinender Manhwa in der Bibliothek. Synchronisiere MAL oder aktiviere "
        "erscheinende Titel im Katalog."
    ),
    "Currently releasing": "Aktuell erscheinend",
    "Today": "Heute",
    "No drops": "Keine Releases",
    "TBA": "TBA",
    # Admin users
    "Users": "Benutzer",
    "Create accounts, restrict access, and reset passwords. Only one master is allowed.": (
        "Konten anlegen, Zugriff sperren und Passwörter zurücksetzen. Nur ein Master ist erlaubt."
    ),
    "Create user": "Benutzer anlegen",
    "Create": "Anlegen",
    "Accounts": "Konten",
    "Role": "Rolle",
    "Restricted": "Gesperrt",
    "Yes": "Ja",
    "No": "Nein",
    "Actions": "Aktionen",
    "New password": "Neues Passwort",
    "Reset password": "Passwort zurücksetzen",
    "Restrict": "Sperren",
    "Unrestrict": "Entsperren",
    "Connected": "Verbunden",
    # Watch / player chrome
    "Episodes overview": "Episodenübersicht",
    "Seek": "Spulen",
    "Play": "Abspielen",
    "Pause": "Pause",
    "Mute": "Stumm",
    "Unmute": "Ton an",
    "Subtitles": "Untertitel",
    "Subtitles: use the CC control in the player bar.": "Untertitel: CC-Taste in der Player-Leiste nutzen.",
    "Off": "Aus",
    "Fullscreen": "Vollbild",
    "Stream only — no available file for this episode.": "Nur Stream — keine Datei für diese Episode verfügbar.",
    "Resolve stream": "Stream auflösen",
    "Refresh stream URL": "Stream-URL aktualisieren",
    "Demo samples are enabled, but no URL resolved yet.": "Demo-Samples sind aktiv, aber noch keine URL aufgelöst.",
    "On-demand stream": "On-Demand-Stream",
    "no available copy stored.": "keine lokale Kopie gespeichert.",
    "On-demand stream — no available copy stored by Ko-Stream.": "On-Demand-Stream — keine lokale Kopie von Ko-Stream gespeichert.",
    "Prev": "Zurück",
    "Next →": "Weiter →",
    "← Prev": "← Zurück",
    "Complete": "Abschließen",
    "Complete on MAL": "Auf MAL abschließen",
    "Download to library": "In Bibliothek laden",
    "Save & play": "Speichern & abspielen",
    "Direct stream URL (HTTPS .mp4 / .m3u8)": "Direkte Stream-URL (HTTPS .mp4 / .m3u8)",
    "Press Resolve stream to fetch a URL via your Grab resolver.": (
        "Drücke „Stream auflösen“, um eine URL über deinen Grab-Resolver zu holen."
    ),
    "Paste a direct HTTPS URL below, or set KOSTREAM_GRAB_CMD to your resolver.": (
        "Füge unten eine direkte HTTPS-URL ein, oder setze KOSTREAM_GRAB_CMD auf deinen Resolver."
    ),
    "Available files go in media/shows/…/S01E0N.mp4 when you prefer downloads.": (
        "Verfügbare Dateien gehören nach media/shows/…/S01E0N.mp4, wenn du Downloads bevorzugst."
    ),
    # Show overview
    "Episodes": "Episoden",
    "Already completed": "Bereits abgeschlossen",
    "Watch Now": "Jetzt ansehen",
    "Continue watching": "Weiterschauen",
    "Mark as watched": "Als gesehen markieren",
    "Mark as watched and sync to MAL": "Als gesehen markieren und mit MAL synchronisieren",
    "Your score:": "Deine Bewertung:",
    "Your rating": "Deine Bewertung",
    "Clear": "Löschen",
    "Clear rating": "Bewertung löschen",
    "Connect MAL to rate this title.": "MAL verbinden, um zu bewerten.",
    "Airing": "Läuft",
    "Test stream": "Test-Stream",
    "No available files — use Grab for streams.": "Keine verfügbaren Dateien — nutze Grab für Streams.",
    "No available video files yet.": "Noch keine verfügbaren Videodateien.",
    "MAL list status": "MAL-Listenstatus",
    "Connect MAL to set list status.": "Verbinde MAL, um den Listenstatus zu setzen.",
    "Recommend": "Empfehlen",
    "Remove recommendation": "Empfehlung entfernen",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": _DE,
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
    app.jinja_env.globals["THEME_LABELS"] = THEME_LABELS
    app.jinja_env.globals["SUPPORTED_THEMES"] = sorted(SUPPORTED_THEMES)