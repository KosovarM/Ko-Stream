# Ko-Stream



Private **local library** UI for series you own — play files from disk, `.strm` pointers, Jellyfin, or Grab test streams. Metadata and posters via AniList / MyAnimeList.



## Disclaimer



Stream **only** media you own or may legally play. Grab uses public sample MP4s or URLs you paste; it does not scrape pirate anime sites. Intended for personal home use.



## Quick start



```powershell

cd C:\Users\Kosov\.cursor\Repositories\CodeProject2

python -m venv .venv

.\.venv\Scripts\Activate.ps1

pip install -r requirements.lock

pip install -e ".[dev]"

ko-stream serve

```

Pinned dependency versions live in `requirements.lock` (regenerate with `pip-compile pyproject.toml -o requirements.lock` or `uv pip compile pyproject.toml -o requirements.lock` after changing bounds in `pyproject.toml`).



Open **http://127.0.0.1:5001**

### Heimnetz (Handy / andere PCs)

Same Wi‑Fi/LAN as this PC:

```powershell
pip install -e ".[lan]"
ko-stream serve --lan
```

Easy names (recommended):

| URL | How |
|-----|-----|
| `http://kostream.local:5001` | mDNS (needs `pip install -e ".[lan]"`; works on many phones) |
| `http://kostream.fritz.box:5001` | Fritzbox DNS — set this PC’s network name to **kostream** (see below) |
| `http://192.168.x.x:5001` | Always works as fallback (printed in the terminal) |

Custom label:

```powershell
ko-stream serve --lan --name kostream
# → http://kostream.local:5001
```

**Why not `KoStream.net`?**  
`.net` is a real public internet domain. Phones look it up on the public DNS, not in your living room — unless you own that domain and run local DNS (Pi-hole etc.). For home use, prefer **`.local`** or **`.fritz.box`**.

**Fritzbox → `http://kostream.fritz.box:5001`**

1. Fritzbox UI → Heimnetz → Netzwerk → this PC  
2. Set the device name to **kostream** (or change the Windows computer name to `kostream` and reconnect Wi‑Fi)  
3. On the phone open `http://kostream.fritz.box:5001`

If it does not load, allow the port in Windows Firewall (Admin PowerShell):

```powershell
New-NetFirewallRule -DisplayName "Ko-Stream" -Direction Inbound -Protocol TCP -LocalPort 5001 -Action Allow -Profile Private
```

**Security:** There is no login yet. Basic CSRF protection covers mutating POSTs (session token + `X-CSRF-Token` on fetch). Use only on a trusted home network (not public Wi‑Fi / not exposed to the internet). Optional secret: `KOSTREAM_SECRET_KEY` (otherwise a key is stored in `data/.flask_secret`). Disable CSRF for local scripts with `KOSTREAM_CSRF=0`.

## Media roots

Anime and manga files live **outside the git repo** (disk space):

| Kind | Default path | Env override |
|------|----------------|--------------|
| Anime | `D:\Media\Ko-Stream\anime` | `KOSTREAM_ANIME_ROOT` or `KOSTREAM_MEDIA_ROOT` |
| Manga | `D:\Media\Ko-Stream\manga` | `KOSTREAM_MANGA_ROOT` |

Repo `media/shows/` and `media/manga/` keep README stubs only. On a Pi / other host, set the env vars to your NAS or USB path.

## Catalog (fast local testing)



Only **enabled** entries in `data/catalog/selected.json` load on the home page.



Open **http://127.0.0.1:5001/catalog** to:



- Enable/disable shows

- Link local folders under the anime media root

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

**Sync** also pulls anime episode titles (Jikan/MAL) and, for local manga/manhwa with a MAL id, chapter titles from [MangaDex](https://mangadex.org/) (metadata only — no chapter images). Optional per-title override: set `mangadex_id` on a manga catalog entry in `data/manga/selected.json`.



## Add shows



**Local video:**



```

D:\Media\Ko-Stream\anime\My Series Name\S01E01.mp4

```

(or `$env:KOSTREAM_ANIME_ROOT\My Series Name\S01E01.mp4`)



**URL pointer (no video file stored):**



```

D:\Media\Ko-Stream\anime\My Series Name\S01E01.strm

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

### Local episode files

Show page → **Open folder**, then place files as `SxxExx.mp4` (e.g. `S04E03.mp4`), or use **Upload** next to an episode. Refresh the page after adding files.

### Manga

Place titles under `D:\Media\Ko-Stream\manga\` (or `$env:KOSTREAM_MANGA_ROOT`):

```
D:\Media\Ko-Stream\manga\My Manga\Chapter 01\001.jpg
D:\Media\Ko-Stream\manga\My Manga\vol2.cbz
D:\Media\Ko-Stream\manga\OneShot.cbz
```

Open **Manga** in the nav — click a cover (or a chapter) for the full-screen reader (←/→, Esc, RTL toggle).

## VS Code



Open workspace: `Ko-Stream.code-workspace`



## GitHub



https://github.com/KosovarM/Ko-Stream



## Tests



```powershell

pytest

```

