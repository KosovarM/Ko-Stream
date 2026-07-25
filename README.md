# CodeProject2 — LocalWatch

Local series streaming with an **[Aniwatch](https://aniwatch.co.at/)-inspired** dark UI — for **your own files** on disk.

## Disclaimer

Stream **only** media you own or may legally play locally. This is not an anime piracy site — it reads folders on your PC.

## Quick start

```powershell
cd C:\Users\Kosov\.cursor\Repositories\CodeProject2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
stream serve
```

Open **http://127.0.0.1:5001**

## Add shows

Put videos in:

```
media/shows/My Series Name/S01E01.mp4
```

See [media/shows/README.md](media/shows/README.md).

## VS Code

Open workspace: `CodeProject2.code-workspace`

## GitHub

https://github.com/KosovarM/CodeProject2

## Obsidian

Vault: `CodingProjekt1\CodingProjekt` → [[10 Project#Projekt 2]]

## UI features (Aniwatch-style)

- Dark purple theme, sticky header + search
- Spotlight carousel (#1–#10)
- Trending / Latest Episode rows
- Sidebar: Top Airing, Most Popular, Top 10
- Show detail + episode list
- HTML5 video player + watch progress

## Tests

```powershell
pytest
```
