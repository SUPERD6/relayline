"""Finding the next times an expression fires (minute resolution)."""
from __future__ import annotations

from datetime import datetime, timedelta

from .errors import CronError
from .expr import CronExpr

SEARCH_LIMIT = timedelta(days=366 * 4)


def next_after(expr: CronExpr, when: datetime) -> datetime:
    """The first matching minute strictly after `when` (seconds are dropped first)."""
    t = when.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = t + SEARCH_LIMIT
    while t < end:
        if not expr.day_matches(t):
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if not expr.fields["hour"].matches(t.hour):
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if expr.fields["minute"].matches(t.minute):
            return t
        t += timedelta(minutes=1)
    raise CronError(f"{expr.text!r} never fires")


def upcoming(expr: CronExpr, when: datetime, count: int) -> list[datetime]:
    """The next `count` firing times after `when`."""
    out, t = [], when
    for _ in range(count):
        t = next_after(expr, t)
        out.append(t)
    return out
