# Grab URL (on-demand streams)

For **stream only** episodes (`demo.mp4`), Ko-Stream resolves a remote HTTPS URL and proxies it — no full download into `media/shows/`.

## Resolve order

1. Manual override (`overrides.json` or watch-page paste)
2. Cache (`cache.json`, TTL via `KOSTREAM_GRAB_CACHE_TTL`, default 2h)
3. External command (`KOSTREAM_GRAB_CMD`)
4. Optional public demo MP4s (`KOSTREAM_GRAB_DEMO=1`)

## External resolver (recommended)

Ko-Stream does **not** ship anime site scrapers. Point Grab at your own script/CLI:

```powershell
$env:KOSTREAM_GRAB = "1"
$env:KOSTREAM_GRAB_CMD = "python C:\Users\Kosov\.cursor\Repositories\CodeProject2\scripts\grab_resolver.example.py"
ko-stream serve
```

**Contract**

- **stdin:** JSON object, e.g.
  ```json
  {
    "show_id": "mal-61316",
    "title": "Re:Zero … 4th Season",
    "mal_id": 61316,
    "episode_id": "mal-61316-s01e03",
    "season": 1,
    "number": 3,
    "episode_title": "Episode 3"
  }
  ```
- **stdout:** one direct media URL, or `{"url":"https://…"}` (last non-empty line wins)
- **exit 0** on success; non-zero + stderr message on failure

Example (sample files only): `scripts/grab_resolver.example.py`

On the watch page: **Resolve stream** / **Refresh stream URL**.

## Manual / bulk overrides

Per episode on the watch page, or:

```http
POST /api/grab/overrides/bulk
{"show_id":"mal-61316","urls":{"mal-61316-s01e03":"https://…/ep3.mp4"}}
```

## Files

| File | Purpose |
|------|---------|
| `overrides.json` | Manual per-episode URLs |
| `cache.json` | Short-lived resolved URLs (gitignored) |

## Env

| Variable | Meaning |
|----------|---------|
| `KOSTREAM_GRAB` | `1` (default) on / `0` off |
| `KOSTREAM_GRAB_CMD` | External resolver command |
| `KOSTREAM_GRAB_DEMO` | `1` = fall back to public sample MP4s |
| `KOSTREAM_GRAB_CACHE_TTL` | Cache seconds (default 7200) |
| `KOSTREAM_GRAB_DIR` | Override data folder |

## Legal

Only resolve/stream URLs you may use. Keep third-party scrapers out of this repo if you write them for personal experiments.
