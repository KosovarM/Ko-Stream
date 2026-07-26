#!/usr/bin/env python3
"""Example Ko-Stream missing-episode downloader.

Wire with:
  $env:KOSTREAM_DOWNLOAD_CMD = "python path\\to\\scripts\\download_missing.example.py"

stdin JSON: show metadata + list of missing episodes with target_path.
stdout: optional JSON summary on the last line.

This example only downloads episodes that already have a Grab override URL
(data/grab/overrides.json). It does not scrape sites. Replace the body when
you have your own URL source / downloader.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

# Default grab overrides next to the Ko-Stream repo when run from scripts/
REPO_ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = REPO_ROOT / "data" / "grab" / "overrides.json"


def load_overrides() -> dict:
    if not OVERRIDES.is_file():
        return {}
    try:
        data = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def override_url(show_id: str, episode_id: str, data: dict) -> str | None:
    key = f"{show_id}/{episode_id}"
    entry = data.get(key)
    if isinstance(entry, str) and entry.strip():
        return entry.strip()
    if isinstance(entry, dict):
        url = entry.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Ko-Stream-download/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        print("invalid stdin JSON", file=sys.stderr)
        return 1

    show_id = payload.get("show_id") or ""
    episodes = payload.get("episodes") or []
    overrides = load_overrides()
    completed = 0
    skipped = 0

    for ep in episodes:
        episode_id = ep.get("episode_id") or ""
        target = Path(ep.get("target_path") or "")
        if not target.name:
            skipped += 1
            continue
        url = override_url(show_id, episode_id, overrides)
        if not url:
            print(f"skip {episode_id}: no override URL", file=sys.stderr)
            skipped += 1
            continue
        try:
            download(url, target)
            completed += 1
            print(f"saved {target.name}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"fail {episode_id}: {exc}", file=sys.stderr)
            skipped += 1

    print(
        json.dumps(
            {
                "ok": True,
                "completed": completed,
                "skipped": skipped,
                "message": f"Downloaded {completed}, skipped {skipped}.",
            }
        )
    )
    return 0 if completed or skipped == len(episodes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
