# Catalog selection

Only **enabled** entries in `selected.json` are loaded on the home page.

## Why

- Faster startup during development/tests
- No full scan of the anime media root or Jellyfin on every request
- Pick exactly which anime appear in the UI

## Add a local folder

1. Put videos in `D:\Media\Ko-Stream\anime\My Anime\S01E01.mp4` (or `$env:KOSTREAM_ANIME_ROOT\…`)
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
| `local` | Scan `<anime-root>/<folder>/` |
| `demo` | Placeholder episode until files exist |
| `anilist` | Metadata/poster from AniList (may be metadata-only) |
| `jellyfin` | Pull from Jellyfin (`jellyfin_id` required) |
| `mal` | Imported from MyAnimeList list sync |
## Disable all scanning

Set `"enabled": false` on entries, or empty the `shows` array — falls back to demo catalog.
