"""Command line: `python -m cronlite <command> ...`.

    next EXPR [--from ISO] [--count N]     the next firing times
    describe EXPR                           the expression in English
    phrase TEXT                             an English phrase as a cron expression
    lint EXPR [--ignore CODE ...]           warning codes, one per line (nothing when clean)
    check FILE [--from ISO] [--ignore CODE ...] [--json]
                                            warnings for every job of a saved registry; exit 1 when any
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from .describe import describe
from .errors import CronError
from .expr import CronExpr
from .human import to_cron
from .lint import _ignored, lint, lint_registry
from .schedule import upcoming
from .store import loads


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
    p.add_argument("--ignore", action="append", default=[], metavar="CODE")
    p = sub.add_parser("check", help="warnings for every job of a saved registry (JSON)")
    p.add_argument("file")
    p.add_argument("--from", dest="start")
    p.add_argument("--ignore", action="append", default=[], metavar="CODE")
    p.add_argument("--json", action="store_true", help="print the warnings as one JSON object")
    return ap


def _check(args, out) -> int:
    try:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise CronError(f"cannot read {args.file}: {exc.strerror}") from None
    found = lint_registry(loads(text, with_state=False), _when(args.start), args.ignore)
    if args.json:
        out.write(json.dumps(found, sort_keys=True) + "\n")
    else:
        for name, codes in found.items():
            out.write(f"{name}: {', '.join(codes)}\n")
    return 1 if found else 0


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
        elif args.command == "check":
            return _check(args, out)
        else:
            skip = _ignored(args.ignore)
            for w in lint(args.expr):
                if w.code not in skip:
                    out.write(w.code + "\n")
    except CronError as exc:
        sys.stderr.write(f"cronlite: {exc}\n")
        return 2
    return 0


def main() -> None:  # pragma: no cover - thin wrapper
    raise SystemExit(run(sys.argv[1:]))
