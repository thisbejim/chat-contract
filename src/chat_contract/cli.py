"""Command-line interface for chat-contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .parser import lint_text
from .report import exit_code, render_json, render_junit, render_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chat-contract",
        description="Preflight-check OpenAI-style chat or Responses API request JSON offline.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="-",
        help="JSON/JSONL request file, or - to read stdin (default: -)",
    )
    parser.add_argument(
        "--profile",
        choices=("auto", "chat-completions", "responses"),
        default="auto",
        help="request profile to validate (default: auto)",
    )
    parser.add_argument(
        "--input-format",
        choices=("auto", "json", "jsonl"),
        default="auto",
        help="input framing (default: auto-detect JSON vs JSONL)",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json", "junit"),
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print JSON output",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures (exit status 1)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.path == "-":
            text = sys.stdin.read()
            source = "stdin"
        else:
            source_path = Path(args.path)
            text = source_path.read_text(encoding="utf-8")
            source = str(source_path)
    except OSError as exc:
        print(f"chat-contract: cannot read {args.path!r}: {exc}", file=sys.stderr)
        return 2
    result = lint_text(
        text,
        input_format=args.input_format,
        profile=args.profile,
        strict=args.strict,
        source=source,
    )
    if args.output_format == "json":
        output = render_json(result, pretty=args.pretty)
    elif args.output_format == "junit":
        output = render_junit(result, strict=args.strict)
    else:
        output = render_text(result, strict=args.strict)
    try:
        print(output)
    except BrokenPipeError:
        return 0
    return exit_code(result, strict=args.strict)
