---
name: kostream-media
description: >-
  Organize and maintain the Ko-Stream local media library: discover files in
  Downloads Anime/Manga, import into media/shows and media/manga with correct
  naming, skip duplicates, update catalog folder links, and report results.
  Use when importing episodes/chapters, syncing the media base, fixing broken
  catalog folders, or maintaining anime/manga library files.
disable-model-invocation: true
---

# Ko-Stream Media Base

Maintain the user's **own legal local library** files. Organize, rename, copy, and link catalog entries. Do **not** help obtain pirated media or scrape illegal sources.

## Paths

| Role | Path |
|------|------|
| Anime library | `media/shows/<Show Folder>/` |
| Manga library | `media/manga/<Title Folder>/` |
| Anime downloads | `C:\Users\Kosov\Downloads\Anime` |
| Manga downloads | `C:\Users\Kosov\Downloads\Manga` |
| Anime catalog | `data/catalog/selected.json` (`folder` field) |
| Manga catalog | `data/manga/selected.json` (`folder` field) |

Repo root: workspace / CodeProject2.

## Naming

**Anime episodes** (preferred): `SxxExx.ext` — e.g. `S01E01.mp4`. Also accepted by scanner: `s1e1`, `1x01`. Prefer `.mp4` / `.webm` over `.mkv` for browser playback.

**Show folders**: one folder per catalog entry (season/OVA often separate folders, e.g. `Re Zero Season 1`, `Re Zero Memory Snow`). Match existing `folder` values when linking.

**Manga chapters**: under title folder as `Chapter NN.cbz` (or `Chapter NN.N.cbz`) or chapter image folders. Scanner also accepts loose `.cbz` at manga root (one title each).

Code refs: `src/kostream/local_media.py` (`expected_episode_filename`), `src/kostream/library.py` (`EPISODE_PATTERN`), `src/kostream/manga.py` (scan), `data/catalog/README.md`.

## Workflow

Copy this checklist and track it:

```
Media base:
- [ ] Confirm scope (anime / manga / both; which titles)
- [ ] Discover new files in Downloads
- [ ] Map to target media folders + filenames
- [ ] Import (copy); skip duplicates
- [ ] Update catalog `folder` links if needed
- [ ] Optional verify (scan / broken links)
- [ ] Report imported / skipped / linked / issues
```

### 1. Discover

List new items under Downloads Anime and/or Manga. Group by title/season. Ignore incomplete downloads (`.part`, `.crdownload`, zero-byte).

### 2. Map targets

- Match Downloads folder names to existing `media/shows/*` or `media/manga/*` folders (fuzzy title match OK; prefer exact catalog `folder`).
- Parse episode/chapter numbers from source names; target anime files must become `SxxExx.ext`.
- If no target folder exists: create under `media/shows/` or `media/manga/` using a clean display name (spaces OK; no `<>:"/\|?*`).
- There is **no** bulk anime import CLI (`ko-stream` is mainly `serve`). Import = filesystem copy/rename + catalog `folder` updates. Manga has richer scan/catalog helpers in `src/kostream/manga*.py`.

### 3. Import (skip duplicates)

For each candidate file:

1. Compute destination path.
2. **Skip** if destination exists with the **same size** (byte length). Treat same-size as already present.
3. If destination exists with **different size**, do not overwrite — report as conflict and ask or leave for user.
4. Otherwise **copy** (prefer copy over move so Downloads remain until user cleans up), then verify size.

Do not invent new app features or CLIs unless the user asks.

### 4. Catalog links

**Anime** (`data/catalog/selected.json`): set `"folder": "<exact media/shows subfolder name>"` on the matching entry (often `mal-*`). Enable if the user wants it on the home page. New titles: add an entry (`source` `local` or `mal` with ids) — do not invent fake MAL ids; omit or ask.

**Manga** (`data/manga/selected.json`): same idea with `"folder"` under `media/manga/`. Prefer matching existing MAL entries via title/folder.

Catalog JSON files are typically **gitignored** (personal library state). Edit locally; do not force-commit them.

UI alternative: Catalog page can attach folders — agent may still edit JSON when faster.

### 5. Optional verify

When asked or after large imports:

- Count files per show/title folder vs expected episodes/chapters.
- Flag catalog entries whose `folder` is missing or empty on disk.
- Flag empty media folders.
- Spot-check that `ko-stream` / library scan would see files (naming must match `EPISODE_PATTERN` / manga chapter rules).

## Report format

Always end with a short report:

```markdown
## Media import report

### Imported
- …

### Skipped (already present)
- …

### Conflicts / needs decision
- …

### Catalog updates
- …

### Notes
- …
```

## Hard rules

- Legal/local organizing only — no piracy workflow guidance.
- **Never commit** media blobs (`media/` is gitignored). Do not `git add` large video/cbz files.
- **Do not commit** unless the user explicitly asks. Catalog/data edits are local; still no commit unless asked.
- Do not push or invent unrelated product features.
- Prefer existing folder names and catalog entries over renaming the whole library.

## Optional: Automations

A Cursor **Automation** (scheduled Downloads → import) is optional and separate. Prefer this Skill for on-demand maintenance. Create an Automation only if the user explicitly asks for scheduled/triggered runs.

## Invoke

- `@kostream-media` in chat, or ask to import/maintain the media library / media base.
