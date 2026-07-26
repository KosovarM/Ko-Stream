# Ko-Stream

Private **local library** UI for series you own — play files from disk, `.strm` pointers, Jellyfin, or Grab test streams. Metadata and posters via AniList / MyAnimeList.

## Disclaimer

Stream **only** media you own or may legally play. Grab uses public sample MP4s or URLs you paste; it does not scrape pirate anime sites. Intended for personal home use.

## Quick start

```powershell
cd C:\Users\Kosov\.cursor\Repositories\CodeProject2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ko-stream serve
```

Open **http://127.0.0.1:5001**

## Catalog (fast local testing)

Only **enabled** entries in `data/catalog/selected.json` load on the home page.

Open **http://127.0.0.1:5001/catalog** to:

- Enable/disable shows
- Add local folders from `media/shows/`
- Search **AniList** for titles, descriptions, and cover art

See `data/catalog/README.md`.

## MyAnimeList import

Connect your MAL account to auto-fill the catalog from your animelist:

```powershell
$env:MAL_CLIENT_ID = "your-client-id"
$env:MAL_CLIENT_SECRET = "your-client-secret"
ko-stream serve
```

Then open **Catalog → Connect MyAnimeList**. Full setup: `data/mal/README.md`.

## Add shows

**Local video:**

```
media/shows/My Series Name/S01E01.mp4
```

**URL pointer (no video file stored):**

```
media/shows/My Series Name/S01E01.strm
```

File content: one direct URL to an MP4/WebM stream.

**Jellyfin backend:**

```powershell
$env:JELLYFIN_URL = "http://localhost:8096"
$env:JELLYFIN_API_KEY = "your-key"
ko-stream serve
```

See **[docs/STREAMING_SOURCES.md](docs/STREAMING_SOURCES.md)** for Jellyfin, Plex, `.strm`, Grab test streams, and legal source options.

### Grab on-demand streams (no full download)

Stream-only episodes resolve via Grab (`KOSTREAM_GRAB=1`): paste a URL, or set `KOSTREAM_GRAB_CMD` to your resolver. Optional samples: `KOSTREAM_GRAB_DEMO=1`. See `data/grab/README.md`.

### Download missing episodes

Show page → **Download missing**. Set `KOSTREAM_DOWNLOAD_CMD` to a script that receives JSON (missing eps + target paths). Example: `scripts/download_missing.example.py`. Details: `data/grab/DOWNLOAD.md`.

## VS Code

Open workspace: `Ko-Stream.code-workspace`

## GitHub

https://github.com/KosovarM/Ko-Stream

## Tests

```powershell
pytest
```
