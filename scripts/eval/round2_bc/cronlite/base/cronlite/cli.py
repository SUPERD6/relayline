"""Command line: `python -m cronlite <command> ...`.

    next EXPR [--from ISO] [--count N]     the next firing times
    describe EXPR                           the expression in English
    phrase TEXT                             an English phrase as a cron expression
    lint EXPR                               warning codes, one per line (nothing when clean)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from .describe import describe
from .errors import CronError
from .expr import CronExpr
from .human import to_cron
from .lint import lint
from .schedule import upcoming


def _when(text: str | None) -> datetime:
    if text is None:
        return datetime.now().replace(second=0, microsecond=0)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise CronError(f"not an ISO date and time: {text!r}") from None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cronlite", description="cron-style schedules")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("next", help="the next firing times")
    p.add_argument("expr")
    p.add_argument("--from", dest="start")
    p.add_argument("--count", type=int, default=5)
    p = sub.add_parser("describe", help="the expression in English")
    p.add_argument("expr")
    p = sub.add_parser("phrase", help="an English phrase as a cron expression")
    p.add_argument("text")
    p = sub.add_parser("lint", help="warnings about an expression")
    p.add_argument("expr")
    return ap


def run(argv: list[str], out=None) -> int:
    """Run one command, writing to `out` (default stdout); returns the exit code (2 on a CronError)."""
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        if args.command == "next":
            if args.count < 1:
                raise CronError("--count must be at least 1")
            for t in upcoming(CronExpr.parse(args.expr), _when(args.start), args.count):
                out.write(t.strftime("%Y-%m-%d %H:%M") + "\n")
        elif args.command == "describe":
            out.write(describe(args.expr) + "\n")
        elif args.command == "phrase":
            out.write(to_cron(args.text) + "\n")
        else:
            for w in lint(args.expr):
                out.write(w.code + "\n")
    except CronError as exc:
        sys.stderr.write(f"cronlite: {exc}\n")
        return 2
    return 0


def main() -> None:  # pragma: no cover - thin wrapper
    raise SystemExit(run(sys.argv[1:]))
