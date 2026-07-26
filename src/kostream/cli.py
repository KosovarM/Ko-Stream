from __future__ import annotations

import argparse
import atexit
import socket
import sys
from typing import Any

from kostream.app import create_app


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1")


def _lan_ipv4_addresses() -> list[str]:
    """Best-effort list of non-loopback IPv4 addresses on this machine."""
    found: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                found.add(ip)
    except OSError:
        pass
    try:
        # UDP connect does not send packets; reveals the preferred outbound IP.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if not ip.startswith("127."):
                found.add(ip)
    except OSError:
        pass
    return sorted(found)


def _sanitize_mdns_name(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "").strip())
    cleaned = cleaned.strip("-_.").lower() or "kostream"
    return cleaned[:63]


def _start_mdns(name: str, port: int, ips: list[str]) -> Any | None:
    """Advertise ``name.local`` via mDNS so phones can open http://name.local:port."""
    if not ips:
        return None
    try:
        from zeroconf import ServiceInfo, Zeroconf
    except ImportError:
        print("  mDNS skipped (optional): pip install 'ko-stream[lan]'  for http://%s.local:%s" % (name, port))
        return None

    zc = Zeroconf()
    addresses = [socket.inet_aton(ip) for ip in ips]
    info = ServiceInfo(
        type_="_http._tcp.local.",
        name="Ko-Stream._http._tcp.local.",
        addresses=addresses,
        port=port,
        properties={"path": "/", "app": "ko-stream"},
        server=f"{name}.local.",
    )
    try:
        zc.register_service(info)
    except Exception as exc:  # noqa: BLE001 — best-effort LAN helper
        print(f"  mDNS register failed: {exc}")
        try:
            zc.close()
        except Exception:  # noqa: BLE001
            pass
        return None

    def _shutdown() -> None:
        try:
            zc.unregister_service(info)
            zc.close()
        except Exception:  # noqa: BLE001
            pass

    atexit.register(_shutdown)
    return zc


def _print_listen_banner(host: str, port: int, *, mdns_name: str | None = None) -> None:
    print(f"Ko-Stream listening on http://{host}:{port}")
    if _is_loopback(host):
        print("  Local only. For phones/PCs on your Wi-Fi use:  ko-stream serve --lan")
        return

    print()
    print("  Heimnetz / LAN - open on other devices:")
    for ip in _lan_ipv4_addresses():
        print(f"    http://{ip}:{port}")
    if mdns_name:
        print(f"    http://{mdns_name}.local:{port}   (mDNS, if supported by the device)")
    print(f"    http://{mdns_name or 'kostream'}.fritz.box:{port}   (Fritzbox: rename this PC to that hostname)")
    print()
    print("  Notes:")
    print("  - PC and phone must be on the same Wi-Fi/LAN (not guest/VPN isolation).")
    print("  - Allow TCP port %s in Windows Firewall if the phone cannot connect." % port)
    print("  - Names like KoStream.net need real DNS (Fritzbox/Pi-hole); they are not magic aliases.")
    print("  - No login yet - only use on a trusted home network.")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ko-Stream — local streaming UI")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start web server")
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1). Use 0.0.0.0 for all interfaces.",
    )
    serve.add_argument("--port", type=int, default=5001)
    serve.add_argument(
        "--lan",
        action="store_true",
        help="Bind 0.0.0.0 so other devices on your home network can connect.",
    )
    serve.add_argument(
        "--name",
        default="kostream",
        help="LAN hostname label for mDNS / Fritzbox tip (default: kostream → kostream.local).",
    )

    args = parser.parse_args(argv)
    if args.command == "serve":
        host = "0.0.0.0" if args.lan else args.host
        port = args.port
        mdns_name = _sanitize_mdns_name(args.name) if (args.lan or not _is_loopback(host)) else None
        _print_listen_banner(host, port, mdns_name=mdns_name)
        if mdns_name:
            _start_mdns(mdns_name, port, _lan_ipv4_addresses())
        # threaded=True: phone + PC can stream / browse at the same time
        create_app().run(host=host, port=port, debug=False, threaded=True)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
