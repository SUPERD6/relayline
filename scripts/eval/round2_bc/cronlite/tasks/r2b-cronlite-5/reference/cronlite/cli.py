"""Command line: `python -m cronlite <command> ...`.

    next EXPR [--from ISO] [--count N]     the next firing times
    describe EXPR                           the expression in English
    phrase TEXT                             an English phrase as a cron expression
    lint EXPR                               warning codes, one per line (nothing when clean)
    ical NAME EXPR [--from ISO] [--count N] [--offset TEXT] [--closed FILE]
                                            the next runs as an iCalendar text (UTC with --offset)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from .blackout import parse_calendar
from .describe import describe
from .errors import CronError
from .expr import CronExpr
from .human import to_cron
from .ical import calendar
from .lint import lint
from .schedule import upcoming
from .zones import parse_offset


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
    p = sub.add_parser("ical", help="the next runs as an iCalendar text")
    p.add_argument("name")
    p.add_argument("expr")
    p.add_argument("--from", dest="start")
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--offset", help="the expression is local time at this UTC offset; --from and the output are UTC")
    p.add_argument("--closed", help="a blackout calendar file (see parse_calendar): closed days get no events")
    return ap


def _closed(path: str | None):
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise CronError(f"cannot read {path}: {exc.strerror}") from None
    return parse_calendar(text)


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
        elif args.command == "ical":
            if args.count < 1:
                raise CronError("--count must be at least 1")
            tz = parse_offset(args.offset) if args.offset is not None else None
            if args.start is None and tz is not None:   # now, as a UTC time
                start = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
            else:
                start = _when(args.start)
            out.write(calendar({args.name: CronExpr.parse(args.expr)}, start, args.count, tz=tz,
                               closed=_closed(args.closed)))
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
