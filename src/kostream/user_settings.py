"""Per-user settings stored under ``data/users/<user_id>/settings.json``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kostream.jsonio import atomic_write_json
from kostream.titles import DEFAULT_TITLE_LANG, normalize_title_lang


def load_user_settings(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_user_settings(path: Path, settings: dict[str, Any]) -> None:
    payload = dict(settings) if isinstance(settings, dict) else {}
    atomic_write_json(path, payload, ensure_ascii=False)


def get_title_language(path: Path | None) -> str:
    settings = load_user_settings(path)
    return normalize_title_lang(settings.get("title_language"))


def set_title_language(path: Path, lang: str | None) -> str:
    normalized = normalize_title_lang(lang)
    settings = load_user_settings(path)
    settings["title_language"] = normalized
    save_user_settings(path, settings)
    return normalized
