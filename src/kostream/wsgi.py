"""WSGI entrypoint for production (gunicorn behind Caddy).

Bind only to loopback — never expose this port on the WAN:

    gunicorn -b 127.0.0.1:5001 -w 2 'kostream.wsgi:app'

See ``docs/PUBLIC_HTTPS.md`` and ``deploy/``.
"""

from __future__ import annotations

from kostream.app import create_app

app = create_app()
