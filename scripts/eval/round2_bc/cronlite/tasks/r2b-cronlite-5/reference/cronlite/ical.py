"""Exporting upcoming runs as an iCalendar (RFC 5545) text with one event per run."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .blackout import BlackoutCalendar, next_open_after
from .errors import CronError
from .expr import CronExpr
from .schedule import next_after
from .zones import next_after_in


def _stamp(t: datetime, utc: bool = False) -> str:
    return t.strftime("%Y%m%dT%H%M%S") + ("Z" if utc else "")


def escape(text: str) -> str:
    """Backslash, semicolon, comma and line breaks escaped as RFC 5545 requires."""
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line: str, width: int = 75) -> list[str]:
    """A content line folded to at most `width` characters per physical line; continuation lines start with a
    space (counted in the width)."""
    if width < 2:
        raise CronError("width must be at least 2")
    out = [line[:width]]
    rest = line[width:]
    while rest:
        out.append(" " + rest[:width - 1])
        rest = rest[width - 1:]
    return out


def run_times(expr: CronExpr, start: datetime, count: int, tz: timezone | None = None,
              closed: BlackoutCalendar | None = None) -> list[datetime]:
    """The next `count` runs after `start`. Without `tz` all times are floating local times; with `tz` the
    expression is local time in `tz` while `start` and the results are UTC. Runs on days `closed` closes are left
    out (judged by the local date) and do not count towards `count`."""
    out, t = [], start
    while len(out) < count:
        if tz is not None:
            t = next_after_in(expr, t, tz, closed)
        else:
            t = next_after(expr, t) if closed is None else next_open_after(expr, t, closed)
        out.append(t)
    return out


def events(name: str, expr: CronExpr, start: datetime, count: int, duration: timedelta = timedelta(minutes=5),
           domain: str = "cronlite.invalid", tz: timezone | None = None,
           closed: BlackoutCalendar | None = None) -> list[list[str]]:
    """The VEVENT lines for the next `count` runs after `start`: floating local times, or UTC times ending in `Z`
    when `tz` is given."""
    if count < 0:
        raise CronError("count must not be negative")
    utc = tz is not None
    out = []
    for t in run_times(expr, start, count, tz, closed):
        out.append(["BEGIN:VEVENT", f"UID:{_stamp(t, utc)}-{escape(name)}@{domain}", f"DTSTAMP:{_stamp(start, utc)}",
                    f"DTSTART:{_stamp(t, utc)}", f"DTEND:{_stamp(t + duration, utc)}", f"SUMMARY:{escape(name)}",
                    "END:VEVENT"])
    return out


def calendar(jobs: dict[str, CronExpr], start: datetime, count: int = 10,
             duration: timedelta = timedelta(minutes=5), tz: timezone | None = None,
             closed: BlackoutCalendar | None = None) -> str:
    """A VCALENDAR with the next `count` runs of each job (jobs in name order), lines folded and ending in CRLF."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//cronlite//EN"]
    for name in sorted(jobs):
        for event in events(name, jobs[name], start, count, duration, tz=tz, closed=closed):
            lines += event
    lines.append("END:VCALENDAR")
    folded = [part for line in lines for part in fold(line)]
    return "\r\n".join(folded) + "\r\n"
