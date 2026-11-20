"""A registry of named jobs, each with a schedule; failed runs are retried after a fixed delay. Jobs can carry tags
and can be paused."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

from .errors import CronError
from .expr import CronExpr

_TAG = re.compile(r"[a-z0-9-]+")


def normalize_tags(tags: Iterable[str] | str) -> tuple[str, ...]:
    """Tags stripped and lower-cased, without repeats, sorted. A single string is one tag (not split into letters)."""
    if isinstance(tags, str):
        tags = [tags]
    out = set()
    for tag in tags:
        if not isinstance(tag, str):
            raise CronError(f"tag {tag!r} is not a string")
        clean = tag.strip().lower()
        if not _TAG.fullmatch(clean):
            raise CronError(f"bad tag {tag!r}: use letters, digits and hyphens")
        out.add(clean)
    return tuple(sorted(out))


@dataclass
class Job:
    name: str
    expr: CronExpr
    retries: int = 0          # extra attempts after a failure
    retry_delay: int = 5      # minutes
    tags: tuple = ()
    paused: bool = False
    attempts: int = field(default=0, init=False)
    retry_at: datetime | None = field(default=None, init=False)

    def __post_init__(self):
        if self.retries < 0 or self.retry_delay <= 0:
            raise CronError(f"job {self.name!r}: retries must be >= 0 and retry_delay > 0")
        if not isinstance(self.paused, bool):
            raise CronError(f"job {self.name!r}: paused must be true or false")
        self.tags = normalize_tags(self.tags)


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
        """Names of jobs to run at this minute: scheduled ones and pending retries, in name order. Paused jobs never
        run."""
        minute = when.replace(second=0, microsecond=0)
        active = [j for j in self.jobs.values() if not j.paused]
        names = [j.name for j in active if j.expr.matches(minute)]
        names += [j.name for j in active if j.retry_at == minute]
        return sorted(names)

    def pause(self, name: str) -> None:
        """Stop the job from running; a pending retry and the attempt count are dropped, not kept for later."""
        job = self.jobs[name]
        job.paused, job.attempts, job.retry_at = True, 0, None

    def resume(self, name: str) -> None:
        """Let the job run again from its next scheduled minute (runs missed while paused are not made up)."""
        self.jobs[name].paused = False

    def tagged(self, tag: str) -> list[str]:
        """Names of the jobs carrying the tag (paused ones included), in name order; the tag is matched like it is
        stored (stripped, any letter case)."""
        wanted = tag.strip().lower()
        return sorted(j.name for j in self.jobs.values() if wanted in j.tags)

    def record_success(self, name: str) -> None:
        job = self.jobs[name]
        job.attempts, job.retry_at = 0, None

    def record_failure(self, name: str, when: datetime) -> datetime | None:
        """Schedule a retry `retry_delay` minutes later while retries remain; None once they are used up, and always
        None for a paused job (no retry is scheduled and its attempt count stays at zero)."""
        job = self.jobs[name]
        if job.paused:
            job.attempts, job.retry_at = 0, None
            return None
        job.attempts += 1
        if job.attempts > job.retries:
            job.attempts, job.retry_at = 0, None
            return None
        job.retry_at = when.replace(second=0, microsecond=0) + timedelta(minutes=job.retry_delay)
        return job.retry_at
