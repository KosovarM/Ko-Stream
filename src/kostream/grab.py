"""Grab URL — resolve remote stream URLs for stream-only (demo.mp4) episodes.

Resolve order: manual override → cache → external command → optional demo samples.

Set ``KOSTREAM_GRAB_CMD`` to an **absolute** executable path (optional args) that
receives JSON on stdin and prints a direct media URL (or ``{"url":"..."}``) on
stdout. Ko-Stream does not ship site scrapers; you bring your own resolver.
The command is run as an argv list (never ``shell=True``).
"""

from __future__ import annotations

import ipaddress
import json
import os
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from kostream.jsonio import atomic_write_json
from kostream.models import Episode, Show

DEFAULT_GRAB_DIR = Path(__file__).resolve().parents[2] / "data" / "grab"
DEFAULT_CACHE_TTL = 2 * 60 * 60
DEFAULT_RESOLVER_TIMEOUT = 90

# Creative Commons / public sample MP4s — only when KOSTREAM_GRAB_DEMO=1.
DEMO_STREAM_URLS = (
    "https://storage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
    "https://storage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4",
    "https://storage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4",
)

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
    }
)


@dataclass(frozen=True)
class GrabResult:
    url: str
    source: str  # "override" | "cache" | "external" | "demo"


class GrabResolveError(Exception):
    """External resolver failed or returned an invalid URL."""


def grab_enabled() -> bool:
    """KOSTREAM_GRAB defaults to on; set 0/false/off/no to disable."""
    raw = os.environ.get("KOSTREAM_GRAB", "1").strip().lower()
    return raw not in ("0", "false", "off", "no", "")


