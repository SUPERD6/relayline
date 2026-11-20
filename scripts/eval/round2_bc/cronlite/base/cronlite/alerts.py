"""Alerts from a run log: repeated failures, missed runs, runs that took too long."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .errors import CronError
from .expr import CronExpr
from .history import RunLog
from .schedule import next_after


@dataclass(frozen=True)
class Alert:
    job: str
    kind: str          # failing, missed, slow
    detail: str


def failing(log: RunLog, job: str, threshold: int = 3) -> Alert | None:
    """An alert when the job's latest `threshold` or more runs all failed."""
    if threshold < 1:
        raise CronError("threshold must be at least 1")
    streak = log.streak(job)
    if streak <= -threshold:
        last = log.last(job)
        return Alert(job, "failing", f"{-streak} failures in a row, last: {last.error}")
    return None


def missed(log: RunLog, job: str, expr: CronExpr, start: datetime, end: datetime,
           tolerance: timedelta = timedelta(minutes=5)) -> list[datetime]:
    """Firing times in (start, end] with no run of the job starting within `tolerance` after them."""
    starts = [r.started for r in log.for_job(job)]
    out, t = [], start
    while True:
        t = next_after(expr, t)
        if t > end:
            return out
        if not any(t <= s <= t + tolerance for s in starts):
            out.append(t)


def slow(log: RunLog, job: str, limit: timedelta) -> list[datetime]:
    """Start times of the job's runs that took longer than `limit`."""
    return [r.started for r in log.for_job(job) if r.finished - r.started > limit]


def check(log: RunLog, schedules: dict[str, CronExpr], start: datetime, end: datetime,
          fail_threshold: int = 3, slow_limit: timedelta | None = None) -> list[Alert]:
    """All alerts for the named jobs, ordered by job name then kind (failing, missed, slow)."""
    alerts: list[Alert] = []
    for job in sorted(schedules):
        a = failing(log, job, fail_threshold)
        if a:
            alerts.append(a)
        gone = missed(log, job, schedules[job], start, end)
        if gone:
            alerts.append(Alert(job, "missed", f"{len(gone)} missed, first at {gone[0]:%Y-%m-%d %H:%M}"))
        if slow_limit is not None:
            late = slow(log, job, slow_limit)
            if late:
                alerts.append(Alert(job, "slow", f"{len(late)} run(s) over {slow_limit}"))
    return alerts
