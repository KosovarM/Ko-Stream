from __future__ import annotations

import os
import random
import secrets
from pathlib import Path
from datetime import datetime
from urllib.error import URLError

from flask import (
    Flask,
    Response,
    abort,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from kostream.anilist import (
    AniListError,
    fetch_anime,
    fetch_anime_by_mal_id,
    fetch_mal_id,
    search_anime,
)
from kostream.browse import (
    AVAIL_COOKIE,
    AVAIL_COOKIE_MAX_AGE,
    KIND_ALL,
    KIND_ANIMES,
    KIND_LABELS,
    KIND_MOVIES,
    KIND_SPECIALS,
    PAGE_SIZE,
    classify_show_kind,
    collect_genres,
    collect_studios,
    filter_by_kind,
    filter_shows,
    normalize_browse_kind,
    paginate,
    resolve_request_availability,
)
from kostream.catalog import (
    SELECTED_FILE,
    CatalogEntry,
    find_matching_entry,
    load_catalog,
    remove_entry,
    save_catalog,
    toggle_entry,
    upsert_entry,
)
from kostream.grab import (
    GrabResolveError,
    grab_cmd,
    grab_dir,
    grab_demo_enabled,
    grab_enabled,
    resolve_stream_url,
    set_override,
    set_overrides_bulk,
)
from kostream.jellyfin import JellyfinConfig, stream_url as jellyfin_stream_url
from kostream.mal import (
    ANIME_LIST_STATUSES,
    MalConfig,
    MalError,
    complete_oauth,
    complete_oauth_with_code,
    disconnect as mal_disconnect,
    get_anime_list_row,
    get_valid_access_token,
    is_connected as mal_is_connected,
    format_last_sync_label,
    load_tokens as mal_load_tokens,
    prepare_oauth,
    ensure_anime_details_async,
    ensure_episode_titles_async,
    cache_needs_enrichment,
    episode_titles_need_fetch,
    load_cached_anime,
    load_cached_manga,
    merge_anime_details_into_cache,
    prefer_large_mal_picture_url,
    sync_animelist_to_catalog,
    sync_mangalist_to_catalog,
    update_anime_list_score,
    update_anime_list_status,
    update_chapters_read,
    update_episodes_watched,
)
from kostream.library import (
    MEDIA_ROOT,
    get_show,
    load_progress,
    save_progress,
    scan_library,
)
from kostream.manga import (
    MANGA_ROOT,
    MangaError,
    collect_manga_genres,
    filter_library_format,
    find_manga_in_library,
    get_chapter,
    get_manga,
    list_page_refs,
    load_manga_library,
    read_page_bytes,
    title_matches_genre,
)
from kostream.manga_catalog import MANGA_SELECTED_FILE
from kostream.manga_progress import (
    chapter_completed,
    chapter_position,
    chapters_read_count,
    filter_currently_publishing,
    filter_currently_reading,
    get_chapter_page_index,
    load_manga_completed,
    load_manga_page_progress,
    manga_reading_status,
    mark_chapter_read,
    mark_chapters_read_through,
    mark_manga_completed,
    set_chapter_page_index,
    total_chapters_target,
)
from kostream.episode_fetch import fetch_episode_from_url
from kostream.local_media import (
    LocalMediaError,
    build_local_info,
    open_folder_in_os,
    prepare_show_folder,
    save_episode_file,
)
from kostream.media_import import import_media_to_catalog, preview_media_import, summarize_import
from kostream.local_registry import list_for_show
from kostream.stream_fetch import StreamFetchError, ffmpeg_available, resolve_fetch_source

from kostream.models import (
    Episode,
    Show,
    is_jellyfin_episode,
    is_local_file_episode,
    is_strm_episode,
    jellyfin_item_id,
    slugify,
    strm_target_url,
)
from kostream.relations import build_relation_links, mal_anime_url
from kostream.proxy import proxy_remote_stream
from kostream.subtitles import discover_vtt_sidecars
from kostream.watch_progress import (
    episode_completed,
    episode_in_progress,
    filter_currently_airing,
    format_episode_progress,
    is_currently_airing,
    load_completed,
    mark_episode_watched,
    mark_show_completed,
    next_unwatched_episode,
    recently_added,
    resume_seconds_for_episode,
    should_persist_watch_progress,
    sort_by_mean_score,
)
from kostream.sync_jobs import (
    get_sync_job,
    start_anime_sync,
    start_anime_title_sync,
    start_chapter_title_sync,
    start_manga_sync,
)
from kostream.sync_index import (
    ANIME_INDEX_FILE,
    MANGA_INDEX_FILE,
    list_index_entries,
    set_skip,
    set_skip_bulk,
)
from kostream.schedule import WEEKDAY_KEYS, build_weekly_schedule
from kostream.streaming import stream_file_with_range
from kostream.requests_store import (
    KIND_LABELS as REQUEST_KIND_LABELS,
    REQUESTS_FILE,
    fulfill_request,
    group_requests,
    has_request,
    kind_for_show,
    manga_local_counts,
    manga_needs_request,
    open_requests,
    remove_request,
    request_key,
    requested_ids,
    show_local_counts,
    show_needs_request,
    upsert_request,
)
from kostream.notifications import (
    list_notifications,
    mark_all_read,
    mark_read,
    notify_request_created,
    notify_request_fulfilled,
)
from kostream.recommendations import (
    RECOMMENDATIONS_FILE,
    RECOMMEND_BLOCKED_ALL_COMPLETED,
    RecommendationConflict,
    SHOW_KINDS as RECOMMEND_SHOW_KINDS,
    all_users_completed_manga,
    all_users_completed_show,
    clear_recommendation,
    get_user_slots,
    list_family_recommendations,
    normalize_kind as normalize_recommendation_kind,
    set_recommendation,
    user_recommended_this,
)
from kostream.auth import (
    authenticate,
    current_user,
    current_user_id,
    login_error_message,
    role_required,
    user_has_role,
)
from kostream.i18n import (
    DEFAULT_THEME,
    LANG_COOKIE,
    LANG_COOKIE_MAX_AGE,
    THEME_COOKIE,
    THEME_COOKIE_MAX_AGE,
    THEME_LABELS,
    _,
    get_locale,
    get_theme,
    init_app as init_i18n,
    normalize_lang,
    normalize_theme,
    set_request_locale,
    set_request_theme,
)
from kostream.user_paths import USER_DATA_DIR, user_data_paths
from kostream.users import (
    USERS_FILE,
    UsersError,
    create_user,
    find_user_by_id,
    load_users,
    reset_password,
    set_restricted,
    users_bootstrapped,
)


from urllib.parse import urlparse

_SECRET_FILE = Path(__file__).resolve().parents[2] / "data" / ".flask_secret"


def _csrf_enabled() -> bool:
    raw = (os.environ.get("KOSTREAM_CSRF") or "1").strip().lower()
    return raw not in ("0", "false", "off", "no")


def _env_flag(name: str, default: str = "0") -> bool:
    raw = (os.environ.get(name) or default).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _trust_proxy_enabled() -> bool:
    """Trust ``X-Forwarded-*`` from Caddy (only set behind a reverse proxy)."""
    return _env_flag("KOSTREAM_TRUST_PROXY")


def _load_or_create_secret_key() -> str:
    """Flask session secret from env or a persisted local file."""
    env = (
        os.environ.get("KOSTREAM_SECRET_KEY")
        or os.environ.get("FLASK_SECRET_KEY")
        or ""
    ).strip()
    if env:
        return env
    try:
        if _SECRET_FILE.is_file():
            existing = _SECRET_FILE.read_text(encoding="utf-8").strip()
            if existing:
                return existing
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SECRET_FILE.write_text(key, encoding="utf-8")
    except OSError:
        pass
    return key


def _ensure_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(16)
        session["csrf_token"] = token
    return token


def _extract_csrf_token() -> str | None:
    header = request.headers.get("X-CSRF-Token") or request.headers.get("X-CSRFToken")
    if header:
        return header.strip()
    form_token = (request.form.get("csrf_token") or "").strip()
    if form_token:
        return form_token
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        raw = payload.get("csrf_token")
        if raw:
            return str(raw).strip()
    return None


def _csrf_ok(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    try:
        return secrets.compare_digest(provided, expected)
    except (TypeError, ValueError):
        return False


def _login_response(
    *,
    users_bootstrapped: bool,
    error: str | None = None,
    status: int = 200,
):
    """Render login with a fresh CSRF token and no-store caching."""
    _ensure_csrf_token()
    resp = make_response(
        render_template(
            "login.html",
            error=error,
            users_bootstrapped=users_bootstrapped,
        ),
        status,
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


def create_app(
    media_root: Path | None = None,
    catalog_path: Path | None = None,
    grab_base: Path | None = None,
    manga_root: Path | None = None,
    manga_catalog_path: Path | None = None,
    requests_path: Path | None = None,
    recommendations_path: Path | None = None,
    users_path: Path | None = None,
    user_data_base: Path | None = None,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = _load_or_create_secret_key()
    init_i18n(app)
    # LAN devices often hit http://192.168.x.x — keep cookies first-party friendly.
    # Behind public HTTPS (Caddy), set KOSTREAM_SESSION_SECURE=1.
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = _env_flag("KOSTREAM_SESSION_SECURE")
    app.config["TRUST_PROXY"] = _trust_proxy_enabled()
    if app.config["TRUST_PROXY"]:
        # One hop: Caddy → gunicorn. Do not enable without a reverse proxy.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config["MEDIA_ROOT"] = media_root or MEDIA_ROOT
    app.config["CATALOG_PATH"] = catalog_path or SELECTED_FILE
    app.config["GRAB_DIR"] = grab_base if grab_base is not None else grab_dir()
    app.config["MANGA_ROOT"] = manga_root if manga_root is not None else MANGA_ROOT
    app.config["MANGA_CATALOG_PATH"] = (
        manga_catalog_path if manga_catalog_path is not None else MANGA_SELECTED_FILE
    )
    app.config["REQUESTS_PATH"] = requests_path if requests_path is not None else REQUESTS_FILE
    app.config["RECOMMENDATIONS_PATH"] = (
        recommendations_path if recommendations_path is not None else RECOMMENDATIONS_FILE
    )
    app.config["USERS_PATH"] = users_path if users_path is not None else USERS_FILE
    app.config["USER_DATA_DIR"] = user_data_base if user_data_base is not None else USER_DATA_DIR
    app.config["ANIME_SYNC_INDEX_PATH"] = ANIME_INDEX_FILE
    app.config["MANGA_SYNC_INDEX_PATH"] = MANGA_INDEX_FILE
    app.config["CSRF_ENABLED"] = _csrf_enabled()

    def _safe_next_url(candidate: str | None) -> str:
        """Allow only same-site relative paths (login, locale, theme redirects).

        Rejects scheme/netloc URLs (``http://…``, ``//evil.com``, etc.).
        Same-host absolute URLs are reduced to path+query only.
        """
        fallback = url_for("home")
        if not candidate:
            return fallback
        target = candidate.strip()
        if not target or target.startswith("//"):
            return fallback
        parsed = urlparse(target)
        if parsed.scheme or parsed.netloc:
            if parsed.netloc != request.host:
                return fallback
            path = parsed.path or "/"
            if not path.startswith("/"):
                return fallback
            query = f"?{parsed.query}" if parsed.query else ""
            return f"{path}{query}"
        if not target.startswith("/"):
            return fallback
        return target

    def _paths_for_user() -> dict[str, Path] | None:
        uid = current_user_id()
        if not uid:
            return None
        return user_data_paths(uid, app.config["USER_DATA_DIR"])

    def _current_mal_user_id() -> str | None:
        return current_user_id()

    def _scan_shows() -> list:
        return scan_library(
            app.config["MEDIA_ROOT"],
            app.config["CATALOG_PATH"],
            user_id=_current_mal_user_id(),
        )

    def _get_show(show_id: str):
        return get_show(
            show_id,
            app.config["MEDIA_ROOT"],
            app.config["CATALOG_PATH"],
            user_id=_current_mal_user_id(),
        )

    def _manga_library():
        return load_manga_library(
            app.config["MANGA_ROOT"],
            app.config["MANGA_CATALOG_PATH"],
            user_id=_current_mal_user_id(),
        )

    @app.before_request
    def _resolve_locale():
        set_request_locale(request.cookies.get(LANG_COOKIE))
        set_request_theme(request.cookies.get(THEME_COOKIE))

    @app.before_request
    def _csrf_protect():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        if not _csrf_enabled():
            return None
        expected = session.get("csrf_token")
        provided = _extract_csrf_token()
        if _csrf_ok(expected, provided):
            return None
        if request.path.startswith("/api/") or request.is_json:
            return {"ok": False, "error": "CSRF validation failed"}, 403
        # Login is the first request that needs a session cookie. Soft-fail so a
        # missing/stale cookie (common on LAN first hits / password managers)
        # re-establishes CSRF instead of a bare 403 Forbidden page.
        if request.endpoint == "login":
            session.pop("csrf_token", None)
            return _login_response(
                users_bootstrapped=users_bootstrapped(app.config["USERS_PATH"]),
                error=_("Session expired. Please try logging in again."),
            )
        abort(403)

    @app.before_request
    def _require_login():
        if request.endpoint == "static":
            return None
        if request.path.startswith("/static/"):
            return None
        if request.endpoint == "favicon" or request.path == "/favicon.ico":
            return None
        if request.endpoint in ("login", "set_locale", "set_theme"):
            return None

        bootstrapped = users_bootstrapped(app.config["USERS_PATH"])
        if not bootstrapped:
            return redirect(url_for("login"))
        if current_user_id() is None:
            return redirect(url_for("login"))
        return None

    def _require_api_roles(*roles: str):
        user = current_user()
        if user is None:
            return {"ok": False, "error": "Login required"}, 401
        allowed = {r.casefold() for r in roles}
        if user.role.casefold() not in allowed:
            return {"ok": False, "error": "Forbidden"}, 403
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        bootstrapped = users_bootstrapped(app.config["USERS_PATH"])
        if request.method == "POST":
            if not bootstrapped:
                return _login_response(
                    users_bootstrapped=False,
                    error=_("No accounts configured yet."),
                )
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user, error_code = authenticate(username, password, app.config["USERS_PATH"])
            if user is None:
                return _login_response(
                    users_bootstrapped=True,
                    error=login_error_message(error_code),
                )
            session.clear()
            session["user_id"] = user.id
            session["csrf_token"] = secrets.token_hex(16)
            return redirect(_safe_next_url(request.args.get("next")))
        return _login_response(users_bootstrapped=bootstrapped)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/locale")
    def set_locale():
        """Set ``kostream_lang`` cookie and redirect back (Referer or ``next``)."""
        lang = normalize_lang(request.args.get("lang"))
        next_url = _safe_next_url(
            request.args.get("next") or request.referrer
        )
        # Prefer login when anonymous and next would bounce through auth again.
        if current_user_id() is None and next_url == url_for("home"):
            next_url = url_for("login")
        resp = redirect(next_url)
        resp.set_cookie(
            LANG_COOKIE,
            lang,
            max_age=LANG_COOKIE_MAX_AGE,
            path="/",
            httponly=True,
            samesite="Lax",
            secure=bool(app.config.get("SESSION_COOKIE_SECURE")),
        )
        return resp

    @app.route("/theme")
    def set_theme():
        """Set ``kostream_theme`` cookie and redirect back (safe ``next``)."""
        scheme = normalize_theme(request.args.get("scheme"))
        next_url = _safe_next_url(
            request.args.get("next") or request.referrer or url_for("catalog_page")
        )
        if current_user_id() is None and next_url == url_for("home"):
            next_url = url_for("login")
        resp = redirect(next_url)
        resp.set_cookie(
            THEME_COOKIE,
            scheme,
            max_age=THEME_COOKIE_MAX_AGE,
            path="/",
            httponly=True,
            samesite="Lax",
            secure=bool(app.config.get("SESSION_COOKIE_SECURE")),
        )
        return resp

    @app.route("/admin/users", methods=["GET", "POST"])
    @role_required("master")
    def admin_users():
        users_path = app.config["USERS_PATH"]
        error = None
        message = request.args.get("message")
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            role = (request.form.get("role") or "user").strip().casefold()
            try:
                create_user(
                    users_path,
                    username=username,
                    password=password,
                    role=role,
                )
                return redirect(
                    url_for("admin_users", message=f"Created user {username}.")
                )
            except UsersError as exc:
                error = str(exc)
        users = load_users(users_path)
        rows = []
        for user in users:
            rows.append(
                {
                    "user": user,
                    "mal_connected": mal_is_connected(user.id),
                }
            )
        return render_template(
            "admin_users.html",
            users=rows,
            error=error,
            message=message,
        )

    @app.route("/admin/users/<user_id>/restrict", methods=["POST"])
    @role_required("master")
    def admin_users_restrict(user_id: str):
        target = find_user_by_id(load_users(app.config["USERS_PATH"]), user_id)
        if target is not None and target.role == "master":
            return redirect(
                url_for("admin_users", message="Cannot restrict the master account.")
            )
        try:
            set_restricted(app.config["USERS_PATH"], user_id, restricted=True)
            # Drop MAL OAuth so a restricted account cannot keep syncing.
            mal_disconnect(user_id)
        except UsersError as exc:
            return redirect(url_for("admin_users", message=str(exc)))
        return redirect(
            url_for("admin_users", message="User restricted. MAL connection removed.")
        )

    @app.route("/admin/users/<user_id>/unrestrict", methods=["POST"])
    @role_required("master")
    def admin_users_unrestrict(user_id: str):
        try:
            set_restricted(app.config["USERS_PATH"], user_id, restricted=False)
        except UsersError as exc:
            return redirect(url_for("admin_users", message=str(exc)))
        return redirect(url_for("admin_users", message="User unrestricted."))

    @app.route("/admin/users/<user_id>/reset-password", methods=["POST"])
    @role_required("master")
    def admin_users_reset_password(user_id: str):
        new_password = request.form.get("password") or ""
        try:
            reset_password(app.config["USERS_PATH"], user_id, new_password)
        except UsersError as exc:
            return redirect(url_for("admin_users", message=str(exc)))
        return redirect(url_for("admin_users", message="Password reset."))

    @app.route("/favicon.ico")
    def favicon():
        return send_file(
            Path(app.static_folder) / "favicon.svg",
            mimetype="image/svg+xml",
            max_age=86400,
        )

    @app.context_processor
    def inject_globals():
        jellyfin = JellyfinConfig.from_env()
        catalog = load_catalog(app.config["CATALOG_PATH"])
        uid = _current_mal_user_id()
        mal_tokens = mal_load_tokens(uid) if uid else None
        try:
            mal_configured = MalConfig.from_env() is not None
        except MalError:
            mal_configured = False
        _paths = _paths_for_user()
        return {
            "site_name": "Ko-Stream",
            "_": _,
            "lang": get_locale(),
            "theme": get_theme(),
            "theme_labels": THEME_LABELS,
            "supported_themes": (
                DEFAULT_THEME,
                "red-light",
                "blue-green",
            ),
            "csrf_token": _ensure_csrf_token(),
            "current_user": current_user(),
            "is_master": user_has_role("master"),
            "can_manage_requests": user_has_role("master", "manager"),
            "can_import_media": user_has_role("master", "manager"),
            "users_bootstrapped": users_bootstrapped(app.config["USERS_PATH"]),
            "jellyfin_connected": jellyfin is not None,
            "mal_connected": bool(uid and mal_is_connected(uid)),
            "mal_username": mal_tokens.username if mal_tokens else None,
            "mal_configured": mal_configured,
            "grab_enabled": grab_enabled(),
            "grab_has_resolver": bool(grab_cmd()),
            "grab_demo_enabled": grab_demo_enabled(),
            "catalog_count": len(catalog.enabled),
            "poster_for": _poster_for,
            "backdrop_for": _backdrop_for,
            "episode_completed": episode_completed,
            "episode_in_progress": episode_in_progress,
            "format_episode_progress": format_episode_progress,
            "next_unwatched_episode": next_unwatched_episode,
            "progress": load_progress(_paths["progress"]) if _paths else {},
            "completed": load_completed(_paths["completed"]) if _paths else {},
        }

    @app.route("/")
    def home():
        paths = _paths_for_user()
        shows = _scan_shows()
        progress = load_progress(paths["progress"]) if paths else {}
        completed = load_completed(paths["completed"]) if paths else {}
        currently_airing = filter_currently_airing(shows)
        manga_titles = _manga_library()
        manga_completed = (
            load_manga_completed(paths["manga_completed"]) if paths else {}
        )
        currently_reading = filter_currently_reading(manga_titles, manga_completed)
        reading_manga = filter_library_format(currently_reading, kind="manga")
        reading_manhwa = filter_library_format(currently_reading, kind="manhwa")
        family_recommendations = list_family_recommendations(
            app.config["RECOMMENDATIONS_PATH"],
            users=load_users(app.config["USERS_PATH"]),
        )
        shows_by_id = {s.id: s for s in shows}
        for group in family_recommendations:
            for item in group["picks"]:
                sid = item.get("show_id")
                mid = item.get("manga_id")
                kind = str(item.get("kind") or "")
                if not item.get("poster_url") and sid and sid in shows_by_id:
                    item["poster_url"] = _poster_for(shows_by_id[sid])
                if kind in ("manga", "manhwa") and (mid or item.get("mal_id") or item.get("title")):
                    manga = find_manga_in_library(
                        manga_titles,
                        manga_id=str(mid or "") or None,
                        mal_id=item.get("mal_id"),
                        title=item.get("title"),
                    )
                    if manga is not None:
                        # Prefer current library id so cards link after MAL merge.
                        if manga.id:
                            item["manga_id"] = manga.id
                        if not item.get("poster_url"):
                            item["poster_url"] = _manga_poster_for(manga)
                    elif not item.get("poster_url") and item.get("mal_id"):
                        item["poster_url"] = _manga_poster_from_mal_id(item.get("mal_id"))
        spotlight = _random_library_sample(shows, limit=10)
        # Same as show detail: fill AniList wide banners so Featured is not
        # stretched from local card thumbnails / small posters.
        for show in spotlight:
            _hydrate_show_banner(show)
        return render_template(
            "home.html",
            spotlight=spotlight,
            trending=sort_by_mean_score(shows, limit=12),
            currently_airing=currently_airing[:12],
            latest=_continue_watching(shows, progress, completed, limit=12),
            new_on_kostream=recently_added(shows, limit=12),
            currently_reading_manga=reading_manga[:12],
            currently_reading_manhwa=reading_manhwa[:12],
            family_recommendations=family_recommendations,
            progress=progress,
            completed=completed,
        )

    @app.route("/schedule")
    def schedule_page():
        mode = (request.args.get("mode") or "anime").strip().lower()
        if mode not in {"anime", "manga", "manhwa"}:
            mode = "anime"
        shows = _scan_shows()
        days, unknown = build_weekly_schedule(shows)
        today_key = WEEKDAY_KEYS[datetime.now().weekday()]
        manga_titles = _manga_library()
        publishing = filter_currently_publishing(manga_titles)
        if mode in {"manga", "manhwa"}:
            manga_releasing = filter_library_format(publishing, kind=mode)
        else:
            manga_releasing = []
        return render_template(
            "schedule.html",
            schedule_mode=mode,
            schedule_days=days,
            schedule_unknown=unknown,
            today_key=today_key,
            manga_releasing=manga_releasing,
        )

    @app.route("/manga")
    def manga_page():
        return _comics_library_page(kind="manga")

    @app.route("/manhwa")
    def manhwa_page():
        return _comics_library_page(kind="manhwa")

    def _comics_library_page(*, kind: str):
        paths = _paths_for_user()
        all_titles = _manga_library()
        titles = filter_library_format(all_titles, kind=kind)
        completed = load_manga_completed(paths["manga_completed"]) if paths else {}
        page_progress = (
            load_manga_page_progress(paths["manga_page_progress"]) if paths else {}
        )
        mal_n = sum(1 for t in titles if t.source == "mal")
        genres = collect_manga_genres(titles)
        tab = (request.args.get("tab") or "reading").strip().lower()
        if tab not in {"reading", "completed", "new"}:
            tab = "reading"
        avail = (request.args.get("avail") or "all").strip().lower()
        if avail not in {"all", "local"}:
            avail = "all"
        genre = (request.args.get("genre") or "").strip()
        if genre and genre not in genres:
            genre = ""
        open_id = (request.args.get("open") or "").strip()
        library_total = len(titles)
        filtered_titles = []
        for title in titles:
            status = manga_reading_status(title, completed)
            if status != tab:
                continue
            if avail == "local" and not title.has_local:
                continue
            if genre and not title_matches_genre(title, genre):
                continue
            filtered_titles.append(title)
        # Keep an explicitly opened title available even if filters exclude it.
        if open_id and not any(t.id == open_id for t in filtered_titles):
            for title in titles:
                if title.id == open_id:
                    filtered_titles.append(title)
                    break
        filters_active = tab != "reading" or avail != "all" or bool(genre)
        users = load_users(app.config["USERS_PATH"])
        uid = current_user_id()
        user_recommended_manga_ids: set[str] = set()
        if uid:
            try:
                rec_kind = normalize_recommendation_kind(kind)
            except ValueError:
                rec_kind = kind
            pick = get_user_slots(uid, app.config["RECOMMENDATIONS_PATH"]).get(rec_kind)
            if isinstance(pick, dict):
                mid = str(pick.get("manga_id") or "").strip()
                if mid:
                    user_recommended_manga_ids.add(mid)
        recommend_blocked_manga_ids = {
            title.id
            for title in titles
            if all_users_completed_manga(
                title.id,
                users,
                app.config["USER_DATA_DIR"],
                chapter_total=total_chapters_target(title),
                mal_id=title.mal_id,
            )
        }
        return render_template(
            "manga.html",
            titles=filtered_titles,
            library_total=library_total,
            filters_active=filters_active,
            mal_manga_count=mal_n,
            manga_completed=completed,
            manga_page_progress=page_progress,
            chapter_completed=chapter_completed,
            manga_reading_status=manga_reading_status,
            chapters_read_count=chapters_read_count,
            total_chapters_target=total_chapters_target,
            title_matches_genre=title_matches_genre,
            manga_needs_request=manga_needs_request,
            manga_local_counts=manga_local_counts,
            request_key=request_key,
            requested_ids=requested_ids(app.config["REQUESTS_PATH"]),
            active_tab=tab,
            selected_avail=avail,
            selected_genre=genre,
            genres=genres,
            open_manga_id=open_id,
            library_kind=kind,
            library_label="Manhwa" if kind == "manhwa" else "Manga",
            browse_endpoint="manhwa_page" if kind == "manhwa" else "manga_page",
            user_recommended_manga_ids=user_recommended_manga_ids,
            recommend_blocked_manga_ids=recommend_blocked_manga_ids,
            recommend_blocked_reason=RECOMMEND_BLOCKED_ALL_COMPLETED,
        )

    @app.route("/api/manga/<manga_id>/pages")
    def api_manga_pages(manga_id: str):
        paths = _paths_for_user()
        manga = get_manga(
            manga_id, app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        if not manga or not manga.chapters:
            return {"ok": False, "error": "Manga not found or no available chapters"}, 404
        chapter = manga.chapters[0]
        try:
            pages = list_page_refs(app.config["MANGA_ROOT"], manga, chapter)
        except MangaError as exc:
            return {"ok": False, "error": str(exc)}, 400
        saved = get_chapter_page_index(
            manga.id, chapter.id, paths["manga_page_progress"]
        )
        return {
            "ok": True,
            "manga_id": manga.id,
            "chapter_id": chapter.id,
            "chapter_title": chapter.title,
            "pages": pages,
            "page_index": saved if saved is not None else 0,
        }

    @app.route("/api/manga/<manga_id>/chapter/<chapter_id>/pages")
    def api_manga_chapter_pages(manga_id: str, chapter_id: str):
        paths = _paths_for_user()
        manga = get_manga(
            manga_id, app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        if not manga:
            return {"ok": False, "error": "Manga not found"}, 404
        chapter = get_chapter(manga, chapter_id)
        if not chapter:
            return {"ok": False, "error": "Chapter not found"}, 404
        try:
            pages = list_page_refs(app.config["MANGA_ROOT"], manga, chapter)
        except MangaError as exc:
            return {"ok": False, "error": str(exc)}, 400
        saved = get_chapter_page_index(
            manga.id, chapter.id, paths["manga_page_progress"]
        )
        return {
            "ok": True,
            "manga_id": manga.id,
            "chapter_id": chapter.id,
            "chapter_title": chapter.title,
            "pages": pages,
            "page_index": saved if saved is not None else 0,
        }

    @app.route("/api/manga/page-progress", methods=["POST"])
    def api_manga_page_progress():
        """Save last page index (0-based) for a manga chapter."""
        paths = _paths_for_user()
        payload = request.get_json(silent=True) or {}
        manga_id = payload.get("manga_id")
        chapter_id = payload.get("chapter_id")
        page_index = payload.get("page_index")
        if not manga_id or not chapter_id or page_index is None:
            abort(400)
        try:
            page_index = int(page_index)
        except (TypeError, ValueError):
            abort(400)
        if page_index < 0:
            abort(400)
        manga = get_manga(
            manga_id, app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        if not manga:
            abort(404)
        chapter = get_chapter(manga, chapter_id)
        if not chapter:
            abort(404)
        if chapter.page_count:
            page_index = min(page_index, max(chapter.page_count - 1, 0))
        saved = set_chapter_page_index(
            manga.id, chapter.id, page_index, paths["manga_page_progress"]
        )
        return {"ok": True, "page_index": saved}

    @app.route("/api/manga/complete", methods=["POST"])
    def api_manga_complete():
        paths = _paths_for_user()
        payload = request.get_json(silent=True) or {}
        manga_id = payload.get("manga_id")
        chapter_id = payload.get("chapter_id")
        if not manga_id or not chapter_id:
            abort(400)
        manga = get_manga(
            manga_id, app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        if not manga:
            abort(404)
        if not get_chapter(manga, chapter_id):
            abort(404)

        chapters_read = mark_chapter_read(
            manga,
            chapter_id,
            paths["manga_completed"],
            page_path=paths["manga_page_progress"],
        )
        mal_synced = False
        mal_error = None
        cfg = MalConfig.from_env()
        uid = _current_mal_user_id()
        if cfg and manga.mal_id and uid and mal_is_connected(uid):
            try:
                total = manga.num_chapters_mal or manga.chapter_count
                status = (
                    "completed"
                    if total and chapters_read >= total
                    else "reading"
                )
                update_chapters_read(
                    cfg, manga.mal_id, chapters_read, status=status, user_id=uid
                )
                mal_synced = True
            except MalError as exc:
                mal_error = str(exc)

        return {
            "ok": True,
            "chapters_read": chapters_read,
            "mal_synced": mal_synced,
            "mal_error": mal_error,
        }

    @app.route("/api/manga/complete-all", methods=["POST"])
    def api_manga_complete_all():
        paths = _paths_for_user()
        payload = request.get_json(silent=True) or {}
        manga_id = payload.get("manga_id")
        if not manga_id:
            abort(400)
        manga = get_manga(
            manga_id, app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        if not manga:
            abort(404)

        chapters_read = mark_manga_completed(
            manga,
            paths["manga_completed"],
            page_path=paths["manga_page_progress"],
        )
        mal_synced = False
        mal_error = None
        cfg = MalConfig.from_env()
        uid = _current_mal_user_id()
        if cfg and manga.mal_id and uid and mal_is_connected(uid):
            try:
                total = max(manga.num_chapters_mal, manga.chapter_count, chapters_read)
                update_chapters_read(
                    cfg, manga.mal_id, total, status="completed", user_id=uid
                )
                mal_synced = True
            except MalError as exc:
                mal_error = str(exc)

        return {
            "ok": True,
            "chapters_read": chapters_read,
            "status": "completed",
            "mal_synced": mal_synced,
            "mal_error": mal_error,
        }

    @app.route("/api/manga/complete-range", methods=["POST"])
    def api_manga_complete_range():
        """Mark a contiguous chapter range as read (through ``to`` in list order)."""
        paths = _paths_for_user()
        payload = request.get_json(silent=True) or {}
        manga_id = payload.get("manga_id")
        if not manga_id:
            abort(400)
        manga = get_manga(
            manga_id, app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        if not manga:
            abort(404)

        from_chapter_id = payload.get("from_chapter_id")
        to_chapter_id = payload.get("to_chapter_id")
        from_pos = payload.get("from_pos")
        to_pos = payload.get("to_pos")

        if from_chapter_id and to_chapter_id:
            if not manga.chapters:
                abort(400)
            from_pos = chapter_position(manga, str(from_chapter_id))
            to_pos = chapter_position(manga, str(to_chapter_id))
            if not from_pos or not to_pos:
                abort(404)
        else:
            try:
                from_pos = int(from_pos)
                to_pos = int(to_pos)
            except (TypeError, ValueError):
                abort(400)

        if from_pos > to_pos:
            from_pos, to_pos = to_pos, from_pos
        if from_pos < 1 or to_pos < 1:
            abort(400)

        max_pos = total_chapters_target(manga)
        if max_pos and to_pos > max_pos:
            to_pos = max_pos
        if not max_pos and not manga.chapters:
            # Metadata-only with unknown chapter total: trust requested end.
            max_pos = to_pos

        chapters_read = mark_chapters_read_through(
            manga,
            to_pos,
            paths["manga_completed"],
            page_path=paths["manga_page_progress"],
        )
        mal_synced = False
        mal_error = None
        cfg = MalConfig.from_env()
        uid = _current_mal_user_id()
        if cfg and manga.mal_id and uid and mal_is_connected(uid):
            try:
                total = manga.num_chapters_mal or manga.chapter_count
                status = (
                    "completed"
                    if total and chapters_read >= total
                    else "reading"
                )
                update_chapters_read(
                    cfg, manga.mal_id, chapters_read, status=status, user_id=uid
                )
                mal_synced = True
            except MalError as exc:
                mal_error = str(exc)

        return {
            "ok": True,
            "chapters_read": chapters_read,
            "from_pos": from_pos,
            "to_pos": to_pos,
            "mal_synced": mal_synced,
            "mal_error": mal_error,
        }

    @app.route("/manga-page/<manga_id>/<chapter_id>/<int:page_index>")
    def manga_page_image(manga_id: str, chapter_id: str, page_index: int):
        manga = get_manga(
            manga_id, app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        if not manga:
            abort(404)
        chapter = get_chapter(manga, chapter_id)
        if not chapter:
            abort(404)
        try:
            data, mime = read_page_bytes(
                app.config["MANGA_ROOT"], manga, chapter, page_index
            )
        except MangaError:
            abort(404)
        return Response(data, mimetype=mime, headers={"Cache-Control": "public, max-age=3600"})

    @app.route("/catalog")
    def catalog_page():
        catalog = load_catalog(app.config["CATALOG_PATH"])
        mal_cfg = MalConfig.from_env()
        uid = _current_mal_user_id()
        user = current_user()
        mal_count = sum(1 for e in catalog.shows if e.source == "mal")
        mal_client_hint = None
        if mal_cfg:
            mal_client_hint = f"{mal_cfg.client_id[:4]}…{mal_cfg.client_id[-4:]} ({len(mal_cfg.client_id)} chars)"
        media_requests = open_requests(app.config["REQUESTS_PATH"])
        if user and user.role.casefold() not in ("master", "manager"):
            media_requests = [
                row
                for row in media_requests
                if row.get("requester_id") == user.id
            ]
        return render_template(
            "catalog.html",
            catalog=catalog,
            catalog_path=app.config["CATALOG_PATH"],
            mal_redirect_uri=mal_cfg.redirect_uri if mal_cfg else None,
            mal_client_hint=mal_client_hint,
            mal_count=mal_count,
            mal_last_sync=format_last_sync_label(user_id=uid) if uid else None,
            mal_message=request.args.get("mal_message"),
            mal_error=request.args.get("mal_error"),
            library_stats=_library_stats(app),
            media_requests=media_requests,
            media_requests_grouped=group_requests(media_requests),
            request_kind_labels=REQUEST_KIND_LABELS,
        )

    @app.route("/auth/mal/connect")
    def mal_connect():
        uid = _current_mal_user_id()
        if not uid:
            return redirect(url_for("login", next=request.path))
        try:
            cfg = MalConfig.from_env()
        except MalError as exc:
            return redirect(url_for("catalog_page", mal_error=str(exc)))
        if not cfg:
            return redirect(url_for("catalog_page", mal_error="Set MAL_CLIENT_ID and MAL_CLIENT_SECRET first."))
        urls = prepare_oauth(cfg, uid)
        return render_template(
            "mal_connect.html",
            authorize_url=urls["authorize_url"],
            login_first_url=urls["login_first_url"],
            redirect_uri=cfg.redirect_uri,
        )

    @app.route("/auth/mal/callback")
    def mal_callback():
        uid = _current_mal_user_id()
        if not uid:
            return redirect(url_for("login", next=request.path))
        cfg = MalConfig.from_env()
        if not cfg:
            abort(500)
        error = request.args.get("error")
        if error:
            return redirect(url_for("catalog_page", mal_error=f"MyAnimeList denied access: {error}"))
        code = request.args.get("code")
        state = request.args.get("state")
        if not code or not state:
            return redirect(url_for("catalog_page", mal_error="Missing OAuth code."))
        try:
            complete_oauth(cfg, code, state, uid)
            count = sync_animelist_to_catalog(
                cfg, app.config["CATALOG_PATH"], user_id=uid
            )
            manga_count = sync_mangalist_to_catalog(
                cfg,
                user_id=uid,
                manga_catalog_path=app.config["MANGA_CATALOG_PATH"],
                manga_media_root=app.config["MANGA_ROOT"],
            )
        except MalError as exc:
            return redirect(url_for("catalog_page", mal_error=str(exc)))
        return redirect(
            url_for(
                "catalog_page",
                mal_message=(
                    f"Connected — synced {count} anime · {manga_count} manga to catalog."
                ),
            )
        )
    @app.route("/auth/mal/complete", methods=["POST"])
    def mal_complete_manual():
        uid = _current_mal_user_id()
        if not uid:
            return redirect(url_for("login", next=request.path))
        cfg = MalConfig.from_env()
        if not cfg:
            return redirect(url_for("catalog_page", mal_error="MAL not configured."))
        raw_code = (request.form.get("code") or "").strip()
        if not raw_code:
            return redirect(url_for("catalog_page", mal_error="Paste the authorization code or callback URL."))
        try:
            complete_oauth_with_code(cfg, raw_code, uid)
            count = sync_animelist_to_catalog(
                cfg, app.config["CATALOG_PATH"], user_id=uid
            )
            manga_count = sync_mangalist_to_catalog(
                cfg,
                user_id=uid,
                manga_catalog_path=app.config["MANGA_CATALOG_PATH"],
                manga_media_root=app.config["MANGA_ROOT"],
            )
        except MalError as exc:
            return redirect(url_for("catalog_page", mal_error=str(exc)))
        return redirect(
            url_for(
                "catalog_page",
                mal_message=(
                    f"Connected — synced {count} anime · {manga_count} manga to catalog."
                ),
            )
        )
    @app.route("/api/mal/sync/animes", methods=["POST"])
    def api_mal_sync_animes():
        """Sync animelist + progress + anime request clear + enrich (not titles)."""
        uid = _current_mal_user_id()
        if not uid:
            return {"ok": False, "error": "Login required"}, 401
        cfg = MalConfig.from_env()
        if not cfg:
            return {"ok": False, "error": "MAL not configured"}, 400
        if not mal_is_connected(uid):
            return {"ok": False, "error": "Not connected to MyAnimeList"}, 401
        paths = _paths_for_user()
        job = start_anime_sync(
            cfg,
            app.config["CATALOG_PATH"],
            user_id=uid,
            media_root=app.config["MEDIA_ROOT"],
            requests_path=app.config["REQUESTS_PATH"],
            anime_index_path=app.config["ANIME_SYNC_INDEX_PATH"],
            completed_path=paths["completed"] if paths else None,
        )
        return {"ok": True, "started": True, **job.to_dict()}

    @app.route("/api/mal/sync/mangas", methods=["POST"])
    def api_mal_sync_mangas():
        """Sync mangalist + manga request clear (not chapter titles)."""
        uid = _current_mal_user_id()
        if not uid:
            return {"ok": False, "error": "Login required"}, 401
        cfg = MalConfig.from_env()
        if not cfg:
            return {"ok": False, "error": "MAL not configured"}, 400
        if not mal_is_connected(uid):
            return {"ok": False, "error": "Not connected to MyAnimeList"}, 401
        job = start_manga_sync(
            cfg,
            user_id=uid,
            manga_catalog_path=app.config["MANGA_CATALOG_PATH"],
            manga_media_root=app.config["MANGA_ROOT"],
            requests_path=app.config["REQUESTS_PATH"],
            manga_index_path=app.config["MANGA_SYNC_INDEX_PATH"],
        )
        return {"ok": True, "started": True, **job.to_dict()}

    @app.route("/api/mal/sync/anime-titles", methods=["POST"])
    def api_mal_sync_anime_titles():
        """Sync anime episode titles only."""
        uid = _current_mal_user_id()
        if not uid:
            return {"ok": False, "error": "Login required"}, 401
        cfg = MalConfig.from_env()
        if not cfg:
            return {"ok": False, "error": "MAL not configured"}, 400
        if not mal_is_connected(uid):
            return {"ok": False, "error": "Not connected to MyAnimeList"}, 401
        job = start_anime_title_sync(
            app.config["CATALOG_PATH"],
            anime_index_path=app.config["ANIME_SYNC_INDEX_PATH"],
        )
        return {"ok": True, "started": True, **job.to_dict()}

    @app.route("/api/mal/sync/chapter-titles", methods=["POST"])
    def api_mal_sync_chapter_titles():
        """Sync MangaDex chapter titles only (metadata, no images)."""
        uid = _current_mal_user_id()
        if not uid:
            return {"ok": False, "error": "Login required"}, 401
        cfg = MalConfig.from_env()
        if not cfg:
            return {"ok": False, "error": "MAL not configured"}, 400
        if not mal_is_connected(uid):
            return {"ok": False, "error": "Not connected to MyAnimeList"}, 401
        job = start_chapter_title_sync(
            manga_catalog_path=app.config["MANGA_CATALOG_PATH"],
            manga_media_root=app.config["MANGA_ROOT"],
            manga_index_path=app.config["MANGA_SYNC_INDEX_PATH"],
        )
        return {"ok": True, "started": True, **job.to_dict()}

    @app.route("/api/mal/sync/status")
    def api_mal_sync_status():
        return get_sync_job().to_dict()

    @app.route("/api/sync-index")
    def api_sync_index_list():
        section = (request.args.get("section") or "anime_sync").strip()
        valid = {"anime_sync", "episode_titles", "manga_sync", "chapter_titles"}
        if section not in valid:
            return {"ok": False, "error": f"Invalid section (use one of {sorted(valid)})"}, 400
        entries = list_index_entries(
            section,  # type: ignore[arg-type]
            catalog_path=app.config["CATALOG_PATH"],
            media_root=app.config["MEDIA_ROOT"],
            manga_catalog_path=app.config["MANGA_CATALOG_PATH"],
            manga_media_root=app.config["MANGA_ROOT"],
            anime_index_path=app.config["ANIME_SYNC_INDEX_PATH"],
            manga_index_path=app.config["MANGA_SYNC_INDEX_PATH"],
        )
        return {"ok": True, "section": section, "entries": entries}

    @app.route("/api/sync-index", methods=["POST"])
    def api_sync_index_update():
        payload = request.get_json(silent=True) or {}
        section = (payload.get("section") or "").strip()
        valid = {"anime_sync", "episode_titles", "manga_sync", "chapter_titles"}
        if section not in valid:
            return {"ok": False, "error": f"Invalid section (use one of {sorted(valid)})"}, 400
        if "skip" not in payload:
            return {"ok": False, "error": "skip required (boolean)"}, 400
        skip = bool(payload.get("skip"))
        index_path = (
            app.config["ANIME_SYNC_INDEX_PATH"]
            if section in ("anime_sync", "episode_titles")
            else app.config["MANGA_SYNC_INDEX_PATH"]
        )
        mal_ids_raw = payload.get("mal_ids")
        if mal_ids_raw is not None:
            if not isinstance(mal_ids_raw, list):
                return {"ok": False, "error": "mal_ids must be an array"}, 400
            mal_ids: list[int] = []
            for raw in mal_ids_raw:
                try:
                    mal_ids.append(int(raw))
                except (TypeError, ValueError):
                    return {"ok": False, "error": "mal_ids must contain integers"}, 400
            set_skip_bulk(mal_ids, section, skip, index_path=index_path)  # type: ignore[arg-type]
            return {
                "ok": True,
                "section": section,
                "skip": skip,
                "updated": len(mal_ids),
                "mal_ids": mal_ids,
            }
        try:
            mal_id = int(payload.get("mal_id"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "mal_id required"}, 400
        set_skip(mal_id, section, skip, index_path=index_path)  # type: ignore[arg-type]
        return {"ok": True, "mal_id": mal_id, "section": section, "skip": skip}

    @app.route("/api/show/<show_id>/relations-ready")
    def api_show_relations_ready(show_id: str):
        show = _get_show(show_id)
        if not show or not show.mal_id:
            return {"ready": True, "has_links": False}
        ready = not cache_needs_enrichment(show.mal_id)
        cached = load_cached_anime(show.mal_id) if ready else None
        has_links = bool(
            cached
            and any(r.relation_type in ("prequel", "sequel") for r in cached.related_anime)
        )
        return {"ready": ready, "has_links": has_links}

    @app.route("/api/show/<show_id>/episode-titles-ready")
    def api_show_episode_titles_ready(show_id: str):
        show = _get_show(show_id)
        if not show or not show.mal_id:
            return {"ready": True, "has_titles": False}
        ready = not episode_titles_need_fetch(show.mal_id)
        cached = load_cached_anime(show.mal_id)
        has_titles = bool(cached and cached.episode_titles)
        return {"ready": ready, "has_titles": has_titles}

    @app.route("/api/mal/disconnect", methods=["POST"])
    def api_mal_disconnect():
        uid = _current_mal_user_id()
        if not uid:
            return {"ok": False, "error": "Login required"}, 401
        # Only drop this user's tokens — shared catalog stays global.
        mal_disconnect(uid)
        return {"ok": True}

    @app.route("/api/catalog/toggle", methods=["POST"])
    def api_catalog_toggle():
        denied = _require_api_roles("master")
        if denied:
            return denied
        payload = request.get_json(silent=True) or {}
        show_id = payload.get("id")
        enabled = payload.get("enabled")
        if not show_id or enabled is None:
            abort(400)
        state = load_catalog(app.config["CATALOG_PATH"])
        state = toggle_entry(state, show_id, bool(enabled))
        save_catalog(state, app.config["CATALOG_PATH"])
        return {"ok": True, "enabled": len(state.enabled)}

    @app.route("/api/catalog/add", methods=["POST"])
    def api_catalog_add():
        # Any logged-in household user may search/add titles (Library bottom search).
        # Toggle/remove stay master-only.
        payload = request.get_json(silent=True) or {}
        if not payload and request.form:
            payload = request.form.to_dict()
        source = payload.get("source", "local")
        folder = payload.get("folder")
        anilist_id = payload.get("anilist_id")
        title = payload.get("title")
        entry_id = payload.get("id") or slugify(folder or title or "show")
        mal_id = int(payload["mal_id"]) if payload.get("mal_id") is not None else None
        anilist_int = int(anilist_id) if anilist_id not in (None, "") else None
        if not mal_id and anilist_int is not None:
            try:
                mal_id = fetch_mal_id(anilist_int)
            except (AniListError, URLError, OSError, ValueError):
                mal_id = None

        state = load_catalog(app.config["CATALOG_PATH"])
        existing = find_matching_entry(
            state,
            entry_id=entry_id,
            mal_id=mal_id,
            anilist_id=anilist_int,
        )
        wants_html = (
            request.accept_mimetypes.best_match(["application/json", "text/html"])
            == "text/html"
        )
        if existing:
            show_url = url_for("show_detail", show_id=existing.id)
            if wants_html:
                return redirect(show_url)
            return {
                "ok": True,
                "id": existing.id,
                "mal_id": existing.mal_id,
                "existing": True,
                "redirect": show_url,
            }

        entry = CatalogEntry(
            id=entry_id,
            enabled=True,
            source=source,
            folder=folder,
            anilist_id=anilist_int,
            mal_id=mal_id,
            title=title,
            jellyfin_id=payload.get("jellyfin_id"),
        )
        state = upsert_entry(state, entry)
        save_catalog(state, app.config["CATALOG_PATH"])

        enriched = False
        cfg = MalConfig.from_env()
        uid = _current_mal_user_id()
        if cfg and mal_id and uid and mal_is_connected(uid):
            try:
                access_token = get_valid_access_token(cfg, uid)
                merge_anime_details_into_cache(access_token, mal_id, title_fallback=title)
                enriched = True
            except MalError:
                enriched = False
        # Jikan episode titles do not need MAL OAuth; kick off when we have an id.
        if mal_id:
            ensure_episode_titles_async(mal_id)

        if wants_html:
            return redirect(url_for("catalog_page"))
        return {
            "ok": True,
            "id": entry.id,
            "mal_id": mal_id,
            "enriched": enriched,
            "existing": False,
        }

    @app.route("/api/catalog/import-media/preview")
    def api_catalog_import_media_preview():
        denied = _require_api_roles("master", "manager")
        if denied:
            return denied
        rows = preview_media_import(
            media_root=app.config["MEDIA_ROOT"],
            catalog_path=app.config["CATALOG_PATH"],
        )
        return {"ok": True, "folders": rows, "count": len(rows)}

    @app.route("/api/catalog/import-media", methods=["POST"])
    def api_catalog_import_media():
        denied = _require_api_roles("master", "manager")
        if denied:
            return denied
        uid = _current_mal_user_id()
        mal_cfg = MalConfig.from_env()
        try:
            result = import_media_to_catalog(
                media_root=app.config["MEDIA_ROOT"],
                catalog_path=app.config["CATALOG_PATH"],
                user_id=uid,
                mal_cfg=mal_cfg,
            )
        except MalError as exc:
            return {"ok": False, "error": str(exc)}, 400
        message = summarize_import(result)
        return {"ok": True, "message": message, **result.to_dict()}

    @app.route("/api/catalog/remove", methods=["POST", "DELETE"])
    def api_catalog_remove():
        denied = _require_api_roles("master")
        if denied:
            return denied
        payload = request.get_json(silent=True) or {}
        if not payload and request.form:
            payload = request.form.to_dict()
        show_id = (payload.get("id") or request.args.get("id") or "").strip()
        if not show_id:
            return {"ok": False, "error": "id required"}, 400
        state = load_catalog(app.config["CATALOG_PATH"])
        existing = state.get(show_id)
        if not existing:
            return {"ok": False, "error": "Not found"}, 404
        title = existing.title or existing.folder or existing.id
        state = remove_entry(state, show_id)
        save_catalog(state, app.config["CATALOG_PATH"])
        message = f"Removed “{title}” from catalog."
        catalog_url = url_for("catalog_page", mal_message=message)
        wants_html = (
            request.accept_mimetypes.best_match(["application/json", "text/html"])
            == "text/html"
        )
        if wants_html:
            return redirect(catalog_url)
        return {"ok": True, "id": show_id, "redirect": catalog_url, "message": message}

    @app.route("/api/anilist/search")
    def api_anilist_search():
        q = request.args.get("q", "").strip()
        if len(q) < 2:
            return {"results": []}
        try:
            results = search_anime(q)
        except AniListError as exc:
            return {"results": [], "error": f"AniList error: {exc}"}, 502
        except (URLError, OSError, ValueError) as exc:
            return {"results": [], "error": f"AniList unavailable: {exc}"}, 502
        return {
            "results": [
                {
                    "anilist_id": m.anilist_id,
                    "title": m.title,
                    "genres": m.genres,
                    "poster_url": m.poster_url,
                }
                for m in results
            ]
        }

    @app.route("/show/<show_id>")
    def show_detail(show_id: str):
        show = _get_show(show_id)
        if not show:
            abort(404)

        # Lazy-load prequel/sequel without blocking the page (background enrich).
        relations_pending = False
        titles_pending = False
        if show.mal_id:
            uid = _current_mal_user_id()
            if uid and mal_is_connected(uid):
                list_row = get_anime_list_row(uid, show.mal_id)
                if cache_needs_enrichment(show.mal_id):
                    relations_pending = True
                    cfg = MalConfig.from_env()
                    if cfg:
                        ensure_anime_details_async(cfg, show.mal_id, uid)
                    # Overlay status still applies while metadata enrich is pending.
                    if list_row and list_row.get("list_status"):
                        show.list_status = str(list_row["list_status"])
                    if list_row and "num_episodes_watched" in list_row:
                        show.episodes_watched = max(
                            show.episodes_watched,
                            int(list_row.get("num_episodes_watched") or 0),
                        )
                else:
                    cached = load_cached_anime(show.mal_id)
                    if cached:
                        from kostream.watch_progress import apply_mal_metadata

                        apply_mal_metadata(show, cached, list_row)
            if episode_titles_need_fetch(show.mal_id):
                titles_pending = True
                ensure_episode_titles_async(show.mal_id)

        catalog = load_catalog(app.config["CATALOG_PATH"])
        mal_id_to_show_id = {entry.mal_id: entry.id for entry in catalog.shows if entry.mal_id}
        relation_links = build_relation_links(
            show,
            mal_id_to_show_id,
            lambda sid: url_for("show_detail", show_id=sid),
        )
        local_info = build_local_info(
            show, app.config["MEDIA_ROOT"], catalog_path=app.config["CATALOG_PATH"]
        )
        local_count, expected_count = show_local_counts(show, local_info)
        req_kind = kind_for_show(show)
        already_requested = has_request(
            req_kind, show.id, app.config["REQUESTS_PATH"]
        )
        try:
            recommend_kind = normalize_recommendation_kind(req_kind)
        except ValueError:
            recommend_kind = "series"
        uid = current_user_id()
        users = load_users(app.config["USERS_PATH"])
        episode_total = max(len(show.episodes), int(show.episode_count or 0), 0)
        recommend_blocked_all_completed = all_users_completed_show(
            show.id,
            users,
            app.config["USER_DATA_DIR"],
            episode_total=episode_total,
            mal_id=show.mal_id,
        )
        user_rec_this = bool(
            uid
            and user_recommended_this(
                uid,
                recommend_kind,
                show_id=show.id,
                path=app.config["RECOMMENDATIONS_PATH"],
            )
        )
        _hydrate_show_banner(show)
        return render_template(
            "show.html",
            show=show,
            relation_links=relation_links,
            relations_pending=relations_pending,
            titles_pending=titles_pending,
            local_info=local_info,
            mal_page_url=mal_anime_url(show.mal_id) if show.mal_id else None,
            show_request_kind=req_kind,
            show_recommend_kind=recommend_kind,
            show_needs_request=show_needs_request(show, local_info),
            already_requested=already_requested,
            show_is_airing=is_currently_airing(show),
            show_local_count=local_count,
            show_expected_count=expected_count,
            user_recommended_this=user_rec_this,
            recommend_blocked_all_completed=recommend_blocked_all_completed,
            recommend_blocked_reason=(
                RECOMMEND_BLOCKED_ALL_COMPLETED if recommend_blocked_all_completed else ""
            ),
        )

    @app.route("/api/recommendations", methods=["POST"])
    def api_recommendations_set():
        user = current_user()
        if user is None:
            return {"ok": False, "error": "Login required"}, 401
        payload = request.get_json(silent=True) or {}
        kind_raw = str(payload.get("kind") or "").strip()
        title = str(payload.get("title") or "").strip()
        show_id = str(payload.get("show_id") or payload.get("media_id") or "").strip() or None
        manga_id = str(payload.get("manga_id") or "").strip() or None
        if not manga_id and kind_raw.strip().casefold() in ("manga", "manhwa"):
            manga_id = str(payload.get("media_id") or "").strip() or None
        replace = bool(
            payload.get("replace")
            or payload.get("confirm")
            or payload.get("swap")
        )
        mal_raw = payload.get("mal_id")
        mal_id = None
        if mal_raw is not None and str(mal_raw).strip() != "":
            try:
                mal_id = int(mal_raw)
            except (TypeError, ValueError):
                return {"ok": False, "error": "mal_id must be an integer"}, 400
        poster_url = str(payload.get("poster_url") or "").strip() or None
        try:
            kind = normalize_recommendation_kind(kind_raw)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        if not title:
            return {"ok": False, "error": "title required"}, 400
        users = load_users(app.config["USERS_PATH"])
        if kind in RECOMMEND_SHOW_KINDS and show_id:
            show = _get_show(show_id)
            episode_total = 0
            mal_id_for_block = mal_id
            if show is not None:
                episode_total = max(len(show.episodes), int(show.episode_count or 0), 0)
                if mal_id_for_block is None:
                    mal_id_for_block = show.mal_id
            if all_users_completed_show(
                show_id,
                users,
                app.config["USER_DATA_DIR"],
                episode_total=episode_total,
                mal_id=mal_id_for_block,
            ):
                return {"ok": False, "error": RECOMMEND_BLOCKED_ALL_COMPLETED}, 400
        elif kind not in RECOMMEND_SHOW_KINDS and manga_id:
            manga = find_manga_in_library(
                _manga_library(),
                manga_id=manga_id,
                mal_id=mal_id,
                title=title,
            )
            chapter_total = total_chapters_target(manga) if manga else 0
            mal_id_for_block = mal_id if mal_id is not None else (manga.mal_id if manga else None)
            if manga is not None:
                # Prefer catalog id after MAL merge (legacy dir-* / file-* → mal-manga-*).
                if manga.id:
                    manga_id = manga.id
                if mal_id is None and manga.mal_id is not None:
                    mal_id = manga.mal_id
                if not poster_url:
                    poster_url = _manga_poster_for(manga)
            elif not poster_url and mal_id is not None:
                poster_url = _manga_poster_from_mal_id(mal_id)
            if all_users_completed_manga(
                manga_id,
                users,
                app.config["USER_DATA_DIR"],
                chapter_total=chapter_total,
                mal_id=mal_id_for_block,
            ):
                return {"ok": False, "error": RECOMMEND_BLOCKED_ALL_COMPLETED}, 400
        try:
            pick, swapped = set_recommendation(
                user.id,
                kind,
                title=title,
                show_id=show_id,
                manga_id=manga_id,
                mal_id=mal_id,
                poster_url=poster_url,
                replace=replace,
                path=app.config["RECOMMENDATIONS_PATH"],
            )
        except RecommendationConflict as exc:
            return {
                "ok": False,
                "needs_swap": True,
                "current": exc.current,
                "error": f"Already recommending “{exc.current.get('title') or 'another title'}”. Confirm to swap.",
            }, 409
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        return {
            "ok": True,
            "swapped": swapped,
            "kind": kind,
            "recommendation": pick,
        }

    @app.route("/api/recommendations/<kind>", methods=["DELETE"])
    def api_recommendations_clear(kind: str):
        user = current_user()
        if user is None:
            return {"ok": False, "error": "Login required"}, 401
        try:
            kind_n = normalize_recommendation_kind(kind)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        removed = clear_recommendation(
            user.id,
            kind_n,
            path=app.config["RECOMMENDATIONS_PATH"],
        )
        if not removed:
            return {"ok": False, "error": "No recommendation in that category"}, 404
        return {"ok": True, "cleared": kind_n}

    @app.route("/api/requests", methods=["POST"])
    def api_requests_create():
        payload = request.get_json(silent=True) or {}
        media_id = str(payload.get("media_id") or payload.get("id") or "").strip()
        kind = str(payload.get("kind") or "").strip()
        title = str(payload.get("title") or "").strip()
        if not media_id:
            return {"ok": False, "error": "media_id required"}, 400
        if not kind:
            return {"ok": False, "error": "kind required"}, 400
        mal_raw = payload.get("mal_id")
        mal_id = None
        if mal_raw is not None and str(mal_raw).strip() != "":
            try:
                mal_id = int(mal_raw)
            except (TypeError, ValueError):
                return {"ok": False, "error": "mal_id must be an integer"}, 400
        local_raw = payload.get("local_count")
        expected_raw = payload.get("expected_count")
        try:
            local_count = int(local_raw) if local_raw is not None else None
            expected_count = int(expected_raw) if expected_raw is not None else None
        except (TypeError, ValueError):
            return {"ok": False, "error": "local_count/expected_count must be integers"}, 400
        try:
            user = current_user()
            entry, created = upsert_request(
                kind=kind,
                media_id=media_id,
                title=title or media_id,
                path=app.config["REQUESTS_PATH"],
                mal_id=mal_id,
                poster_url=(str(payload.get("poster_url") or "").strip() or None),
                type_label=(str(payload.get("type_label") or "").strip() or None),
                local_count=local_count,
                expected_count=expected_count,
                requester_id=user.id if user else None,
                requester_username=user.username if user else None,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        if created:
            notify_request_created(
                entry,
                users_path=app.config["USERS_PATH"],
                base=app.config["USER_DATA_DIR"],
                exclude_user_id=user.id if user else None,
            )
        return {"ok": True, "created": created, "request": entry}

    @app.route("/api/requests/<path:request_id>/fulfill", methods=["POST"])
    def api_requests_fulfill(request_id: str):
        denied = _require_api_roles("master", "manager")
        if denied:
            return denied
        user = current_user()
        assert user is not None
        entry, newly_fulfilled = fulfill_request(
            request_id,
            fulfilled_by=user.id,
            path=app.config["REQUESTS_PATH"],
        )
        if entry is None:
            return {"ok": False, "error": "Request not found"}, 404
        if newly_fulfilled:
            notify_request_fulfilled(
                entry,
                base=app.config["USER_DATA_DIR"],
            )
        return {"ok": True, "request": entry}

    @app.route("/api/notifications", methods=["GET"])
    def api_notifications_list():
        user = current_user()
        if user is None:
            return {"ok": False, "error": "Login required"}, 401
        items, unread = list_notifications(
            user.id,
            base=app.config["USER_DATA_DIR"],
        )
        return {"ok": True, "notifications": items, "unread_count": unread}

    @app.route("/api/notifications/read", methods=["POST"])
    def api_notifications_read():
        user = current_user()
        if user is None:
            return {"ok": False, "error": "Login required"}, 401
        payload = request.get_json(silent=True) or {}
        mark_all = bool(payload.get("all") or payload.get("mark_all"))
        ids_raw = payload.get("ids") or payload.get("id")
        ids: list[str] = []
        if isinstance(ids_raw, list):
            ids = [str(i).strip() for i in ids_raw if str(i).strip()]
        elif ids_raw is not None and str(ids_raw).strip():
            ids = [str(ids_raw).strip()]
        if mark_all:
            changed = mark_all_read(user.id, base=app.config["USER_DATA_DIR"])
        elif ids:
            changed = mark_read(user.id, ids, base=app.config["USER_DATA_DIR"])
        else:
            return {"ok": False, "error": "Provide ids or all=true"}, 400
        _, unread = list_notifications(
            user.id,
            base=app.config["USER_DATA_DIR"],
        )
        return {"ok": True, "marked": changed, "unread_count": unread}

    @app.route("/api/requests/<path:request_id>", methods=["DELETE"])
    def api_requests_delete(request_id: str):
        denied = _require_api_roles("master", "manager")
        if denied:
            return denied
        removed = remove_request(request_id, app.config["REQUESTS_PATH"])
        if not removed:
            return {"ok": False, "error": "Request not found"}, 404
        return {"ok": True, "removed": request_id}

    @app.route("/api/show/<show_id>/local-info")
    def api_show_local_info(show_id: str):
        show = _get_show(show_id)
        if not show:
            abort(404)
        return build_local_info(
            show, app.config["MEDIA_ROOT"], catalog_path=app.config["CATALOG_PATH"]
        )

    @app.route("/api/show/<show_id>/prepare-folder", methods=["POST"])
    def api_show_prepare_folder(show_id: str):
        denied = _require_api_roles("master")
        if denied:
            return denied
        show = _get_show(show_id)
        if not show:
            abort(404)
        payload = request.get_json(silent=True) or {}
        try:
            info = prepare_show_folder(
                show,
                app.config["MEDIA_ROOT"],
                catalog_path=app.config["CATALOG_PATH"],
                folder_name=payload.get("folder"),
            )
        except LocalMediaError as exc:
            return {"ok": False, "error": str(exc)}, 400
        return {"ok": True, **info}

    @app.route("/api/show/<show_id>/open-folder", methods=["POST"])
    def api_show_open_folder(show_id: str):
        denied = _require_api_roles("master")
        if denied:
            return denied
        show = _get_show(show_id)
        if not show:
            abort(404)
        try:
            info = prepare_show_folder(
                show,
                app.config["MEDIA_ROOT"],
                catalog_path=app.config["CATALOG_PATH"],
            )
        except LocalMediaError as exc:
            return {"ok": False, "error": str(exc)}, 400
        opened = open_folder_in_os(Path(info["folder_path"]))
        return {"ok": True, "opened": opened, **info}

    @app.route("/api/show/<show_id>/upload-episode", methods=["POST"])
    def api_show_upload_episode(show_id: str):
        show = _get_show(show_id)
        if not show:
            abort(404)
        episode_id = request.form.get("episode_id")
        if not episode_id:
            return {"ok": False, "error": "episode_id required"}, 400
        episode = next((e for e in show.episodes if e.id == episode_id), None)
        if not episode:
            abort(404)
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return {"ok": False, "error": "file required"}, 400
        try:
            raw = upload.read()
            result = save_episode_file(
                show,
                episode,
                upload.filename,
                raw,
                app.config["MEDIA_ROOT"],
                catalog_path=app.config["CATALOG_PATH"],
            )
        except LocalMediaError as exc:
            return {"ok": False, "error": str(exc)}, 400
        return result

    @app.route("/api/show/<show_id>/fetch-episode", methods=["POST"])
    def api_show_fetch_episode(show_id: str):
        """Copy/download an explicit URL or local file into the show folder; update registry."""
        show = _get_show(show_id)
        if not show:
            abort(404)
        payload = request.get_json(silent=True) or {}
        episode_id = payload.get("episode_id")
        url = payload.get("url")
        if not episode_id or not url:
            return {"ok": False, "error": "episode_id and url required"}, 400
        episode = next((e for e in show.episodes if e.id == episode_id), None)
        if not episode:
            abort(404)
        try:
            kind, _source = resolve_fetch_source(str(url))
        except StreamFetchError as exc:
            return {"ok": False, "error": str(exc)}, 400
        if kind == "http" and not ffmpeg_available():
            return {"ok": False, "error": "ffmpeg not found on PATH"}, 500
        try:
            result = fetch_episode_from_url(
                show,
                episode,
                str(url),
                app.config["MEDIA_ROOT"],
                catalog_path=app.config["CATALOG_PATH"],
            )
        except LocalMediaError as exc:
            return {"ok": False, "error": str(exc)}, 400
        # Fresh scan so callers know the episode is playable as local.
        refreshed = _get_show(show_id)
        ep_now = (
            next((e for e in refreshed.episodes if e.id == episode_id), None)
            if refreshed
            else None
        )
        result["is_local"] = bool(
            ep_now and ep_now.filename != "demo.mp4"
            and not str(ep_now.filename).startswith(("strm:", "jellyfin:"))
        )
        result["reload_suggested"] = True
        return result

    @app.route("/api/show/<show_id>/local-registry")
    def api_show_local_registry(show_id: str):
        show = _get_show(show_id)
        if not show:
            abort(404)
        episodes = list_for_show(show_id)
        filenames = sorted(
            {str(e.get("filename")) for e in episodes if e.get("filename")}
        )
        episode_ids = sorted(
            {str(e.get("episode_id")) for e in episodes if e.get("episode_id")}
        )
        return {
            "ok": True,
            "show_id": show_id,
            "episodes": episodes,
            "filenames": filenames,
            "episode_ids": episode_ids,
        }

    @app.route("/watch/<show_id>/<episode_id>")
    def watch(show_id: str, episode_id: str):
        paths = _paths_for_user()
        show = _get_show(show_id)
        if not show:
            abort(404)
        episode = next((e for e in show.episodes if e.id == episode_id), None)
        if not episode:
            abort(404)
        idx = show.episodes.index(episode)
        prev = show.episodes[idx - 1] if idx > 0 else None
        nxt = show.episodes[idx + 1] if idx + 1 < len(show.episodes) else None
        video_url = _resolve_video_url(
            episode, show_id, grab_base=app.config["GRAB_DIR"], show=show
        )
        is_grab = bool(video_url) and episode.filename == "demo.mp4"
        is_demo = episode.filename == "demo.mp4" and not video_url
        is_external = is_strm_episode(episode) or is_jellyfin_episode(episode) or is_grab
        grab_source = None
        if is_grab:
            try:
                grabbed = resolve_stream_url(
                    show, episode, base=app.config["GRAB_DIR"]
                )
                grab_source = grabbed.source if grabbed else None
            except GrabResolveError:
                grab_source = None
        progress = load_progress(paths["progress"])
        completed = load_completed(paths["completed"])
        ep_done = episode_completed(show, episode, progress, completed)
        next_done = (
            episode_completed(show, nxt, progress, completed) if nxt else False
        )
        resume_at = resume_seconds_for_episode(
            progress.get(episode.id), is_completed=ep_done
        )
        subtitle_tracks = []
        if is_local_file_episode(episode):
            video_path = _resolve_local_path(
                app.config["MEDIA_ROOT"], show_id, episode.filename
            )
            show_dir = _resolve_show_dir(app.config["MEDIA_ROOT"], show_id)
            if video_path and show_dir:
                for track in discover_vtt_sidecars(video_path, show_dir=show_dir):
                    subtitle_tracks.append(
                        {
                            "label": track.label,
                            "lang": track.lang,
                            "url": url_for(
                                "stream_video",
                                show_id=show_id,
                                filename=track.relpath,
                            ),
                        }
                    )
        return render_template(
            "watch.html",
            show=show,
            episode=episode,
            prev_episode=prev,
            next_episode=nxt,
            video_url=video_url,
            is_demo=is_demo,
            is_grab=is_grab,
            is_external=is_external,
            grab_source=grab_source,
            resume_seconds=resume_at,
            episode_completed_flag=ep_done,
            next_episode_completed_flag=next_done,
            show_list_completed=show.list_status == "completed",
            subtitle_tracks=subtitle_tracks,
        )

    @app.route("/media/<show_id>/<path:filename>")
    def stream_video(show_id: str, filename: str):
        path = _resolve_local_path(app.config["MEDIA_ROOT"], show_id, filename)
        if not path:
            abort(404)
        try:
            return stream_file_with_range(path, request)
        except FileNotFoundError:
            abort(404)

    @app.route("/media/poster/<show_id>")
    def local_poster(show_id: str):
        path = _resolve_local_poster(app.config["MEDIA_ROOT"], show_id)
        if not path:
            abort(404)
        return send_file(path)

    @app.route("/media/thumbnail/<kind>/<int:mal_id>")
    def local_thumbnail(kind: str, mal_id: int):
        """Serve cached MAL posters from D:\\Media\\Ko-Stream\\Thumbnail."""
        from kostream.thumbnails import find_thumbnail_file

        if kind not in ("anime", "manga"):
            abort(404)
        path = find_thumbnail_file(kind, mal_id)  # type: ignore[arg-type]
        if not path:
            abort(404)
        return send_file(path, max_age=86400 * 7)

    @app.route("/stream/jellyfin/<item_id>")
    def proxy_jellyfin(item_id: str):
        cfg = JellyfinConfig.from_env()
        if not cfg:
            abort(404)
        url = jellyfin_stream_url(cfg, item_id)
        try:
            return proxy_remote_stream(
                url,
                request,
                headers={"X-Emby-Token": cfg.api_key},
            )
        except (URLError, OSError):
            abort(502)

    @app.route("/stream/strm/<show_id>/<episode_id>")
    def proxy_strm(show_id: str, episode_id: str):
        show = _get_show(show_id)
        if not show:
            abort(404)
        episode = next((e for e in show.episodes if e.id == episode_id), None)
        if not episode or not is_strm_episode(episode):
            abort(404)
        try:
            return proxy_remote_stream(strm_target_url(episode), request)
        except (URLError, OSError):
            abort(502)

    @app.route("/stream/grab/<show_id>/<episode_id>")
    def proxy_grab(show_id: str, episode_id: str):
        if not grab_enabled():
            abort(404)
        show = _get_show(show_id)
        if not show:
            abort(404)
        episode = next((e for e in show.episodes if e.id == episode_id), None)
        if not episode:
            abort(404)
        try:
            result = resolve_stream_url(show, episode, base=app.config["GRAB_DIR"])
        except GrabResolveError:
            abort(502)
        if not result:
            abort(404)
        try:
            return proxy_remote_stream(result.url, request)
        except (URLError, OSError):
            abort(502)

    @app.route("/api/grab/override", methods=["POST"])
    def api_grab_override():
        denied = _require_api_roles("master", "manager")
        if denied:
            return denied
        if not grab_enabled():
            return {"ok": False, "error": "Grab is disabled (KOSTREAM_GRAB=0)"}, 400
        payload = request.get_json(silent=True) or {}
        show_id = payload.get("show_id")
        episode_id = payload.get("episode_id")
        url = payload.get("url")
        if not show_id or not episode_id or not url:
            abort(400)
        show = _get_show(show_id)
        if not show:
            abort(404)
        if not any(e.id == episode_id for e in show.episodes):
            abort(404)
        try:
            cleaned = set_override(
                show_id, episode_id, str(url), base=app.config["GRAB_DIR"]
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        return {"ok": True, "url": cleaned}

    @app.route("/api/grab/overrides/bulk", methods=["POST"])
    def api_grab_overrides_bulk():
        denied = _require_api_roles("master", "manager")
        if denied:
            return denied
        if not grab_enabled():
            return {"ok": False, "error": "Grab is disabled (KOSTREAM_GRAB=0)"}, 400
        payload = request.get_json(silent=True) or {}
        show_id = payload.get("show_id")
        urls = payload.get("urls") or {}
        if not show_id or not isinstance(urls, dict) or not urls:
            abort(400)
        show = _get_show(show_id)
        if not show:
            abort(404)
        valid_ids = {e.id for e in show.episodes}
        mapping = {
            str(ep_id): str(url)
            for ep_id, url in urls.items()
            if str(ep_id) in valid_ids and url
        }
        if not mapping:
            return {"ok": False, "error": "No valid episode URLs in payload"}, 400
        try:
            saved = set_overrides_bulk(show_id, mapping, base=app.config["GRAB_DIR"])
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        return {"ok": True, "count": len(saved), "urls": saved}

    @app.route("/api/grab/resolve", methods=["POST"])
    def api_grab_resolve():
        if not grab_enabled():
            return {"ok": False, "error": "Grab is disabled (KOSTREAM_GRAB=0)"}, 400
        payload = request.get_json(silent=True) or {}
        show_id = payload.get("show_id")
        episode_id = payload.get("episode_id")
        force = bool(payload.get("force"))
        if not show_id or not episode_id:
            abort(400)
        show = _get_show(show_id)
        if not show:
            abort(404)
        episode = next((e for e in show.episodes if e.id == episode_id), None)
        if not episode:
            abort(404)
        if episode.filename != "demo.mp4":
            return {"ok": False, "error": "Episode already has an available or remote file"}, 400
        try:
            result = resolve_stream_url(
                show, episode, base=app.config["GRAB_DIR"], force=force
            )
        except GrabResolveError as exc:
            return {"ok": False, "error": str(exc)}, 502
        if not result:
            return {
                "ok": False,
                "error": (
                    "No stream URL. Set KOSTREAM_GRAB_CMD, paste a URL, "
                    "or enable KOSTREAM_GRAB_DEMO=1 for sample files."
                ),
            }, 404
        return {
            "ok": True,
            "source": result.source,
            "stream_path": url_for(
                "proxy_grab", show_id=show_id, episode_id=episode_id
            ),
        }

    @app.route("/api/progress", methods=["POST"])
    def api_progress():
        paths = _paths_for_user()
        payload = request.get_json(silent=True) or {}
        ep_id = payload.get("episode_id")
        show_id = payload.get("show_id")
        seconds = payload.get("seconds")
        if not ep_id or seconds is None:
            abort(400)
        try:
            seconds_f = float(seconds)
        except (TypeError, ValueError):
            abort(400)

        duration_f: float | None = None
        duration = payload.get("duration")
        if duration is not None:
            try:
                dur = float(duration)
                if dur > 0:
                    duration_f = dur
            except (TypeError, ValueError):
                duration_f = None

        data = load_progress(paths["progress"])
        prev = data.get(ep_id)
        if duration_f is None and isinstance(prev, dict) and prev.get("duration"):
            try:
                duration_f = float(prev["duration"])
            except (TypeError, ValueError):
                duration_f = None

        is_done = False
        if show_id:
            show = _get_show(str(show_id))
            if show:
                episode = next((e for e in show.episodes if e.id == ep_id), None)
                if episode:
                    completed = load_completed(paths["completed"])
                    is_done = episode_completed(show, episode, data, completed)

        if not should_persist_watch_progress(
            seconds_f, duration_f, is_completed=is_done
        ):
            if ep_id in data:
                data.pop(ep_id, None)
                save_progress(paths["progress"], data)
            return {"ok": True, "saved": False}

        entry: dict = {"seconds": seconds_f}
        if duration_f is not None:
            entry["duration"] = duration_f
        data[ep_id] = entry
        save_progress(paths["progress"], data)
        return {"ok": True, "saved": True}

    @app.route("/api/episodes/complete", methods=["POST"])
    def api_episode_complete():
        paths = _paths_for_user()
        payload = request.get_json(silent=True) or {}
        show_id = payload.get("show_id")
        episode_id = payload.get("episode_id")
        if not show_id or not episode_id:
            abort(400)
        show = _get_show(show_id)
        if not show:
            abort(404)
        episode = next((e for e in show.episodes if e.id == episode_id), None)
        if not episode:
            abort(404)

        watched_count = mark_episode_watched(show, episode, paths["completed"])
        # Drop in-episode resume once marked complete
        progress = load_progress(paths["progress"])
        if episode_id in progress:
            progress.pop(episode_id, None)
            save_progress(paths["progress"], progress)

        mal_synced = False
        mal_error = None
        cfg = MalConfig.from_env()
        uid = _current_mal_user_id()
        if cfg and show.mal_id and uid and mal_is_connected(uid):
            try:
                total_eps = show.episode_count
                status = "completed" if total_eps and watched_count >= total_eps else "watching"
                update_episodes_watched(
                    cfg, show.mal_id, watched_count, status=status, user_id=uid
                )
                mal_synced = True
            except MalError as exc:
                mal_error = str(exc)

        return {
            "ok": True,
            "watched_count": watched_count,
            "mal_synced": mal_synced,
            "mal_error": mal_error,
        }

    
    @app.route("/api/show/complete-all", methods=["POST"])
    def api_show_complete_all():
        paths = _paths_for_user()
        payload = request.get_json(silent=True) or {}
        show_id = payload.get("show_id")
        if not show_id:
            abort(400)
        show = _get_show(show_id)
        if not show:
            abort(404)

        watched_count = mark_show_completed(show, paths["completed"])
        mal_synced = False
        mal_error = None
        cfg = MalConfig.from_env()
        uid = _current_mal_user_id()
        if cfg and show.mal_id and uid and mal_is_connected(uid):
            try:
                total = max(show.episode_count or 0, len(show.episodes), watched_count)
                update_episodes_watched(
                    cfg, show.mal_id, total, status="completed", user_id=uid
                )
                mal_synced = True
            except MalError as exc:
                mal_error = str(exc)

        return {
            "ok": True,
            "watched_count": watched_count,
            "status": "completed",
            "mal_synced": mal_synced,
            "mal_error": mal_error,
        }

    @app.route("/api/show/mal-status", methods=["POST"])
    def api_show_mal_status():
        uid = _current_mal_user_id()
        if not uid:
            return {"ok": False, "error": "Login required"}, 401
        if not mal_is_connected(uid):
            return {"ok": False, "error": "MAL not connected"}, 400

        payload = request.get_json(silent=True) or {}
        show_id = str(payload.get("show_id") or "").strip()
        status = str(payload.get("status") or "").strip()
        if not show_id or not status:
            abort(400)
        if status not in ANIME_LIST_STATUSES:
            return {"ok": False, "error": "Invalid status"}, 400

        show = _get_show(show_id)
        if not show or not show.mal_id:
            abort(404)

        cfg = MalConfig.from_env()
        if not cfg:
            return {"ok": False, "error": "MAL not configured"}, 400

        try:
            row = update_anime_list_status(cfg, show.mal_id, status, user_id=uid)
        except MalError as exc:
            return {"ok": False, "error": str(exc)}, 502

        return {
            "ok": True,
            "status": row.get("list_status") or status,
            "mal_id": show.mal_id,
        }

    @app.route("/api/show/mal-score", methods=["POST"])
    def api_show_mal_score():
        uid = _current_mal_user_id()
        if not uid:
            return {"ok": False, "error": "Login required"}, 401
        if not mal_is_connected(uid):
            return {"ok": False, "error": "MAL not connected"}, 400

        payload = request.get_json(silent=True) or {}
        show_id = str(payload.get("show_id") or "").strip()
        try:
            score = int(payload.get("score"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid score"}, 400
        if not show_id or score < 0 or score > 10:
            return {"ok": False, "error": "Invalid score"}, 400

        show = _get_show(show_id)
        if not show or not show.mal_id:
            abort(404)

        cfg = MalConfig.from_env()
        if not cfg:
            return {"ok": False, "error": "MAL not configured"}, 400

        try:
            row = update_anime_list_score(cfg, show.mal_id, score, user_id=uid)
        except MalError as exc:
            return {"ok": False, "error": str(exc)}, 502

        return {
            "ok": True,
            "score": int(row.get("score") or 0),
            "mal_id": show.mal_id,
        }

    @app.route("/search")
    def search():
        return _anime_browse_page(kind=KIND_ANIMES)

    @app.route("/movies")
    def movies_page():
        return _anime_browse_page(kind=KIND_MOVIES)

    @app.route("/specials")
    def specials_page():
        return _anime_browse_page(kind=KIND_SPECIALS)

    def _anime_browse_page(*, kind: str):
        scope = (request.args.get("scope") or "").strip().casefold()
        if scope == KIND_ALL:
            browse_kind = KIND_ALL
        else:
            browse_kind = normalize_browse_kind(kind)
        q = request.args.get("q", "").strip()
        genre = request.args.get("genre", "").strip()
        studio = request.args.get("studio", "").strip()
        availability, persist_avail = resolve_request_availability(
            has_avail_param="avail" in request.args,
            avail_param=request.args.get("avail"),
            cookie_value=request.cookies.get(AVAIL_COOKIE),
        )
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1

        all_shows = _scan_shows()
        kind_shows = filter_by_kind(all_shows, browse_kind)
        genres = collect_genres(kind_shows)
        studios = collect_studios(kind_shows)
        if genre and genre not in genres:
            genre = ""
        if studio and studio not in studios:
            studio = ""
        filtered = filter_shows(kind_shows, q, genre, availability, studio=studio)
        shows, page, total_pages = paginate(filtered, page, PAGE_SIZE)
        endpoint = {
            KIND_ANIMES: "search",
            KIND_MOVIES: "movies_page",
            KIND_SPECIALS: "specials_page",
            KIND_ALL: "search",
        }[browse_kind]
        browse_scope = KIND_ALL if browse_kind == KIND_ALL else ""
        # Empty header search (scope=all, no q) browses everything — label as All titles.
        if browse_kind == KIND_ALL and not q and not genre and not studio:
            browse_label = "All titles"
        else:
            browse_label = KIND_LABELS[browse_kind]

        resp = make_response(
            render_template(
                "search.html",
                shows=shows,
                query=q,
                selected_genre=genre,
                selected_studio=studio,
                selected_avail=availability,
                genres=genres,
                studios=studios,
                page=page,
                total_pages=total_pages,
                total_count=len(filtered),
                page_size=PAGE_SIZE,
                browse_kind=browse_kind,
                browse_label=browse_label,
                browse_endpoint=endpoint,
                browse_scope=browse_scope,
                classify_show_kind=classify_show_kind,
                kind_labels=KIND_LABELS,
            )
        )
        if persist_avail:
            resp.set_cookie(
                AVAIL_COOKIE,
                availability,
                max_age=AVAIL_COOKIE_MAX_AGE,
                path="/",
                httponly=True,
                samesite="Lax",
                secure=bool(app.config.get("SESSION_COOKIE_SECURE")),
            )
        return resp

    return app


def _library_stats(app: Flask) -> dict[str, int]:
    """Totals shown on the Library (catalog) page."""
    shows = scan_library(app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
    anime_episodes = sum(
        1 for show in shows for ep in show.episodes if is_local_file_episode(ep)
    )
    comics = load_manga_library(
        app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
    )
    manga = filter_library_format(comics, kind="manga")
    manhwa = filter_library_format(comics, kind="manhwa")
    return {
        "anime_titles": len(shows),
        "anime_episodes": anime_episodes,
        "manga_titles": len(manga),
        "manga_chapters": sum(t.chapter_count for t in manga),
        "manhwa_titles": len(manhwa),
        "manhwa_chapters": sum(t.chapter_count for t in manhwa),
    }


def _poster_for(show: Show) -> str | None:
    if show.mal_id:
        try:
            from kostream.thumbnails import thumbnail_public_url

            local = thumbnail_public_url("anime", int(show.mal_id))
            if local:
                return local
        except (OSError, TypeError, ValueError):
            pass
    if show.poster_url:
        # Already may be a local /media/thumbnail URL from scan
        return show.poster_url
    if show.poster:
        return url_for("local_poster", show_id=show.id)
    if show.anilist_id:
        meta = fetch_anime(show.anilist_id, network=False)
        if meta and meta.poster_url:
            return meta.poster_url
    return None


def _remote_poster_url(show: Show) -> str | None:
    """Largest available remote poster — never a local thumbnail card image."""
    if show.poster_url and str(show.poster_url).startswith(("http://", "https://")):
        return prefer_large_mal_picture_url(show.poster_url)
    if show.mal_id:
        cached = load_cached_anime(int(show.mal_id))
        if cached and cached.poster_url:
            return prefer_large_mal_picture_url(cached.poster_url)
    if show.anilist_id:
        meta = fetch_anime(show.anilist_id, network=False)
        if meta and meta.poster_url:
            return meta.poster_url
    if show.mal_id:
        meta = fetch_anime_by_mal_id(int(show.mal_id), network=False)
        if meta and meta.poster_url:
            return meta.poster_url
    return None


def _anilist_banner_url(show: Show, *, network: bool = False) -> str | None:
    if show.anilist_id:
        meta = fetch_anime(int(show.anilist_id), network=network)
        if meta and meta.banner_url:
            return meta.banner_url
    if show.mal_id:
        meta = fetch_anime_by_mal_id(int(show.mal_id), network=network)
        if meta and meta.banner_url:
            return meta.banner_url
    return None


def _hydrate_show_banner(show: Show) -> None:
    """Fill ``show.banner_url`` from AniList when missing (detail + Featured)."""
    if show.banner_url:
        return
    banner = _anilist_banner_url(show, network=True)
    if banner:
        show.banner_url = banner


def _backdrop_for(show: Show) -> str | None:
    """Wide banner when available; else remote large poster — not card thumbnails.

    Local ``/media/thumbnail/…`` files are often ~225–400px portraits and look
    heavily pixelated when stretched as a full-bleed hero background.
    """
    if show.banner_url:
        return show.banner_url
    banner = _anilist_banner_url(show, network=False)
    if banner:
        # Keep template ``bg_is_poster`` checks in sync (Featured + detail).
        show.banner_url = banner
        return banner
    remote = _remote_poster_url(show)
    if remote:
        return remote
    return _poster_for(show)


def _manga_poster_from_mal_id(mal_id: int | str | None) -> str | None:
    if mal_id is None or str(mal_id).strip() == "":
        return None
    try:
        mid = int(mal_id)
    except (TypeError, ValueError):
        return None
    try:
        from kostream.thumbnails import thumbnail_public_url

        local = thumbnail_public_url("manga", mid)
        if local:
            return local
    except (OSError, TypeError, ValueError):
        pass
    cached = load_cached_manga(mid)
    if cached and cached.poster_url:
        return cached.poster_url
    return None


def _manga_poster_for(manga) -> str | None:
    """MAL CDN poster, cached MAL image, or first local cover page."""
    if manga is None:
        return None
    if getattr(manga, "poster_url", None):
        return manga.poster_url
    mal_poster = _manga_poster_from_mal_id(getattr(manga, "mal_id", None))
    if mal_poster:
        return mal_poster
    cover_chapter_id = getattr(manga, "cover_chapter_id", None)
    manga_id = getattr(manga, "id", None)
    if cover_chapter_id and manga_id:
        return url_for(
            "manga_page_image",
            manga_id=manga_id,
            chapter_id=cover_chapter_id,
            page_index=0,
        )
    return None


def _resolve_video_url(
    episode: Episode,
    show_id: str,
    *,
    grab_base: Path | None = None,
    show: Show | None = None,
) -> str | None:
    if is_jellyfin_episode(episode):
        if not JellyfinConfig.from_env():
            return None
        return url_for("proxy_jellyfin", item_id=jellyfin_item_id(episode))
    if is_strm_episode(episode):
        return url_for("proxy_strm", show_id=show_id, episode_id=episode.id)
    if episode.filename == "demo.mp4":
        if not grab_enabled():
            return None
        # Need a Show for resolve; build a minimal stand-in if caller omitted it.
        target = show or Show(id=show_id, title=show_id, description="", episodes=[episode])
        try:
            if resolve_stream_url(target, episode, base=grab_base):
                return url_for("proxy_grab", show_id=show_id, episode_id=episode.id)
        except GrabResolveError:
            return None
        return None
    return url_for("stream_video", show_id=show_id, filename=episode.filename)


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _contained_dir(base_root: Path, folder: Path) -> Path | None:
    """Return resolved dir only if it stays under ``base_root``."""
    try:
        resolved = folder.resolve()
    except OSError:
        return None
    if not resolved.is_dir():
        return None
    if not _path_is_under(resolved, base_root) and resolved != base_root:
        return None
    return resolved


def _normalize_media_relpath(filename: str) -> str | None:
    """Return a safe relative path under a show folder, or None if unsafe."""
    normalized = filename.replace('\\', "/").strip().lstrip("/")
    if not normalized:
        return None
    # Reject Windows drive / UNC style paths.
    if len(normalized) >= 2 and normalized[1] == ":":
        return None
    if normalized.startswith("//"):
        return None
    parts = tuple(p for p in normalized.split("/") if p not in ("", "."))
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def _resolve_show_dir(base: Path, show_id: str) -> Path | None:
    """Resolve the on-disk show folder for ``show_id`` under ``base``."""
    if not base.exists():
        return None
    root = base.resolve()
    for folder in base.iterdir():
        if folder.is_dir() and slugify(folder.name) == show_id:
            found = _contained_dir(root, folder)
            if found:
                return found
    catalog = load_catalog()
    entry = catalog.get(show_id)
    if entry and entry.folder:
        if ".." in Path(entry.folder).parts:
            return None
        return _contained_dir(root, base / entry.folder)
    return None


def _resolve_local_path(base: Path, show_id: str, filename: str) -> Path | None:
    """Resolve a media file under ``base``; reject path traversal.

    ``filename`` may be a basename or a relative path inside the show folder
    (as stored by library scan for nested season episodes).
    """
    rel = _normalize_media_relpath(filename)
    if not rel:
        return None
    show_dir = _resolve_show_dir(base, show_id)
    if not show_dir:
        return None
    root = base.resolve()
    try:
        target = (show_dir / rel).resolve()
    except OSError:
        return None
    if not _path_is_under(target, root):
        return None
    try:
        target.relative_to(show_dir.resolve())
    except ValueError:
        return None
    return target if target.is_file() else None


def _resolve_local_poster(base: Path, show_id: str) -> Path | None:
    if not base.exists():
        return None
    root = base.resolve()

    def _safe_poster(folder: Path) -> Path | None:
        contained = _contained_dir(root, folder)
        if not contained:
            return None
        for name in ("poster.jpg", "poster.png", "folder.jpg", "cover.jpg"):
            candidate = (contained / name).resolve()
            if _path_is_under(candidate, root) and candidate.is_file():
                return candidate
        return None

    for folder in base.iterdir():
        if folder.is_dir() and slugify(folder.name) == show_id:
            found = _safe_poster(folder)
            if found:
                return found
    catalog = load_catalog()
    entry = catalog.get(show_id)
    if entry and entry.folder:
        if ".." in Path(entry.folder).parts:
            return None
        return _safe_poster(base / entry.folder)
    return None



def _random_library_sample(shows: list[Show], limit: int = 5) -> list[Show]:
    """Pick up to `limit` shows at random for Featured / recommendations.

    Samples from the full library each call (new set/order per page load).
    Prefers titles with posters when choosing, then shuffles the result.
    """
    if not shows or limit <= 0:
        return []

    with_poster = [s for s in shows if s.poster_url or s.poster]
    without = [s for s in shows if not (s.poster_url or s.poster)]
    picks: list[Show] = []
    if with_poster:
        picks.extend(random.sample(with_poster, min(limit, len(with_poster))))
    if len(picks) < limit and without:
        picks.extend(random.sample(without, min(limit - len(picks), len(without))))
    random.shuffle(picks)
    return picks


def _continue_watching(
    shows: list[Show],
    progress: dict[str, float],
    completed: dict[str, int],
    limit: int = 12,
) -> list[tuple[Show, Episode]]:
    """Shows in Watching/On-Hold with a next unwatched episode."""
    allowed = frozenset({"watching", "on_hold"})
    pairs: list[tuple[Show, Episode]] = []
    for show in shows:
        status = (show.list_status or "").casefold()
        if status not in allowed:
            continue
        nxt = next_unwatched_episode(show, progress, completed)
        if nxt:
            pairs.append((show, nxt))
    pairs.sort(key=lambda pair: pair[0].title.casefold())
    return pairs[:limit]


def main() -> None:
    create_app().run(host="127.0.0.1", port=5001, debug=False)


if __name__ == "__main__":
    main()