def grab_demo_enabled() -> bool:
    """Public sample MP4s as last resort. Default off — use resolver/overrides."""
    raw = os.environ.get("KOSTREAM_GRAB_DEMO", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def grab_cmd() -> str | None:
    """Return configured grab command string, or None when unset/disabled."""
    raw = os.environ.get("KOSTREAM_GRAB_CMD", "").strip()
    return raw or None


def cache_ttl_seconds() -> int:
    raw = os.environ.get("KOSTREAM_GRAB_CACHE_TTL", "").strip()
    if not raw:
        return DEFAULT_CACHE_TTL
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_CACHE_TTL


def grab_dir(base: Path | None = None) -> Path:
    if base is not None:
        return base
    env = os.environ.get("KOSTREAM_GRAB_DIR", "").strip()
    if env:
        return Path(env)
    return DEFAULT_GRAB_DIR


def overrides_path(base: Path | None = None) -> Path:
    return grab_dir(base) / "overrides.json"


def cache_path(base: Path | None = None) -> Path:
    return grab_dir(base) / "cache.json"


def resolve_stream_url(
    show: Show,
    episode: Episode,
    *,
    base: Path | None = None,
    force: bool = False,
) -> GrabResult | None:
    """Resolve a playable HTTP(S) URL (override → cache → external → demo)."""
    if not grab_enabled():
        return None
    if episode.filename != "demo.mp4":
        override = get_override(show.id, episode.id, base=base)
        if override:
            return GrabResult(url=override, source="override")
        return None

    key = _cache_key(show.id, episode.id)
    override = get_override(show.id, episode.id, base=base)
    if override:
        _write_cache_entry(key, override, source="override", base=base)
        return GrabResult(url=override, source="override")

    if not force:
        cached = _read_cache_entry(key, base=base)
        if cached:
            return GrabResult(url=cached["url"], source="cache")

    cmd = grab_cmd()
    if cmd:
        url = run_external_resolver(cmd, show, episode)
        _write_cache_entry(key, url, source="external", base=base)
        return GrabResult(url=url, source="external")

    if grab_demo_enabled():
        url = _demo_url_for(episode)
        _write_cache_entry(key, url, source="demo", base=base)
        return GrabResult(url=url, source="demo")

    return None


def parse_grab_cmd(cmd: str) -> list[str]:
    """Parse ``KOSTREAM_GRAB_CMD`` into an argv list with a safe absolute exe.

    Never uses a shell. The first token must be an absolute filesystem path to
    an existing executable (or ``.py`` / ``.exe`` / ``.bat`` / ``.cmd`` script).
    """
    raw = (cmd or "").strip()
    if not raw:
        raise GrabResolveError("KOSTREAM_GRAB_CMD is empty")
    # posix=True keeps quoted Windows paths working (``"C:\\Prog\\py.exe"``).
    argv = shlex.split(raw, posix=True)
    argv = [a.strip('"') for a in argv if a.strip('"')]
    if not argv:
        raise GrabResolveError("KOSTREAM_GRAB_CMD is empty")
    exe = Path(argv[0])
    if not exe.is_absolute():
        raise GrabResolveError(
            "KOSTREAM_GRAB_CMD must start with an absolute executable path "
            "(relative names and PATH lookups are disabled)"
        )
    if not exe.exists():
        raise GrabResolveError(f"Resolver not found: {exe}")
    if not exe.is_file():
        raise GrabResolveError(f"Resolver is not a file: {exe}")
    argv[0] = str(exe)
    return argv


def run_external_resolver(cmd: str, show: Show, episode: Episode) -> str:
    """Run ``KOSTREAM_GRAB_CMD``; stdin JSON in, URL or JSON out."""
    payload = {
        "show_id": show.id,
        "title": show.title,
        "mal_id": show.mal_id,
        "episode_id": episode.id,
        "season": episode.season,
        "number": episode.number,
        "episode_title": episode.title,
    }
    argv = parse_grab_cmd(cmd)

    try:
        completed = subprocess.run(
            argv,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=DEFAULT_RESOLVER_TIMEOUT,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise GrabResolveError(f"Resolver not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GrabResolveError("Resolver timed out") from exc

    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        raise GrabResolveError(err or f"Resolver exited with code {completed.returncode}")

    return _parse_resolver_stdout(completed.stdout)


def _parse_resolver_stdout(stdout: str) -> str:
    text = (stdout or "").strip()
    if not text:
        raise GrabResolveError("Resolver returned empty output")
    # Prefer last non-empty line (tools often log to stdout).
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    candidate = lines[-1]
    if candidate.startswith("{"):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise GrabResolveError("Resolver JSON was invalid") from exc
        url = data.get("url") if isinstance(data, dict) else None
        if not isinstance(url, str) or not url.strip():
            raise GrabResolveError("Resolver JSON missing url")
        return _validate_https_url(url)
    return _validate_https_url(candidate)


def get_override(show_id: str, episode_id: str, *, base: Path | None = None) -> str | None:
    data = _load_json(overrides_path(base), default={})
    entry = data.get(_cache_key(show_id, episode_id))
    if isinstance(entry, str) and entry.strip():
        return entry.strip()
    if isinstance(entry, dict):
        url = entry.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def set_override(
    show_id: str,
    episode_id: str,
    url: str,
    *,
    base: Path | None = None,
) -> str:
    """Store a manual stream URL override. Returns normalized URL."""
    cleaned = _validate_https_url(url)
    path = overrides_path(base)
    data = _load_json(path, default={})
    key = _cache_key(show_id, episode_id)
    data[key] = {"url": cleaned, "updated_at": int(time.time())}
    _save_json(path, data)
    _write_cache_entry(key, cleaned, source="override", base=base)
    return cleaned


def set_overrides_bulk(
    show_id: str,
    mapping: dict[str, str],
    *,
    base: Path | None = None,
) -> dict[str, str]:
    """Set many episode overrides for one show. Returns episode_id → url."""
    saved: dict[str, str] = {}
    for episode_id, url in mapping.items():
        saved[episode_id] = set_override(show_id, episode_id, url, base=base)
    return saved


def _demo_url_for(episode: Episode) -> str:
    idx = max(0, episode.number - 1) % len(DEMO_STREAM_URLS)
    return DEMO_STREAM_URLS[idx]


def _cache_key(show_id: str, episode_id: str) -> str:
    return f"{show_id}/{episode_id}"


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return True
    if ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return True
    # Carrier-grade NAT / documentation / benchmarking ranges.
    if isinstance(ip, ipaddress.IPv4Address):
        for net in (
            "100.64.0.0/10",
            "192.0.0.0/24",
            "192.0.2.0/24",
            "198.18.0.0/15",
            "198.51.100.0/24",
            "203.0.113.0/24",
            "240.0.0.0/4",
        ):
            if ip in ipaddress.ip_network(net):
                return True
    return False


def _is_blocked_host(hostname: str) -> bool:
    """True when hostname is loopback/private/link-local (or resolves to one)."""
    host = (hostname or "").strip().strip("[]").casefold()
    if not host or host in _BLOCKED_HOSTNAMES:
        return True
    if host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return _ip_is_blocked(ip)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        # Unresolved names are allowed at validation time; fetch will fail later.
        # Literal private IPs and localhost aliases are already rejected above.
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            if _ip_is_blocked(ipaddress.ip_address(addr)):
                return True
        except ValueError:
            return True
    return False


def _validate_https_url(url: str) -> str:
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise ValueError("URL must be an absolute http(s) address")
    host = parsed.hostname
    if not host or _is_blocked_host(host):
        raise ValueError("URL host is not allowed (private/loopback addresses blocked)")
    return cleaned


def _read_cache_entry(key: str, *, base: Path | None = None) -> dict[str, Any] | None:
    data = _load_json(cache_path(base), default={})
    entry = data.get(key)
    if not isinstance(entry, dict):
        return None
    url = entry.get("url")
    expires = entry.get("expires_at", 0)
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        if float(expires) < time.time():
            return None
    except (TypeError, ValueError):
        return None
    return entry


def _write_cache_entry(
    key: str,
    url: str,
    *,
    source: str,
    base: Path | None = None,
) -> None:
    path = cache_path(base)
    data = _load_json(path, default={})
    data[key] = {
        "url": url,
        "source": source,
        "expires_at": int(time.time()) + cache_ttl_seconds(),
    }
    _save_json(path, data)


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.is_file():
        return default if not isinstance(default, dict) else dict(default)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if not isinstance(default, dict) else dict(default)
    if isinstance(default, dict) and not isinstance(raw, dict):
        return dict(default)
    return raw


def _save_json(path: Path, data: Any) -> None:
    atomic_write_json(path, data)
