# Ko-Stream

Local series streaming with an **[Aniwatch](https://aniwatch.co.at/)-inspired** UI — for **your own files** on disk.

## Disclaimer

Stream **only** media you own or may legally play locally.

## Quick start

```powershell
cd C:\Users\Kosov\.cursor\Repositories\Ko-Stream
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ko-stream serve
```

Open **http://127.0.0.1:5001**

## Add shows

```
media/shows/My Series Name/S01E01.mp4
```

## VS Code

Open workspace: `Ko-Stream.code-workspace`

## GitHub

https://github.com/KosovarM/Ko-Stream

## Tests

```powershell
pytest
```
