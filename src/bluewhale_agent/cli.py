"""Command-line entry point for starting BlueWhale Code."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Build the BlueWhale command-line parser."""
    parser = argparse.ArgumentParser(
        prog="bluewhale",
        description="Run the BlueWhale coding agent.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start the local Web application.")
    serve_parser.add_argument("--workspace", required=True, help="Project directory to operate on.")
    serve_parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host.")
    serve_parser.add_argument("--port", default=8000, type=int, help="HTTP bind port.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse startup options for the local BlueWhale Web application."""
    args = build_parser().parse_args(argv)
    print(
        f"BlueWhale serve requested for workspace {args.workspace} "
        f"on http://{args.host}:{args.port}"
    )
    return 0
