from __future__ import annotations

import random
from pathlib import Path
from datetime import datetime
from urllib.error import URLError

from flask import Flask, Response, abort, redirect, render_template, request, send_file, url_for

from kostream.anilist import AniListError, fetch_anime, fetch_mal_id, search_anime
from kostream.browse import (
    AVAIL_ALL,
    PAGE_SIZE,
    collect_genres,
    filter_shows,
    normalize_availability,
    paginate,
)
from kostream.catalog import (
    CATALOG_DIR,
    SELECTED_FILE,
    CatalogEntry,
    CatalogState,
    load_catalog,
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
    MalConfig,
    MalError,
    complete_oauth,
    complete_oauth_with_code,
    disconnect as mal_disconnect,
    get_valid_access_token,
    is_connected as mal_is_connected,
    load_last_sync,
    format_last_sync_label,
    load_tokens as mal_load_tokens,
    prepare_oauth,
    start_oauth,
    enrich_catalog_mal_details,
    ensure_anime_details,
    ensure_anime_details_async,
    ensure_episode_titles_async,
    enrich_mal_details,
    cache_needs_enrichment,
    episode_titles_need_fetch,
    load_cached_anime,
    merge_anime_details_into_cache,
    sync_animelist_to_catalog,
    sync_mangalist_to_catalog,
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
    get_chapter,
    get_manga,
    list_page_refs,
    load_manga_library,
    read_page_bytes,
    title_matches_genre,
)
from kostream.manga_catalog import MANGA_SELECTED_FILE
from kostream.manga_progress import (
    MANGA_COMPLETED_FILE,
    chapter_completed,
    chapter_position,
    chapters_read_count,
    filter_currently_publishing,
    filter_currently_reading,
    load_manga_completed,
    manga_reading_status,
    mark_chapter_read,
    mark_chapters_read_through,
    mark_manga_completed,
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
from kostream.local_registry import list_for_show
from kostream.stream_fetch import StreamFetchError, ffmpeg_available, resolve_fetch_source

from kostream.models import (
    Episode,
    Show,
    is_jellyfin_episode,
    is_strm_episode,
    jellyfin_item_id,
    slugify,
    strm_target_url,
)
from kostream.relations import build_relation_links, mal_anime_url
from kostream.proxy import proxy_remote_stream
from kostream.watch_progress import (
    episode_completed,
    filter_currently_airing,
    load_completed,
    mark_episode_watched,
    mark_show_completed,
    next_unwatched_episode,
    recently_added,
    save_completed,
    sort_by_mean_score,
)
from kostream.sync_jobs import get_sync_job, start_mal_sync
from kostream.schedule import WEEKDAY_KEYS, build_weekly_schedule
from kostream.streaming import stream_file_with_range


import m3u8
from urllib.parse import urljoin

PROGRESS_FILE = Path(__file__).resolve().parents[2] / "data" / "progress.json"
COMPLETED_FILE = Path(__file__).resolve().parents[2] / "data" / "completed.json"


def create_app(
    media_root: Path | None = None,
    catalog_path: Path | None = None,
    grab_base: Path | None = None,
    manga_root: Path | None = None,
    manga_catalog_path: Path | None = None,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["MEDIA_ROOT"] = media_root or MEDIA_ROOT
    app.config["CATALOG_PATH"] = catalog_path or SELECTED_FILE
    app.config["GRAB_DIR"] = grab_base if grab_base is not None else grab_dir()
    app.config["MANGA_ROOT"] = manga_root if manga_root is not None else MANGA_ROOT
    app.config["MANGA_CATALOG_PATH"] = (
        manga_catalog_path if manga_catalog_path is not None else MANGA_SELECTED_FILE
    )
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
        mal_tokens = mal_load_tokens()
        try:
            mal_configured = MalConfig.from_env() is not None
        except MalError:
            mal_configured = False
        return {
            "site_name": "Ko-Stream",
            "jellyfin_connected": jellyfin is not None,
            "mal_connected": mal_is_connected(),
            "mal_username": mal_tokens.username if mal_tokens else None,
            "mal_configured": mal_configured,
            "grab_enabled": grab_enabled(),
            "grab_has_resolver": bool(grab_cmd()),
            "grab_demo_enabled": grab_demo_enabled(),
            "catalog_count": len(catalog.enabled),
            "poster_for": _poster_for,
            "episode_completed": episode_completed,
            "next_unwatched_episode": next_unwatched_episode,
            "progress": load_progress(PROGRESS_FILE),
            "completed": load_completed(COMPLETED_FILE),
        }

    @app.route("/")
    def home():
        shows = scan_library(app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
        progress = load_progress(PROGRESS_FILE)
        completed = load_completed(COMPLETED_FILE)
        currently_airing = filter_currently_airing(shows)
        manga_titles = load_manga_library(
            app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        manga_completed = load_manga_completed(MANGA_COMPLETED_FILE)
        currently_reading = filter_currently_reading(manga_titles, manga_completed)
        currently_releasing = filter_currently_publishing(manga_titles)
        reading_manga = filter_library_format(currently_reading, kind="manga")
        reading_manhwa = filter_library_format(currently_reading, kind="manhwa")
        releasing_manga = filter_library_format(currently_releasing, kind="manga")
        releasing_manhwa = filter_library_format(currently_releasing, kind="manhwa")
        return render_template(
            "home.html",
            spotlight=shows[:10],
            trending=sort_by_mean_score(shows, limit=12),
            currently_airing=currently_airing[:12],
            top_airing=currently_airing[:5],
            most_popular=_random_library_sample(shows, limit=5),
            latest=_continue_watching(shows, progress, completed, limit=12),
            new_on_kostream=recently_added(shows, limit=12),
            currently_reading_manga=reading_manga[:12],
            currently_reading_manhwa=reading_manhwa[:12],
            currently_releasing_manga=releasing_manga[:12],
            currently_releasing_manhwa=releasing_manhwa[:12],
            progress=progress,
            completed=completed,
        )

    @app.route("/schedule")
    def schedule_page():
        mode = (request.args.get("mode") or "anime").strip().lower()
        if mode not in {"anime", "manga", "manhwa"}:
            mode = "anime"
        shows = scan_library(app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
        days, unknown = build_weekly_schedule(shows)
        today_key = WEEKDAY_KEYS[datetime.now().weekday()]
        manga_titles = load_manga_library(
            app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
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
        all_titles = load_manga_library(
            app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        titles = filter_library_format(all_titles, kind=kind)
        completed = load_manga_completed(MANGA_COMPLETED_FILE)
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
        return render_template(
            "manga.html",
            titles=titles,
            mal_manga_count=mal_n,
            manga_completed=completed,
            chapter_completed=chapter_completed,
            manga_reading_status=manga_reading_status,
            chapters_read_count=chapters_read_count,
            title_matches_genre=title_matches_genre,
            active_tab=tab,
            selected_avail=avail,
            selected_genre=genre,
            genres=genres,
            open_manga_id=open_id,
            library_kind=kind,
            library_label="Manhwa" if kind == "manhwa" else "Manga",
        )

    @app.route("/api/manga/<manga_id>/pages")
    def api_manga_pages(manga_id: str):
        manga = get_manga(
            manga_id, app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        if not manga or not manga.chapters:
            return {"ok": False, "error": "Manga not found or no local chapters"}, 404
        chapter = manga.chapters[0]
        try:
            pages = list_page_refs(app.config["MANGA_ROOT"], manga, chapter)
        except MangaError as exc:
            return {"ok": False, "error": str(exc)}, 400
        return {
            "ok": True,
            "manga_id": manga.id,
            "chapter_id": chapter.id,
            "chapter_title": chapter.title,
            "pages": pages,
        }

    @app.route("/api/manga/<manga_id>/chapter/<chapter_id>/pages")
    def api_manga_chapter_pages(manga_id: str, chapter_id: str):
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
        return {
            "ok": True,
            "manga_id": manga.id,
            "chapter_id": chapter.id,
            "chapter_title": chapter.title,
            "pages": pages,
        }

    @app.route("/api/manga/complete", methods=["POST"])
    def api_manga_complete():
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

        chapters_read = mark_chapter_read(manga, chapter_id, MANGA_COMPLETED_FILE)
        mal_synced = False
        mal_error = None
        cfg = MalConfig.from_env()
        if cfg and manga.mal_id and mal_is_connected():
            try:
                total = manga.num_chapters_mal or manga.chapter_count
                status = (
                    "completed"
                    if total and chapters_read >= total
                    else "reading"
                )
                update_chapters_read(cfg, manga.mal_id, chapters_read, status=status)
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
        payload = request.get_json(silent=True) or {}
        manga_id = payload.get("manga_id")
        if not manga_id:
            abort(400)
        manga = get_manga(
            manga_id, app.config["MANGA_ROOT"], app.config["MANGA_CATALOG_PATH"]
        )
        if not manga:
            abort(404)

        chapters_read = mark_manga_completed(manga, MANGA_COMPLETED_FILE)
        mal_synced = False
        mal_error = None
        cfg = MalConfig.from_env()
        if cfg and manga.mal_id and mal_is_connected():
            try:
                total = max(manga.num_chapters_mal, manga.chapter_count, chapters_read)
                update_chapters_read(
                    cfg, manga.mal_id, total, status="completed"
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
            manga, to_pos, MANGA_COMPLETED_FILE
        )
        mal_synced = False
        mal_error = None
        cfg = MalConfig.from_env()
        if cfg and manga.mal_id and mal_is_connected():
            try:
                total = manga.num_chapters_mal or manga.chapter_count
                status = (
                    "completed"
                    if total and chapters_read >= total
                    else "reading"
                )
                update_chapters_read(cfg, manga.mal_id, chapters_read, status=status)
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
        mal_tokens = mal_load_tokens()
        mal_count = sum(1 for e in catalog.shows if e.source == "mal")
        mal_client_hint = None
        if mal_cfg:
            mal_client_hint = f"{mal_cfg.client_id[:4]}…{mal_cfg.client_id[-4:]} ({len(mal_cfg.client_id)} chars)"
        return render_template(
            "catalog.html",
            catalog=catalog,
            catalog_path=app.config["CATALOG_PATH"],
            mal_redirect_uri=mal_cfg.redirect_uri if mal_cfg else None,
            mal_client_hint=mal_client_hint,
            mal_count=mal_count,
            mal_last_sync=format_last_sync_label(load_last_sync()),
            mal_message=request.args.get("mal_message"),
            mal_error=request.args.get("mal_error"),
        )

    @app.route("/auth/mal/connect")
    def mal_connect():
        try:
            cfg = MalConfig.from_env()
        except MalError as exc:
            return redirect(url_for("catalog_page", mal_error=str(exc)))
        if not cfg:
            return redirect(url_for("catalog_page", mal_error="Set MAL_CLIENT_ID and MAL_CLIENT_SECRET first."))
        urls = prepare_oauth(cfg)
        return render_template(
            "mal_connect.html",
            authorize_url=urls["authorize_url"],
            login_first_url=urls["login_first_url"],
            redirect_uri=cfg.redirect_uri,
        )

    @app.route("/auth/mal/callback")
    def mal_callback():
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
            complete_oauth(cfg, code, state)
            count = sync_animelist_to_catalog(cfg, app.config["CATALOG_PATH"])
            manga_count = sync_mangalist_to_catalog(
                cfg,
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
        cfg = MalConfig.from_env()
        if not cfg:
            return redirect(url_for("catalog_page", mal_error="MAL not configured."))
        raw_code = (request.form.get("code") or "").strip()
        if not raw_code:
            return redirect(url_for("catalog_page", mal_error="Paste the authorization code or callback URL."))
        try:
            complete_oauth_with_code(cfg, raw_code)
            count = sync_animelist_to_catalog(cfg, app.config["CATALOG_PATH"])
            manga_count = sync_mangalist_to_catalog(
                cfg,
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
    @app.route("/api/mal/sync", methods=["POST"])
    def api_mal_sync():
        cfg = MalConfig.from_env()
        if not cfg:
            return {"ok": False, "error": "MAL not configured"}, 400
        if not mal_is_connected():
            return {"ok": False, "error": "Not connected to MyAnimeList"}, 401
        job = start_mal_sync(
            cfg,
            app.config["CATALOG_PATH"],
            manga_catalog_path=app.config["MANGA_CATALOG_PATH"],
            manga_media_root=app.config["MANGA_ROOT"],
        )
        return {"ok": True, "started": True, **job.to_dict()}

    @app.route("/api/mal/sync/status")
    def api_mal_sync_status():
        return get_sync_job().to_dict()

    @app.route("/api/show/<show_id>/relations-ready")
    def api_show_relations_ready(show_id: str):
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
        if not show or not show.mal_id:
            return {"ready": True, "has_titles": False}
        ready = not episode_titles_need_fetch(show.mal_id)
        cached = load_cached_anime(show.mal_id)
        has_titles = bool(cached and cached.episode_titles)
        return {"ready": ready, "has_titles": has_titles}

    @app.route("/api/mal/disconnect", methods=["POST"])
    def api_mal_disconnect():
        mal_disconnect()
        catalog = load_catalog(app.config["CATALOG_PATH"])
        catalog = CatalogState(shows=[s for s in catalog.shows if s.source != "mal"])
        save_catalog(catalog, app.config["CATALOG_PATH"])
        return {"ok": True}

    @app.route("/api/catalog/toggle", methods=["POST"])
    def api_catalog_toggle():
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
        payload = request.get_json(silent=True) or {}
        source = payload.get("source", "local")
        folder = payload.get("folder")
        anilist_id = payload.get("anilist_id")
        title = payload.get("title")
        entry_id = payload.get("id") or slugify(folder or title or "show")
        mal_id = int(payload["mal_id"]) if payload.get("mal_id") is not None else None
        if not mal_id and anilist_id:
            try:
                mal_id = fetch_mal_id(int(anilist_id))
            except (AniListError, URLError, OSError, ValueError):
                mal_id = None
        entry = CatalogEntry(
            id=entry_id,
            enabled=True,
            source=source,
            folder=folder,
            anilist_id=int(anilist_id) if anilist_id else None,
            mal_id=mal_id,
            title=title,
            jellyfin_id=payload.get("jellyfin_id"),
        )
        state = load_catalog(app.config["CATALOG_PATH"])
        state = upsert_entry(state, entry)
        save_catalog(state, app.config["CATALOG_PATH"])

        enriched = False
        cfg = MalConfig.from_env()
        if cfg and mal_id and mal_is_connected():
            try:
                access_token = get_valid_access_token(cfg)
                merge_anime_details_into_cache(access_token, mal_id, title_fallback=title)
                enriched = True
            except MalError:
                enriched = False
        # Jikan episode titles do not need MAL OAuth; kick off when we have an id.
        if mal_id:
            ensure_episode_titles_async(mal_id)

        return {"ok": True, "id": entry.id, "mal_id": mal_id, "enriched": enriched}

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
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
        if not show:
            abort(404)

        # Lazy-load prequel/sequel without blocking the page (background enrich).
        relations_pending = False
        titles_pending = False
        if show.mal_id:
            if mal_is_connected():
                if cache_needs_enrichment(show.mal_id):
                    relations_pending = True
                    cfg = MalConfig.from_env()
                    if cfg:
                        ensure_anime_details_async(cfg, show.mal_id)
                else:
                    cached = load_cached_anime(show.mal_id)
                    if cached:
                        from kostream.watch_progress import apply_mal_metadata

                        apply_mal_metadata(show, cached)
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
        return render_template(
            "show.html",
            show=show,
            relation_links=relation_links,
            relations_pending=relations_pending,
            titles_pending=titles_pending,
            local_info=local_info,
            mal_page_url=mal_anime_url(show.mal_id) if show.mal_id else None,
        )

    @app.route("/api/show/<show_id>/local-info")
    def api_show_local_info(show_id: str):
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
        if not show:
            abort(404)
        return build_local_info(
            show, app.config["MEDIA_ROOT"], catalog_path=app.config["CATALOG_PATH"]
        )

    @app.route("/api/show/<show_id>/prepare-folder", methods=["POST"])
    def api_show_prepare_folder(show_id: str):
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        refreshed = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        if not grab_enabled():
            return {"ok": False, "error": "Grab is disabled (KOSTREAM_GRAB=0)"}, 400
        payload = request.get_json(silent=True) or {}
        show_id = payload.get("show_id")
        episode_id = payload.get("episode_id")
        url = payload.get("url")
        if not show_id or not episode_id or not url:
            abort(400)
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        if not grab_enabled():
            return {"ok": False, "error": "Grab is disabled (KOSTREAM_GRAB=0)"}, 400
        payload = request.get_json(silent=True) or {}
        show_id = payload.get("show_id")
        urls = payload.get("urls") or {}
        if not show_id or not isinstance(urls, dict) or not urls:
            abort(400)
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
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
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
        if not show:
            abort(404)
        episode = next((e for e in show.episodes if e.id == episode_id), None)
        if not episode:
            abort(404)
        if episode.filename != "demo.mp4":
            return {"ok": False, "error": "Episode already has a local/remote file"}, 400
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
        payload = request.get_json(silent=True) or {}
        ep_id = payload.get("episode_id")
        seconds = payload.get("seconds")
        if not ep_id or seconds is None:
            abort(400)
        data = load_progress(PROGRESS_FILE)
        duration = payload.get("duration")
        entry: dict = {"seconds": float(seconds)}
        if duration is not None:
            try:
                dur = float(duration)
                if dur > 0:
                    entry["duration"] = dur
            except (TypeError, ValueError):
                pass
        # Preserve prior duration if client omitted it this tick
        prev = data.get(ep_id)
        if "duration" not in entry and isinstance(prev, dict) and prev.get("duration"):
            entry["duration"] = prev["duration"]
        data[ep_id] = entry
        save_progress(PROGRESS_FILE, data)
        return {"ok": True}

    @app.route("/api/episodes/complete", methods=["POST"])
    def api_episode_complete():
        payload = request.get_json(silent=True) or {}
        show_id = payload.get("show_id")
        episode_id = payload.get("episode_id")
        if not show_id or not episode_id:
            abort(400)
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
        if not show:
            abort(404)
        episode = next((e for e in show.episodes if e.id == episode_id), None)
        if not episode:
            abort(404)

        watched_count = mark_episode_watched(show, episode, COMPLETED_FILE)
        mal_synced = False
        mal_error = None
        cfg = MalConfig.from_env()
        if cfg and show.mal_id and mal_is_connected():
            try:
                total_eps = show.episode_count
                status = "completed" if total_eps and watched_count >= total_eps else "watching"
                update_episodes_watched(cfg, show.mal_id, watched_count, status=status)
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
        payload = request.get_json(silent=True) or {}
        show_id = payload.get("show_id")
        if not show_id:
            abort(400)
        show = get_show(show_id, app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
        if not show:
            abort(404)

        watched_count = mark_show_completed(show, COMPLETED_FILE)
        mal_synced = False
        mal_error = None
        cfg = MalConfig.from_env()
        if cfg and show.mal_id and mal_is_connected():
            try:
                total = max(show.episode_count or 0, len(show.episodes), watched_count)
                update_episodes_watched(cfg, show.mal_id, total, status="completed")
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

    @app.route("/search")
    def search():
        q = request.args.get("q", "").strip()
        genre = request.args.get("genre", "").strip()
        availability = normalize_availability(request.args.get("avail", AVAIL_ALL))
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1

        all_shows = scan_library(app.config["MEDIA_ROOT"], app.config["CATALOG_PATH"])
        genres = collect_genres(all_shows)
        filtered = filter_shows(all_shows, q, genre, availability)
        shows, page, total_pages = paginate(filtered, page, PAGE_SIZE)

        return render_template(
            "search.html",
            shows=shows,
            query=q,
            selected_genre=genre,
            selected_avail=availability,
            genres=genres,
            page=page,
            total_pages=total_pages,
            total_count=len(filtered),
            page_size=PAGE_SIZE,
        )

    return app



def _poster_for(show: Show) -> str | None:
    if show.poster_url:
        return show.poster_url
    if show.poster:
        return url_for("local_poster", show_id=show.id)
    if show.anilist_id:
        meta = fetch_anime(show.anilist_id, network=False)
        if meta and meta.poster_url:
            return meta.poster_url
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


def _resolve_local_path(base: Path, show_id: str, filename: str) -> Path | None:
    if not base.exists():
        return None
    for folder in base.iterdir():
        if folder.is_dir() and slugify(folder.name) == show_id:
            target = folder / filename
            if target.is_file():
                return target
    catalog = load_catalog()
    entry = catalog.get(show_id)
    if entry and entry.folder:
        target = base / entry.folder / filename
        if target.is_file():
            return target
    return None


def _resolve_local_poster(base: Path, show_id: str) -> Path | None:
    if not base.exists():
        return None
    for folder in base.iterdir():
        if folder.is_dir() and slugify(folder.name) == show_id:
            for name in ("poster.jpg", "poster.png", "folder.jpg", "cover.jpg"):
                candidate = folder / name
                if candidate.is_file():
                    return candidate
    catalog = load_catalog()
    entry = catalog.get(show_id)
    if entry and entry.folder:
        folder = base / entry.folder
        for name in ("poster.jpg", "poster.png", "folder.jpg", "cover.jpg"):
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None



def _random_library_sample(shows: list[Show], limit: int = 5) -> list[Show]:
    """Pick up to `limit` shows at random, preferring titles with posters."""
    if len(shows) <= limit:
        return list(shows)
    with_poster = [s for s in shows if s.poster_url or getattr(s, "poster", None)]
    without = [s for s in shows if s not in with_poster]
    random.shuffle(with_poster)
    random.shuffle(without)
    return (with_poster + without)[:limit]


def _continue_watching(
    shows: list[Show],
    progress: dict[str, float],
    completed: dict[str, int],
    limit: int = 12,
) -> list[tuple[Show, Episode]]:
    """Shows with a next unwatched episode (MAL progress or local resume)."""
    pairs: list[tuple[Show, Episode]] = []
    for show in shows:
        nxt = next_unwatched_episode(show, progress, completed)
        if nxt and show.list_status != "completed":
            pairs.append((show, nxt))
    pairs.sort(key=lambda pair: pair[0].title.casefold())
    return pairs[:limit]


def _latest_episodes(shows: list[Show], limit: int = 12) -> list[tuple[Show, Episode]]:
    pairs: list[tuple[Show, Episode]] = []
    for show in shows:
        ep = show.latest_episode
        if ep:
            pairs.append((show, ep))
    return pairs[:limit]


def main() -> None:
    create_app().run(host="127.0.0.1", port=5001, debug=False)


if __name__ == "__main__":
    main()
