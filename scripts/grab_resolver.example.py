#!/usr/bin/env python3
"""Example Grab resolver for Ko-Stream.

Wire with (absolute paths only):
  $py = (Resolve-Path .\.venv\Scripts\python.exe).Path
  $script = (Resolve-Path .\scripts\grab_resolver.example.py).Path
  $env:KOSTREAM_GRAB_CMD = "$py $script"

Reads JSON from stdin, prints a direct media URL on stdout.
Replace the body with your own legal URL source — do not commit scrapers
against unauthorized sites into this repo.
"""

from __future__ import annotations

import json
import sys

# Public sample used only to verify the hook works end-to-end.
_SAMPLES = (
    "https://storage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
    "https://storage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4",
    "https://storage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4",
)


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        print("invalid stdin JSON", file=sys.stderr)
        return 1

    number = int(data.get("number") or 1)
    url = _SAMPLES[(number - 1) % len(_SAMPLES)]
    # Prefer plain URL (also accepted: print(json.dumps({"url": url})))
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
