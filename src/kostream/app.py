from __future__ import annotations

from pathlib import Path

from flask import Flask, abort, render_template, request, send_from_directory, url_for

from kostream.library import (
    MEDIA_ROOT,
    get_show,
    load_progress,
    save_progress,
    scan_library,
)
from kostream.models import Episode, Show, slugify

PROGRESS_FILE = Path(__file__).resolve().parents[2] / "data" / "progress.json"


def create_app(media_root: Path | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["MEDIA_ROOT"] = media_root or MEDIA_ROOT

    @app.context_processor
    def inject_globals():
        return {"site_name": "Ko-Stream"}

    @app.route("/")
    def home():
        shows = scan_library(app.config["MEDIA_ROOT"])
        return render_template(
            "home.html",
            spotlight=shows[:10],
            trending=shows[:12],
            top_airing=shows[:5],
            most_popular=shows[:5],
            latest=_latest_episodes(shows, limit=12),
            top10=shows[:10],
        )

    @app.route("/show/<show_id>")
    def show_detail(show_id: str):
        show = get_show(show_id, app.config["MEDIA_ROOT"])
        if not show:
            abort(404)
        return render_template(
            "show.html",
            show=show,
            progress=load_progress(PROGRESS_FILE),
        )

    @app.route("/watch/<show_id>/<episode_id>")
    def watch(show_id: str, episode_id: str):
        show = get_show(show_id, app.config["MEDIA_ROOT"])
        if not show:
            abort(404)
        episode = next((e for e in show.episodes if e.id == episode_id), None)
        if not episode:
            abort(404)
        idx = show.episodes.index(episode)
        nxt = show.episodes[idx + 1] if idx + 1 < len(show.episodes) else None
        is_demo = episode.filename == "demo.mp4"
        video_url = None if is_demo else url_for(
            "stream_video", show_id=show_id, filename=episode.filename
        )
        return render_template(
            "watch.html",
            show=show,
            episode=episode,
            next_episode=nxt,
            video_url=video_url,
            is_demo=is_demo,
        )

    @app.route("/media/<show_id>/<path:filename>")
    def stream_video(show_id: str, filename: str):
        base: Path = app.config["MEDIA_ROOT"]
        if not base.exists():
            abort(404)
        for folder in base.iterdir():
            if folder.is_dir() and slugify(folder.name) == show_id:
                return send_from_directory(folder, filename)
        abort(404)

    @app.route("/api/progress", methods=["POST"])
    def api_progress():
        payload = request.get_json(silent=True) or {}
        ep_id = payload.get("episode_id")
        seconds = payload.get("seconds")
        if not ep_id or seconds is None:
            abort(400)
        data = load_progress(PROGRESS_FILE)
        data[ep_id] = float(seconds)
        save_progress(PROGRESS_FILE, data)
        return {"ok": True}

    @app.route("/search")
    def search():
        q = request.args.get("q", "").strip().lower()
        shows = scan_library(app.config["MEDIA_ROOT"])
        if q:
            shows = [s for s in shows if q in s.title.lower()]
        return render_template("search.html", shows=shows, query=q)

    return app


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
