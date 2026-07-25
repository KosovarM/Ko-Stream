from __future__ import annotations

import argparse
import sys

from kostream.app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ko-Stream — local streaming UI")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start web server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=5001)

    args = parser.parse_args(argv)
    if args.command == "serve":
        create_app().run(host=args.host, port=args.port, debug=False)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
