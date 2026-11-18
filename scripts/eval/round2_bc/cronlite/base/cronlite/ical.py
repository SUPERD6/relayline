"""Exporting upcoming runs as an iCalendar (RFC 5545) text with one event per run."""
from __future__ import annotations

from datetime import datetime, timedelta

from .errors import CronError
from .expr import CronExpr
from .schedule import upcoming


def _stamp(t: datetime) -> str:
    return t.strftime("%Y%m%dT%H%M%S")


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


def events(name: str, expr: CronExpr, start: datetime, count: int, duration: timedelta = timedelta(minutes=5),
           domain: str = "cronlite.invalid") -> list[list[str]]:
    """The VEVENT lines for the next `count` runs after `start` (floating local times, no time zone)."""
    if count < 0:
        raise CronError("count must not be negative")
    out = []
    for t in upcoming(expr, start, count):
        out.append(["BEGIN:VEVENT", f"UID:{_stamp(t)}-{escape(name)}@{domain}", f"DTSTAMP:{_stamp(start)}",
                    f"DTSTART:{_stamp(t)}", f"DTEND:{_stamp(t + duration)}", f"SUMMARY:{escape(name)}",
                    "END:VEVENT"])
    return out


def calendar(jobs: dict[str, CronExpr], start: datetime, count: int = 10,
             duration: timedelta = timedelta(minutes=5)) -> str:
    """A VCALENDAR with the next `count` runs of each job (jobs in name order), lines folded and ending in CRLF."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//cronlite//EN"]
    for name in sorted(jobs):
        for event in events(name, jobs[name], start, count, duration):
            lines += event
    lines.append("END:VCALENDAR")
    folded = [part for line in lines for part in fold(line)]
    return "\r\n".join(folded) + "\r\n"
