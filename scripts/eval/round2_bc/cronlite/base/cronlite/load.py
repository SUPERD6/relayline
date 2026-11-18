"""Estimating the load a set of jobs puts on a machine: busy minutes per day and peak concurrency."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .analysis import firings
from .errors import CronError
from .expr import CronExpr


@dataclass(frozen=True)
class JobLoad:
    name: str
    expr: CronExpr
    minutes: int          # how long one run takes, whole minutes, at least 1

    def __post_init__(self):
        if self.minutes < 1:
            raise CronError(f"job {self.name!r}: a run takes at least one minute")


def busy_minutes(jobs: list[JobLoad], day: datetime) -> dict[str, int]:
    """Minutes of work each job does on the calendar day of `day` (runs starting that day; a run that crosses
    midnight is counted on the day it starts)."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=1)
    end = start + timedelta(days=1)
    return {j.name: j.minutes * len(firings(j.expr, start, end)) for j in jobs}


def occupancy(jobs: list[JobLoad], start: datetime, end: datetime) -> dict[datetime, list[str]]:
    """For every minute in (start, end] in which at least one job is running, the names running (sorted)."""
    minutes: dict[datetime, list[str]] = {}
    lookback = start - timedelta(minutes=max((j.minutes for j in jobs), default=1))
    for job in jobs:
        for t in firings(job.expr, lookback, end):
            for k in range(job.minutes):
                m = t + timedelta(minutes=k)
                if start < m <= end:
                    minutes.setdefault(m, []).append(job.name)
    return {m: sorted(names) for m, names in sorted(minutes.items())}


def peak(jobs: list[JobLoad], start: datetime, end: datetime) -> tuple[int, datetime | None]:
    """The highest number of jobs running in one minute of the window and the first minute it happens."""
    occ = occupancy(jobs, start, end)
    if not occ:
        return 0, None
    best = max(len(v) for v in occ.values())
    first = next(m for m, v in occ.items() if len(v) == best)
    return best, first


def utilization(jobs: list[JobLoad], start: datetime, end: datetime, workers: int = 1) -> float:
    """Busy job-minutes in the window divided by the minutes `workers` could work, rounded to 4 places."""
    if workers < 1:
        raise CronError("workers must be at least 1")
    total = (end - start) // timedelta(minutes=1)
    if total <= 0:
        raise CronError("the window must be at least one minute long")
    used = sum(len(names) for names in occupancy(jobs, start, end).values())
    return round(used / (total * workers), 4)


def overloaded(jobs: list[JobLoad], start: datetime, end: datetime, workers: int) -> list[datetime]:
    """Minutes in which more jobs run than there are workers."""
    return [m for m, names in occupancy(jobs, start, end).items() if len(names) > workers]
