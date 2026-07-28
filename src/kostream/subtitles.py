"""Discover WebVTT sidecar subtitle files next to local episode videos."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Common filename tokens → BCP-47 + display label.
_LANG_MAP: dict[str, tuple[str, str]] = {
    "en": ("en", "English"),
    "eng": ("en", "English"),
    "de": ("de", "German"),
    "ger": ("de", "German"),
    "deu": ("de", "German"),
    "ja": ("ja", "Japanese"),
    "jpn": ("ja", "Japanese"),
    "es": ("es", "Spanish"),
    "spa": ("es", "Spanish"),
    "fr": ("fr", "French"),
    "fre": ("fr", "French"),
    "fra": ("fr", "French"),
    "pt": ("pt", "Portuguese"),
    "ru": ("ru", "Russian"),
    "zh": ("zh", "Chinese"),
    "chi": ("zh", "Chinese"),
    "ko": ("ko", "Korean"),
    "kor": ("ko", "Korean"),
    "it": ("it", "Italian"),
    "ar": ("ar", "Arabic"),
}


@dataclass(frozen=True)
class SubtitleTrack:
    """A WebVTT file relative to the show folder (for ``/media/<show>/<relpath>``)."""

    relpath: str
    lang: str
    label: str


def discover_vtt_sidecars(video_path: Path, *, show_dir: Path) -> list[SubtitleTrack]:
    """Return WebVTT tracks sharing the video stem in the same directory.

    Matches ``Episode.vtt``, ``Episode.en.vtt``, ``Episode.de.forced.vtt``, etc.
    Does not extract embedded softsubs from MKV/MP4 containers.
    """
    if not video_path.is_file():
        return []
    try:
        show_resolved = show_dir.resolve()
        video_resolved = video_path.resolve()
        video_resolved.relative_to(show_resolved)
    except (OSError, ValueError):
        return []

    stem = video_path.stem
    parent = video_path.parent
    tracks: list[SubtitleTrack] = []
    seen: set[str] = set()

    try:
        entries = list(parent.iterdir())
    except OSError:
        return []

    for path in sorted(entries, key=lambda p: p.name.casefold()):
        if not path.is_file() or path.suffix.lower() != ".vtt":
            continue
        # Exact stem or stem.<lang…>.vtt — avoid S01E01* matching S01E010.en.vtt
        name = path.name
        if name != f"{stem}.vtt" and not name.startswith(f"{stem}."):
            continue
        try:
            rel = path.resolve().relative_to(show_resolved).as_posix()
        except (OSError, ValueError):
            continue
        if rel in seen:
            continue
        seen.add(rel)
        lang, label = parse_vtt_label(stem, path.name)
        tracks.append(SubtitleTrack(relpath=rel, lang=lang, label=label))
    return tracks


def parse_vtt_label(video_stem: str, vtt_filename: str) -> tuple[str, str]:
    """Derive ``(lang, label)`` from a VTT filename next to ``video_stem``."""
    name = Path(vtt_filename).name
    lower = name.lower()
    if not lower.endswith(".vtt"):
        return "und", "Subtitles"
    base = name[: -len(".vtt")]
    if base == video_stem:
        return "und", "Subtitles"
    prefix = f"{video_stem}."
    if not base.startswith(prefix):
        return "und", base or "Subtitles"
    rest = base[len(prefix) :]
    if not rest:
        return "und", "Subtitles"
    token = rest.split(".", 1)[0].casefold()
    mapped = _LANG_MAP.get(token)
    if mapped:
        lang, label = mapped
        extra = rest[len(token) :].strip(".")
        if extra:
            return lang, f"{label} ({extra})"
        return lang, label
    if 2 <= len(token) <= 3 and token.isalpha():
        return token, token.upper()
    return "und", rest.replace(".", " ")
