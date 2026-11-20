"""A registry of named jobs, each with a schedule; failed runs are retried with a growing delay."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .errors import CronError
from .expr import CronExpr
from .schedule import next_after, next_run


@dataclass
class Job:
    name: str
    expr: CronExpr
    retries: int = 0              # extra attempts after a failure
    retry_delay: int = 5          # minutes before the first retry
    backoff: float = 1.0          # each further retry waits this many times longer
    max_delay: int | None = None  # minutes; no retry waits longer than this
    attempts: int = field(default=0, init=False)
    retry_at: datetime | None = field(default=None, init=False)

    def __post_init__(self):
        if self.retries < 0 or self.retry_delay <= 0:
            raise CronError(f"job {self.name!r}: retries must be >= 0 and retry_delay > 0")
        if self.backoff < 1:
            raise CronError(f"job {self.name!r}: backoff must be at least 1")
        if self.max_delay is not None and self.max_delay < self.retry_delay:
            raise CronError(f"job {self.name!r}: max_delay must not be below retry_delay")

    def delay(self, attempt: int) -> int:
        """Minutes to wait before retry number `attempt` (1-based): retry_delay * backoff**(attempt-1), rounded down
        to whole minutes, capped at max_delay."""
        minutes = int(self.retry_delay * self.backoff ** (attempt - 1))
        return minutes if self.max_delay is None else min(minutes, self.max_delay)

    def next_run(self, when: datetime) -> datetime:
        """The next minute after `when` at which this job runs (its pending retry counts)."""
        return next_run(self.expr, when, self.retry_at)


class Registry:
    def __init__(self):
        self.jobs: dict[str, Job] = {}

    def add(self, name: str, schedule: str, **options) -> Job:
        if name in self.jobs:
            raise CronError(f"job {name!r} already exists")
        job = Job(name, CronExpr.parse(schedule), **options)
        self.jobs[name] = job
        return job

    def due(self, when: datetime) -> list[str]:
        """Names of jobs to run at this minute: scheduled ones and pending retries, each name once, in name order."""
        minute = when.replace(second=0, microsecond=0)
        return sorted(j.name for j in self.jobs.values() if j.expr.matches(minute) or j.retry_at == minute)

    def next_due(self, when: datetime) -> tuple[datetime, list[str]] | None:
        """The earliest minute after `when` at which any job runs, with the names due then; None without jobs."""
        if not self.jobs:
            return None
        first = min(job.next_run(when) for job in self.jobs.values())
        return first, self.due(first)

    def record_success(self, name: str) -> None:
        job = self.jobs[name]
        job.attempts, job.retry_at = 0, None

    def record_failure(self, name: str, when: datetime) -> datetime | None:
        """Schedule the next retry while retries remain and return its time; None once they are used up, and also
        when the retry would not come before the job's next scheduled run (that run takes its place; the attempt
        count starts over)."""
        job = self.jobs[name]
        minute = when.replace(second=0, microsecond=0)
        job.attempts += 1
        if job.attempts > job.retries:
            job.attempts, job.retry_at = 0, None
            return None
        retry = minute + timedelta(minutes=job.delay(job.attempts))
        if retry >= next_after(job.expr, minute):
            job.attempts, job.retry_at = 0, None
            return None
        job.retry_at = retry
        return retry
