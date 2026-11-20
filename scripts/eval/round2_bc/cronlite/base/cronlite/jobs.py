"""A registry of named jobs, each with a schedule; failed runs are retried after a fixed delay."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .errors import CronError
from .expr import CronExpr


@dataclass
class Job:
    name: str
    expr: CronExpr
    retries: int = 0          # extra attempts after a failure
    retry_delay: int = 5      # minutes
    attempts: int = field(default=0, init=False)
    retry_at: datetime | None = field(default=None, init=False)

    def __post_init__(self):
        if self.retries < 0 or self.retry_delay <= 0:
            raise CronError(f"job {self.name!r}: retries must be >= 0 and retry_delay > 0")


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
        """Names of jobs to run at this minute: scheduled ones and pending retries, in name order."""
        minute = when.replace(second=0, microsecond=0)
        names = [j.name for j in self.jobs.values() if j.expr.matches(minute)]
        names += [j.name for j in self.jobs.values() if j.retry_at == minute]
        return sorted(names)

    def record_success(self, name: str) -> None:
        job = self.jobs[name]
        job.attempts, job.retry_at = 0, None

    def record_failure(self, name: str, when: datetime) -> datetime | None:
        """Schedule a retry `retry_delay` minutes later while retries remain; None once they are used up."""
        job = self.jobs[name]
        job.attempts += 1
        if job.attempts > job.retries:
            job.attempts, job.retry_at = 0, None
            return None
        job.retry_at = when.replace(second=0, microsecond=0) + timedelta(minutes=job.retry_delay)
        return job.retry_at
