"""Schedules written in a fixed-offset local time, evaluated against UTC instants."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .blackout import BlackoutCalendar, next_open_after
from .errors import CronError
from .expr import CronExpr
from .schedule import next_after

_OFFSET = re.compile(r"(?:UTC|GMT)?\s*([+-])(\d{1,2})(?::?(\d{2}))?")


def parse_offset(text: str) -> timezone:
    """'+05:30', '-0800', 'UTC+2', 'Z' or 'UTC' as a fixed-offset timezone (at most 14 hours either way)."""
    text = text.strip()
    if text.upper() in ("Z", "UTC", "GMT"):
        return timezone.utc
    m = _OFFSET.fullmatch(text.upper())
    if not m:
        raise CronError(f"not a UTC offset: {text!r}")
    sign, hours, minutes = m.group(1), int(m.group(2)), int(m.group(3) or 0)
    if minutes > 59 or hours > 14 or (hours == 14 and minutes):
        raise CronError(f"offset out of range: {text!r}")
    delta = timedelta(hours=hours, minutes=minutes)
    return timezone(-delta if sign == "-" else delta)


def format_offset(tz: timezone) -> str:
    """'+05:30', '-08:00', '+00:00'."""
    total = int(tz.utcoffset(None).total_seconds() // 60)
    sign = "-" if total < 0 else "+"
    total = abs(total)
    return f"{sign}{total // 60:02d}:{total % 60:02d}"


def to_utc(local: datetime, tz: timezone) -> datetime:
    """A naive local wall time in `tz` as a naive UTC time."""
    return (local.replace(tzinfo=tz)).astimezone(timezone.utc).replace(tzinfo=None)


def to_local(utc: datetime, tz: timezone) -> datetime:
    """A naive UTC time as naive wall time in `tz`."""
    return utc.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)


def next_after_in(expr: CronExpr, utc_when: datetime, tz: timezone,
                  calendar: BlackoutCalendar | None = None) -> datetime:
    """The next firing time after the UTC instant `utc_when`, for an expression written in local time `tz`;
    the result is in UTC (naive). With a calendar, firings on closed days are skipped, judged by the local date."""
    local = to_local(utc_when, tz)
    found = next_after(expr, local) if calendar is None else next_open_after(expr, local, calendar)
    return to_utc(found, tz)


def upcoming_in(expr: CronExpr, utc_when: datetime, tz: timezone, count: int) -> list[datetime]:
    out, t = [], utc_when
    for _ in range(count):
        t = next_after_in(expr, t, tz)
        out.append(t)
    return out


def same_moment(expr_a: CronExpr, tz_a: timezone, expr_b: CronExpr, tz_b: timezone, start: datetime,
                within: timedelta = timedelta(days=7)) -> datetime | None:
    """The first UTC instant after `start` (UTC) at which both schedules fire, looking `within` ahead."""
    end = start + within
    a, b = next_after_in(expr_a, start, tz_a), next_after_in(expr_b, start, tz_b)
    while a <= end and b <= end:
        if a == b:
            return a
        if a < b:
            a = next_after_in(expr_a, a, tz_a)
        else:
            b = next_after_in(expr_b, b, tz_b)
    return None
