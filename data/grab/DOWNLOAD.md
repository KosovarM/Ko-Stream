# Download missing episodes

UI: show page → **Download missing (N)**.

Ko-Stream prepares the show folder and passes missing episodes to an **external**
command. It does **not** ship anime site scrapers or vendor animdl.

## Configure

```powershell
$env:KOSTREAM_DOWNLOAD_CMD = "python C:\Users\Kosov\.cursor\Repositories\CodeProject2\scripts\download_missing.example.py"
ko-stream serve
```

## Contract (stdin JSON)

```json
{
  "show_id": "mal-61316",
  "title": "…",
  "mal_id": 61316,
  "folder": "Re Zero Season 4",
  "folder_path": "C:\\…\\media\\shows\\Re Zero Season 4",
  "episodes": [
    {
      "episode_id": "mal-61316-s04e03",
      "season": 4,
      "number": 3,
      "title": "Episode 3",
      "expected_filename": "S04E03.mp4",
      "target_path": "C:\\…\\S04E03.mp4"
    }
  ]
}
```

- Exit **0** on success.
- Last stdout line may be JSON: `{"completed":2,"message":"…"}`.

## Example script

`scripts/download_missing.example.py` only downloads episodes that already have a
**Grab override URL**. Replace it when you have your own URL source.

## APIs

- `POST /api/show/<id>/download-missing`
- `GET /api/show/<id>/download-missing/status`
