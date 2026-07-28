# Raspberry Pi LAN prep (not internet-facing yet)

Use this before first deploy on the Pi. **No port-forward / no public URL.**

**Live host facts (SSH, IP, mounts):** Obsidian  
`70 Documentation/How-to/Raspberry Pi — Host inventory.md`

| Field | Value |
|-------|--------|
| SSH | `ssh kosovar@192.168.178.10` |
| USB mount | `/media/kosovar/PiVault` |
| Anime | `/media/kosovar/PiVault/Media/Ko-Stream/anime` |
| Manga | `/media/kosovar/PiVault/Media/Ko-Stream/manga` |
| Thumbnails | `/media/kosovar/PiVault/Media/Ko-Stream/Thumbnail` |

## Answers (project vs Pi)

| Topic | Where |
|-------|--------|
| `requirements.lock` | **In the repo already.** On the Pi: `pip install -r requirements.lock` (+ `pip install -e ".[lan]"` if you want mDNS). |
| Secrets (`MAL_*`, `KOSTREAM_SECRET_KEY`) | **You set on the Pi** (SSH / systemd `EnvironmentFile`). Template: [`.env.example`](../.env.example). Do not commit real values. |
| Media paths | **Canonical Pi paths below** (USB `PiVault`). Windows `D:\Media\…` defaults do **not** apply on the Pi. |

## Media env (Pi)

```bash
export KOSTREAM_ANIME_ROOT="/media/kosovar/PiVault/Media/Ko-Stream/anime"
export KOSTREAM_MANGA_ROOT="/media/kosovar/PiVault/Media/Ko-Stream/manga"
```

Verify:

```bash
ls /media/kosovar/PiVault/Media/Ko-Stream/anime | head
ls /media/kosovar/PiVault/Media/Ko-Stream/manga | head
```

**Caveat:** Mount under `/media/kosovar/…` is typically automount — after reboot, confirm it is up (or add fstab/UUID later). Disk is **exFAT**.

## Backup `data/` (before moving machine)

```bash
python scripts/backup_data.py
# → backups/kostream-data-*.zip
```

Copy the zip onto the Pi (media stays on the USB disk). Restore by unzipping into the repo `data/` on the Pi.

## First LAN run (Pi)

```bash
git clone https://github.com/KosovarM/Ko-Stream.git
cd Ko-Stream
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e ".[lan]"
export KOSTREAM_ANIME_ROOT="/media/kosovar/PiVault/Media/Ko-Stream/anime"
export KOSTREAM_MANGA_ROOT="/media/kosovar/PiVault/Media/Ko-Stream/manga"
# also: MAL_CLIENT_ID, MAL_CLIENT_SECRET, KOSTREAM_SECRET_KEY
ko-stream serve --lan --name kostream
```

Open from the LAN: `http://192.168.178.10:5001` (or mDNS / Fritzbox name once configured).

Fritzbox: do **not** open port 5001 to the internet. Clients stay on home Wi‑Fi/LAN only.

## Deferred until later (outside / hardening)

- TLS (Caddy) / Tailscale
- MAL token encryption on disk
- Restrictive `.strm` proxy allowlist (would block some remote setups)
- Replace Werkzeug with gunicorn behind a reverse proxy
- Persistent mount (fstab) if automount is flaky after reboot
