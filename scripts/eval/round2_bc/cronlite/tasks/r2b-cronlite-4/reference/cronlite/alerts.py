"""Alerts from a run log: repeated failures, missed runs, runs that took too long."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .blackout import BlackoutCalendar
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


def flapping(log: RunLog, job: str, window: int = 6, threshold: int = 3) -> Alert | None:
    """An alert when the outcome changed at least `threshold` times within the job's latest `window` runs."""
    if window < 2 or threshold < 1:
        raise CronError("window must be at least 2 and threshold at least 1")
    changes = log.transitions(job, window)
    if changes >= threshold:
        seen = min(window, len(log.for_job(job)))
        return Alert(job, "flapping", f"{changes} changes in the last {seen} runs")
    return None


def missed(log: RunLog, job: str, expr: CronExpr, start: datetime, end: datetime,
           tolerance: timedelta = timedelta(minutes=5), calendar: BlackoutCalendar | None = None) -> list[datetime]:
    """Firing times in (start, end] with no run of the job starting within `tolerance` after them. One run accounts
    for one firing only (the earliest one it can); firings on days the calendar closes are never missed."""
    if tolerance < timedelta(0):
        raise CronError("tolerance must not be negative")
    starts = sorted(r.started for r in log.for_job(job))
    out, t, i = [], start, 0
    while True:
        t = next_after(expr, t)
        if t > end:
            return out
        if calendar is not None and calendar.is_closed(t):
            continue
        while i < len(starts) and starts[i] < t:
            i += 1                       # too early for this firing and for every later one
        if i < len(starts) and starts[i] <= t + tolerance:
            i += 1                       # this run is used up
        else:
            out.append(t)


def slow(log: RunLog, job: str, limit: timedelta) -> list[datetime]:
    """Start times of the job's runs that took longer than `limit`."""
    return [r.started for r in log.for_job(job) if r.finished - r.started > limit]


def check(log: RunLog, schedules: dict[str, CronExpr], start: datetime, end: datetime,
          fail_threshold: int = 3, slow_limit: timedelta | None = None, flap_threshold: int | None = None,
          flap_window: int = 6, calendars: dict[str, BlackoutCalendar] | None = None) -> list[Alert]:
    """All alerts for the named jobs, ordered by job name then kind (failing, flapping, missed, slow). Flapping is
    only checked when `flap_threshold` is given; `calendars` maps job names to their blackout calendars, and a
    calendar under the key "*" applies to every job without its own."""
    calendars = calendars or {}
    alerts: list[Alert] = []
    for job in sorted(schedules):
        a = failing(log, job, fail_threshold)
        if a:
            alerts.append(a)
        if flap_threshold is not None:
            a = flapping(log, job, flap_window, flap_threshold)
            if a:
                alerts.append(a)
        gone = missed(log, job, schedules[job], start, end, calendar=calendars.get(job, calendars.get("*")))
        if gone:
            alerts.append(Alert(job, "missed", f"{len(gone)} missed, first at {gone[0]:%Y-%m-%d %H:%M}"))
        if slow_limit is not None:
            late = slow(log, job, slow_limit)
            if late:
                alerts.append(Alert(job, "slow", f"{len(late)} run(s) over {slow_limit}"))
    return alerts
