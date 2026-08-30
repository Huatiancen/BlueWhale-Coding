"""Command-line entry point for starting BlueWhale Code."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from bluewhale_agent.web.app import create_app


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
    subparsers.add_parser("desktop", help="Start the native macOS application.")
    eval_parser = subparsers.add_parser("eval", help="Run a repeatable Coding Agent suite.")
    eval_parser.add_argument("--suite", required=True, help="Path to suite.json.")
    eval_parser.add_argument("--output", default="eval-results", help="Report directory.")
    eval_parser.add_argument("--repeat", default=1, type=int, help="Runs per case.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate startup options and run the local BlueWhale Web application."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "desktop":
        from bluewhale_agent.desktop.launcher import run_desktop

        return run_desktop()
    if args.command == "eval":
        from bluewhale_agent.config import Settings
        from bluewhale_agent.evals.models import EvalSuite
        from bluewhale_agent.evals.runner import EvalRunner
        from bluewhale_agent.providers.deepseek import DeepSeekProvider

        suite_path = Path(args.suite).resolve(strict=True)
        suite = EvalSuite.load(suite_path)
        settings = Settings(workspace=suite_path.parent)
        report = asyncio.run(
            EvalRunner(lambda: DeepSeekProvider(settings), model=settings.model).run(
                suite,
                suite_directory=suite_path.parent,
                repeats=args.repeat,
            )
        )
        json_path, markdown_path = report.write(Path(args.output).resolve())
        print(f"BlueWhale evaluation complete: {json_path} and {markdown_path}")
        return 0
    workspace = Path(args.workspace).resolve(strict=False)
    if not workspace.is_dir():
        parser.error(f"workspace does not exist or is not a directory: {args.workspace}")
    print(f"BlueWhale serving workspace {workspace} on http://{args.host}:{args.port}")
    uvicorn.run(create_app(workspace=workspace), host=args.host, port=args.port)
    return 0
