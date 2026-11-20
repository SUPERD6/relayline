"""Estimating the load a set of jobs puts on a machine: busy minutes per day and peak concurrency. Each job follows an
overlap policy (see `overlap`): with `skip` or `queue`, runs that would overlap are dropped or wait."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .analysis import firings
from .errors import CronError
from .expr import CronExpr
from .overlap import POLICIES, Planned, simulate, summarize

# runs due this long before a window are planned too, so a run still going (or waiting) when it opens is seen
LOOKBACK = timedelta(days=1)


@dataclass(frozen=True)
class JobLoad:
    name: str
    expr: CronExpr
    minutes: int          # how long one run takes, whole minutes, at least 1
    policy: str = "allow"
    max_queue: int = 1    # queue policy: how many runs may wait

    def __post_init__(self):
        if self.minutes < 1:
            raise CronError(f"job {self.name!r}: a run takes at least one minute")
        if self.policy not in POLICIES:
            raise CronError(f"job {self.name!r}: policy must be one of {', '.join(POLICIES)}")
        if self.max_queue < 0:
            raise CronError(f"job {self.name!r}: max_queue must be >= 0")


def _planned(job: JobLoad, start: datetime, end: datetime) -> list[Planned]:
    """The job's runs due after `start - LOOKBACK` up to `end`, planned under its policy."""
    lookback = start - max(LOOKBACK, timedelta(minutes=job.minutes))
    due = firings(job.expr, lookback, end)
    return simulate(due, timedelta(minutes=job.minutes), job.policy, job.max_queue)


def busy_minutes(jobs: list[JobLoad], day: datetime) -> dict[str, int]:
    """Minutes of work each job does on the calendar day of `day`: runs that start that day (a run that crosses
    midnight is counted on the day it starts; a queued run on the day it actually starts; dropped runs not at
    all)."""
    first = day.replace(hour=0, minute=0, second=0, microsecond=0)
    after = first + timedelta(days=1)
    out = {}
    for j in jobs:
        runs = [p for p in _planned(j, first - timedelta(minutes=1), after) if not p.dropped]
        out[j.name] = j.minutes * sum(1 for p in runs if first <= p.start < after)
    return out


def occupancy(jobs: list[JobLoad], start: datetime, end: datetime) -> dict[datetime, list[str]]:
    """For every minute in (start, end] in which at least one job is running, the names running (sorted)."""
    minutes: dict[datetime, list[str]] = {}
    for job in jobs:
        for p in _planned(job, start, end):
            if p.dropped:
                continue
            for k in range(job.minutes):
                m = p.start + timedelta(minutes=k)
                if start < m <= end:
                    minutes.setdefault(m, []).append(job.name)
    return {m: sorted(names) for m, names in sorted(minutes.items())}


def _due_in(job: JobLoad, start: datetime, end: datetime) -> list[Planned]:
    return [p for p in _planned(job, start, end) if start < p.due <= end]


def dropped_runs(jobs: list[JobLoad], start: datetime, end: datetime) -> dict[str, int]:
    """How many runs of each job due in (start, end] its policy drops."""
    return {j.name: sum(1 for p in _due_in(j, start, end) if p.dropped) for j in jobs}


def policy_report(jobs: list[JobLoad], start: datetime, end: datetime) -> dict[str, dict]:
    """For each job, `overlap.summarize` of its runs due in (start, end] (a queued run's delay counts even when it
    starts after `end`)."""
    return {j.name: summarize(_due_in(j, start, end)) for j in jobs}


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
