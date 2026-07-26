# Fetch explicit stream URL → local file

You supply a **direct** `.mp4` / `.m3u8` URL (no site scraping in Ko-Stream).

## ffmpeg download

```python
from kostream.stream_fetch import fetch_into_storage, fetch_stream_to_file

fetch_into_storage("https://…/ep.m3u8", "clip.mp4")  # → media_assets/clip.mp4
```

CLI:

```powershell
python -m kostream.stream_fetch "https://…/ep.m3u8" "clip.mp4"
```

Requires `ffmpeg` on `PATH`. Uses `-c copy` (remux, no re-encode).

## Library integration

Watch page (stream-only): paste URL → **Download to library**  
→ `POST /api/show/<id>/fetch-episode` `{ "episode_id", "url" }`  
→ writes `media/shows/<folder>/SxxExx.mp4` and updates `data/local_registry.json`.

Registry listing: `GET /api/show/<id>/local-registry`
