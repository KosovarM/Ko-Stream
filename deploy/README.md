# Deploy templates (public HTTPS)

| File | Purpose |
|------|---------|
| [`Caddyfile`](Caddyfile) | TLS termination → `127.0.0.1:5001` |
| [`kostream.service`](kostream.service) | systemd unit for gunicorn |
| [`kostream.env.example`](kostream.env.example) | `/etc/kostream.env` skeleton |

Full guide: [`docs/PUBLIC_HTTPS.md`](../docs/PUBLIC_HTTPS.md).
