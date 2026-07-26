"""JSON registry of locally available episode assets."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY = Path(__file__).resolve().parents[2] / "data" / "local_registry.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"episodes": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"episodes": {}}
    if not isinstance(raw, dict):
        return {"episodes": {}}
    episodes = raw.get("episodes")
    if not isinstance(episodes, dict):
        raw["episodes"] = {}
    return raw


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def registry_key(show_id: str, episode_id: str) -> str:
    return f"{show_id}/{episode_id}"


def mark_local(
    show_id: str,
    episode_id: str,
    *,
    path: str,
    filename: str,
    source_url: str | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    file_path = registry_path or DEFAULT_REGISTRY
    data = _load(file_path)
    entry = {
        "show_id": show_id,
        "episode_id": episode_id,
        "path": path,
        "filename": filename,
        "source_url": source_url,
        "updated_at": int(time.time()),
    }
    data["episodes"][registry_key(show_id, episode_id)] = entry
    _save(file_path, data)
    return entry


def unmark_local(
    show_id: str,
    episode_id: str,
    *,
    registry_path: Path | None = None,
) -> bool:
    file_path = registry_path or DEFAULT_REGISTRY
    data = _load(file_path)
    key = registry_key(show_id, episode_id)
    if key not in data["episodes"]:
        return False
    del data["episodes"][key]
    _save(file_path, data)
    return True


def get_local(
    show_id: str,
    episode_id: str,
    *,
    registry_path: Path | None = None,
) -> dict[str, Any] | None:
    data = _load(registry_path or DEFAULT_REGISTRY)
    entry = data["episodes"].get(registry_key(show_id, episode_id))
    return entry if isinstance(entry, dict) else None


def list_for_show(
    show_id: str,
    *,
    registry_path: Path | None = None,
) -> list[dict[str, Any]]:
    data = _load(registry_path or DEFAULT_REGISTRY)
    out: list[dict[str, Any]] = []
    prefix = f"{show_id}/"
    for key, entry in data["episodes"].items():
        if key.startswith(prefix) and isinstance(entry, dict):
            out.append(entry)
    return out


def is_registered(
    show_id: str,
    episode_id: str,
    *,
    registry_path: Path | None = None,
) -> bool:
    return get_local(show_id, episode_id, registry_path=registry_path) is not None
