"""Looking at a schedule over a period: how often it fires, the gaps between runs, collisions between jobs."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Iterable

from .errors import CronError
from .expr import CronExpr
from .schedule import next_after


def firings(expr: CronExpr, start: datetime, end: datetime, limit: int = 200_000) -> list[datetime]:
    """Every firing time after `start` up to `end` inclusive (CronError beyond `limit` of them)."""
    out, t = [], start
    while True:
        t = next_after(expr, t)
        if t > end:
            return out
        out.append(t)
        if len(out) > limit:
            raise CronError(f"more than {limit} firings between {start} and {end}")


def per_day(times: Iterable[datetime]) -> dict[str, int]:
    """Firings per calendar day, as {'YYYY-MM-DD': count} in date order."""
    counts = Counter(t.date().isoformat() for t in times)
    return dict(sorted(counts.items()))


def per_hour(times: Iterable[datetime]) -> list[int]:
    """Firings per hour of day: a list of 24 counts."""
    counts = [0] * 24
    for t in times:
        counts[t.hour] += 1
    return counts


def gaps(times: Iterable[datetime]) -> dict:
    """The shortest, longest and mean time between consecutive firings (None with fewer than two)."""
    times = sorted(times)
    deltas = [b - a for a, b in zip(times, times[1:])]
    if not deltas:
        return {"min": None, "max": None, "mean": None}
    total = sum(deltas, timedelta(0))
    return {"min": min(deltas), "max": max(deltas), "mean": total / len(deltas)}


def collisions(schedules: dict[str, CronExpr], start: datetime, end: datetime) -> dict[datetime, list[str]]:
    """Minutes at which two or more of the named schedules fire, with the names (sorted), in time order."""
    by_time: dict[datetime, list[str]] = {}
    for name, expr in schedules.items():
        for t in firings(expr, start, end):
            by_time.setdefault(t, []).append(name)
    return {t: sorted(names) for t, names in sorted(by_time.items()) if len(names) > 1}


def busiest_minute(schedules: dict[str, CronExpr], start: datetime, end: datetime) -> tuple[datetime, int] | None:
    """The minute with the most jobs firing (the earliest on ties) and how many; None when nothing fires."""
    counts: Counter = Counter()
    for expr in schedules.values():
        counts.update(firings(expr, start, end))
    if not counts:
        return None
    best = max(counts.items(), key=lambda kv: (kv[1], -kv[0].timestamp()))
    return best


def spread_suggestion(schedules: dict[str, CronExpr], minute_choices: Iterable[int] = range(60)) -> dict[str, int]:
    """For jobs that all fire at minute 0 of some hours, a minute for each so that they no longer start together:
    names in sorted order get the minute choices in order. Jobs not firing at minute 0 keep no suggestion."""
    choices = list(minute_choices)
    at_zero = sorted(n for n, e in schedules.items() if 0 in e.fields["minute"].values
                     and len(e.fields["minute"].values) == 1)
    if len(at_zero) > len(choices):
        raise CronError("not enough minute choices to spread the jobs")
    return {name: choices[k] for k, name in enumerate(at_zero)}
