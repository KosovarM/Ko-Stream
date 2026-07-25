from __future__ import annotations

import json
import re
from pathlib import Path

from localstream.models import Episode, Show, VIDEO_EXTENSIONS, slugify

MEDIA_ROOT = Path(__file__).resolve().parents[2] / "media" / "shows"
EPISODE_PATTERN = re.compile(
    r"(?:[Ss](?P<season>\d+)[Ee](?P<ep>\d+)|(?P<ep2>\d+)x(?P<season2>\d+))",
    re.IGNORECASE,
)


def scan_library(root: Path | None = None) -> list[Show]:
    """Scan media/shows/<SeriesName>/ for video files."""
    base = root or MEDIA_ROOT
    if not base.exists():
        return _demo_shows()

    shows: list[Show] = []
    for show_dir in sorted(base.iterdir()):
        if not show_dir.is_dir():
            continue
        episodes = _scan_show_folder(show_dir)
        if not episodes:
            continue
        show_id = slugify(show_dir.name)
        poster = _find_poster(show_dir)
        shows.append(
            Show(
                id=show_id,
                title=show_dir.name.replace("-", " ").replace("_", " "),
                description=f"Local library — {len(episodes)} episode(s)",
                poster=poster,
                episodes=episodes,
                genres=["Local"],
            )
        )
    return shows if shows else _demo_shows()


def _scan_show_folder(show_dir: Path) -> list[Episode]:
    show_id = slugify(show_dir.name)
    episodes: list[Episode] = []
    for path in sorted(show_dir.rglob("*")):
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        season, number = _parse_episode_numbers(path.name)
        rel = path.relative_to(show_dir)
        episodes.append(
            Episode(
                id=f"{show_id}-s{season:02d}e{number:02d}",
                show_id=show_id,
                season=season,
                number=number,
                title=path.stem,
                filename=str(rel).replace("\\", "/"),
            )
        )
    return sorted(episodes, key=lambda e: (e.season, e.number))


def _parse_episode_numbers(name: str) -> tuple[int, int]:
    match = EPISODE_PATTERN.search(name)
    if match:
        if match.group("season"):
            return int(match.group("season")), int(match.group("ep"))
        return int(match.group("season2")), int(match.group("ep2"))
    return 1, 1


def _find_poster(show_dir: Path) -> str | None:
    for name in ("poster.jpg", "poster.png", "folder.jpg", "cover.jpg"):
        candidate = show_dir / name
        if candidate.exists():
            return candidate.name
    return None


def get_show(show_id: str, root: Path | None = None) -> Show | None:
    for show in scan_library(root):
        if show.id == show_id:
            return show
    return None


def _demo_shows() -> list[Show]:
    """Placeholder catalog when media/ is empty — demonstrates Aniwatch-style UI."""
    return [
        Show(
            id="demo-one-piece",
            title="Demo — One Piece (local)",
            description="Add your own files under media/shows/One Piece/ to replace this demo entry.",
            type_label="TV",
            genres=["Adventure", "Demo"],
            episodes=[
                Episode("demo-1", "demo-one-piece", 1, 1, "Episode 1", "demo.mp4"),
            ],
        ),
        Show(
            id="demo-frieren",
            title="Demo — Frieren Season 2",
            description="Place videos as S01E01.mp4 in a folder under media/shows/.",
            type_label="TV",
            genres=["Fantasy", "Demo"],
            episodes=[
                Episode("demo-f1", "demo-frieren", 2, 1, "Episode 1", "demo.mp4"),
            ],
        ),
        Show(
            id="demo-jujutsu",
            title="Demo — Jujutsu Kaisen",
            description="Supports S01E01 naming or 1x01 pattern.",
            type_label="TV",
            genres=["Action", "Demo"],
            episodes=[
                Episode("demo-j1", "demo-jujutsu", 1, 11, "Episode 11", "demo.mp4"),
            ],
        ),
    ]


def load_progress(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_progress(path: Path, data: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
