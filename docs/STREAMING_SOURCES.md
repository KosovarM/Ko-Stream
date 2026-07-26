# Ko-Stream — Streaming sources & web streamers

Ko-Stream is designed for **on-demand playback without duplicating video files**. Metadata lives in Ko-Stream; bytes are streamed when you press play.

## Supported source types

| Source | Storage on disk | How it works |
|--------|-----------------|--------------|
| **Local files** | Your video files in `media/shows/` | HTTP Range requests — seek works, no copy |
| **`.strm` pointers** | Tiny text file (~100 bytes) with a URL | Ko-Stream proxies the remote URL on play |
| **Jellyfin** | None in Ko-Stream | API metadata + proxy stream from your server |
| **Grab** | Override JSON + short cache | Resolves HTTPS URL for stream-only episodes, then proxies |

## 1. Local files (simplest)

```
media/shows/One Piece/S01E01.mp4
media/shows/One Piece/S01E02.mkv
```

Naming: `S01E01`, `1x01`, or any filename (defaults to S1E1).

Ko-Stream serves files via `/media/<show>/<file>` with **206 Partial Content** for seeking.

## 2. `.strm` files (no video copy)

Same layout as Plex/Jellyfin `.strm` — one URL per line:

```
media/shows/My Series/S01E01.strm
```

Contents of `S01E01.strm`:

```
https://your-server.example/anime/S01E01.mp4
```

Only the pointer is stored locally. Playback goes through `/stream/strm/...` (proxy with Range support).

**You are responsible** for having rights to stream that URL.

## 3. Jellyfin (recommended web streamer)

Run [Jellyfin](https://jellyfin.org/) on a NAS, PC, or VPS. Point it at your library (local paths, `.strm`, network shares). Ko-Stream reads the catalog and proxies streams.

```powershell
$env:JELLYFIN_URL = "http://192.168.1.10:8096"
$env:JELLYFIN_API_KEY = "your-api-key"
ko-stream serve
```

Create an API key: Jellyfin → Dashboard → Advanced → API Keys.

Shows appear as `jf-<id>` in the UI. No videos are copied into Ko-Stream.

## 4. Grab URL (on-demand / stream only)

For **stream only** episodes (`demo.mp4`) without downloading into `media/shows/`:

1. Manual HTTPS override (watch page or `data/grab/overrides.json`)
2. Optional **external resolver** via `KOSTREAM_GRAB_CMD` (stdin JSON → stdout URL)
3. Optional public demo MP4s if `KOSTREAM_GRAB_DEMO=1`

```powershell
$env:KOSTREAM_GRAB = "1"
$env:KOSTREAM_GRAB_CMD = "python path\to\your_resolver.py"
ko-stream serve
```

See `data/grab/README.md` and `scripts/grab_resolver.example.py`.

Playback: `/stream/grab/...` (Range proxy). Ko-Stream does **not** embed anime aggregator scrapers; wire your own legal URL source to the hook.

## Web streamer options (comparison)

| Software | Best for | On-demand | Notes |
|----------|----------|-----------|-------|
| **[Jellyfin](https://jellyfin.org/)** | Self-hosted, free, anime-friendly | Yes | HLS/transcode on the fly; `.strm` plugin; **integrated in Ko-Stream** |
| **[Plex](https://www.plex.tv/)** | Easy UI, clients everywhere | Yes | Pass required for some transcodes; no direct Ko-Stream integration yet |
| **[Emby](https://emby.media/)** | Similar to Jellyfin | Yes | Paid features for some clients |
| **Ko-Stream alone** | Lightweight local library UI | Yes | Local + `.strm` + Jellyfin + Grab proxy |

### When to use which

- **Few local files, one machine** → Ko-Stream local mode only
- **Large library, multiple devices** → Jellyfin backend + Ko-Stream as a simple front-end
- **Remote files without downloading** → `.strm`, Grab overrides, or `KOSTREAM_GRAB_CMD`
- **MKV in browser** → Jellyfin transcodes to HLS; Ko-Stream local mode serves MKV if the browser supports it

## Legal sources (metadata / own media / samples)

Stream only media you own or may legally play. For a typical setup:

| Service | Type | Ko-Stream |
|---------|------|-----------|
| [Crunchyroll](https://www.crunchyroll.com/) | Subscription streaming | Use their apps; no rip integration |
| [HIDIVE](https://www.hidive.com/) | Subscription | Same |
| Own Blu-rays / digital purchases | Local files | Copy to `media/shows/` or import into Jellyfin |
| [Internet Archive](https://archive.org/) | Public domain / licensed uploads | `.strm`, Grab override, or local download where permitted |
| Google / Blender sample MP4s | CC / public demos | `KOSTREAM_GRAB_DEMO=1` |

## Environment variables

| Variable | Description |
|----------|-------------|
| `JELLYFIN_URL` | Base URL, e.g. `http://localhost:8096` |
| `JELLYFIN_API_KEY` | Jellyfin API key |
| `KOSTREAM_GRAB` | `1` (default) enable Grab; `0` to disable |
| `KOSTREAM_GRAB_CMD` | External resolver command (stdin JSON → stdout URL) |
| `KOSTREAM_GRAB_DEMO` | `1` enable public sample MP4 fallback |
| `KOSTREAM_GRAB_CACHE_TTL` | Cache lifetime in seconds (default 7200) |
| `KOSTREAM_GRAB_DIR` | Optional path to grab data folder |

## Architecture

```
Browser → Ko-Stream (Flask UI)
              ├─ /media/...        → local file (Range)
              ├─ /stream/strm/...  → proxy remote URL (Range)
              ├─ /stream/jellyfin/ → proxy Jellyfin (Range)
              └─ /stream/grab/...  → override/cache/external/demo → proxy (Range)
```

No full-file caching unless the browser’s own media buffer.
