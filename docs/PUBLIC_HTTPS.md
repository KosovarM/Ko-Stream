# Public HTTPS (no Tailscale / no extra client apps)

Expose Ko-Stream on the internet with **TLS termination on the Pi** and **no open app port**.

```text
Phone (LTE) --HTTPS:443--> Fritzbox --forward--> Caddy --HTTP--> 127.0.0.1:5001 gunicorn
```

**Never** port-forward `5001`. Only **80** and **443** → the Pi.

Live host inventory: Obsidian `70 Documentation/How-to/Raspberry Pi — Host inventory.md`  
LAN-only setup: [`PI_LAN_PREP.md`](PI_LAN_PREP.md)

---

## Prerequisites

1. A **hostname** that resolves to your public IP (own domain, DuckDNS, or MyFRITZ!).
2. Raspberry Pi already running Ko-Stream on LAN (media mounts + accounts).
3. Fritzbox admin access.

Without a hostname, Let's Encrypt cannot issue a normal trusted certificate.

---

## 1. Install production stack on the Pi

```bash
cd ~/Ko-Stream   # or your clone path
source .venv/bin/activate
pip install -r requirements.lock
pip install -e ".[prod]"     # gunicorn
# Optional LAN extras are unrelated to WAN:
# pip install -e ".[lan]"
```

Install [Caddy](https://caddyserver.com/docs/install#debian-ubuntu-raspbian) (apt repo recommended on Raspberry Pi OS).

---

## 2. Environment (`/etc/kostream.env`)

```bash
sudo cp deploy/kostream.env.example /etc/kostream.env
sudo chmod 600 /etc/kostream.env
sudo nano /etc/kostream.env
```

Required for public HTTPS:

| Variable | Value |
|----------|--------|
| `KOSTREAM_SESSION_SECURE` | `1` |
| `KOSTREAM_TRUST_PROXY` | `1` |
| `KOSTREAM_SECRET_KEY` | long random string |
| `MAL_REDIRECT_URI` | `https://YOUR.HOST/auth/mal/callback` |
| Media roots | PiVault paths (see host inventory) |

Also set `MAL_CLIENT_ID` / `MAL_CLIENT_SECRET`. Register the **exact** redirect URI in [MAL apiconfig](https://myanimelist.net/apiconfig).

---

## 3. gunicorn (systemd)

```bash
sudo cp deploy/kostream.service /etc/systemd/system/kostream.service
# Edit User/WorkingDirectory/ExecStart if your paths differ
sudo systemctl daemon-reload
sudo systemctl enable --now kostream.service
sudo systemctl status kostream.service
curl -sI http://127.0.0.1:5001/login | head
```

App must answer on **loopback only**.

---

## 4. Caddy

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
# Change kostream.example.com → your hostname
sudo nano /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
```

Caddy obtains certificates automatically when DNS + ports 80/443 are correct.

### Optional login rate-limit

Standard Caddy builds may not include `rate_limit`. Options:

- Install a build with [caddy-ratelimit](https://github.com/mholt/caddy-ratelimit), or
- Use fail2ban on auth failures later.

Ko-Stream already has a permanent **3-strike lockout** per username after failed logins.

---

## 5. Fritzbox port forwarding

| External | Internal | Target |
|----------|----------|--------|
| TCP 443 | TCP 443 | Pi `192.168.178.10` |
| TCP 80 | TCP 80 | Pi `192.168.178.10` (ACME + HTTP→HTTPS) |

Do **not** forward:

- `5001` (gunicorn)
- `22` (SSH) to the WAN

Pi firewall: allow 80/443 from LAN/WAN as needed; keep SSH LAN-only if possible.

---

## 6. Verify from outside (mobile LTE, Wi‑Fi off)

1. Open `https://YOUR.HOST/` — valid certificate, no browser warning.
2. Log in; browse Catalog; play an episode; open manga reader.
3. From another network, confirm `http://YOUR.PUBLIC.IP:5001` **fails** (filtered/closed).
4. MAL Connect uses `https://YOUR.HOST/auth/mal/callback`.

---

## 7. Backups

```bash
cd ~/Ko-Stream && source .venv/bin/activate
python scripts/backup_data.py
```

Schedule via cron (example weekly):

```cron
0 3 * * 0 cd /home/kosovar/Ko-Stream && .venv/bin/python scripts/backup_data.py
```

---

## Risk checklist (minimized)

| Risk | Mitigation in this setup |
|------|---------------------------|
| Cleartext sessions | HTTPS + `KOSTREAM_SESSION_SECURE=1` + HSTS |
| Dev server on WAN | gunicorn on `127.0.0.1` only |
| Brute force | App lockout + strong passwords (+ optional Caddy/fail2ban) |
| Large attack surface | Only 80/443 forwarded |
| Broken cookies/redirects | `KOSTREAM_TRUST_PROXY=1` + ProxyFix |
| Leaked URL | Share only with family; every visitor hits login |

Still deferred: MAL token encryption at rest, Cloudflare, heavy DDoS protection.

---

## Local / LAN vs production

| Mode | Command | Bind |
|------|---------|------|
| Dev / LAN | `ko-stream serve --lan` | `0.0.0.0:5001` Werkzeug — **not for WAN** |
| Production | gunicorn via `kostream.service` | `127.0.0.1:5001` behind Caddy |
