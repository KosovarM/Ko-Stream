# Catalog selection

Only **enabled** entries in `selected.json` are loaded on the home page.

## Why

- Faster startup during development/tests
- No full scan of `media/shows/` or Jellyfin on every request
- Pick exactly which anime appear in the UI

## Add a local folder

1. Put videos in `media/shows/My Anime/S01E01.mp4`
2. Open **Catalog** in the UI → **Add to catalog** on the folder
3. Enable the checkbox

## Add metadata-only (AniList posters)

Search on the Catalog page → **Add**. Uses AniList for title, description, cover art.

Optional: add `anilist_id` manually:

```json
{
  "id": "frieren",
  "enabled": true,
  "source": "local",
  "folder": "Frieren",
  "anilist_id": 154587
}
```

## Sources

| `source` | Meaning |
|----------|---------|
| `local` | Scan `media/shows/<folder>/` |
| `demo` | Placeholder episode until files exist |
| `jellyfin` | Pull from Jellyfin (`jellyfin_id` required) |

## Disable all scanning

Set `"enabled": false` on entries, or empty the `shows` array — falls back to demo catalog.
