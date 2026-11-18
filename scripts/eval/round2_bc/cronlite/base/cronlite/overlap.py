"""What happens when a run is due while the previous one is still running: a small simulator of overlap policies.

Policies:
    allow  every due run starts at once, even if others are running
    skip   a due run is dropped while another run of the job is still going
    queue  a due run waits until the running one finishes; at most `max_queue` runs wait, later ones are dropped
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .errors import CronError

POLICIES = ("allow", "skip", "queue")


@dataclass(frozen=True)
class Planned:
    due: datetime
    start: datetime | None      # None: dropped
    end: datetime | None

    @property
    def dropped(self) -> bool:
        return self.start is None

    @property
    def delay(self) -> timedelta | None:
        return None if self.start is None else self.start - self.due


def simulate(due_times: Iterable[datetime], duration: timedelta | Iterable[timedelta], policy: str = "skip",
             max_queue: int = 1) -> list[Planned]:
    """Plan every due time under `policy`. `duration` is one length for all runs or one per due time."""
    if policy not in POLICIES:
        raise CronError(f"policy must be one of {', '.join(POLICIES)}")
    if max_queue < 0:
        raise CronError("max_queue must be >= 0")
    due = sorted(due_times)
    if isinstance(duration, timedelta):
        lengths = [duration] * len(due)
    else:
        lengths = list(duration)
        if len(lengths) != len(due):
            raise CronError("one duration per due time is needed")
    if any(d < timedelta(0) for d in lengths):
        raise CronError("durations must not be negative")
    plan: list[Planned] = []
    busy_until: datetime | None = None
    waiting: list[tuple[datetime, timedelta]] = []
    for when, length in zip(due, lengths):
        if policy == "allow":
            plan.append(Planned(when, when, when + length))
            continue
        # start queued runs that can start before this due time
        while waiting and busy_until is not None and busy_until <= when:
            q_due, q_len = waiting.pop(0)
            start = busy_until
            busy_until = start + q_len
            plan.append(Planned(q_due, start, busy_until))
        if busy_until is None or busy_until <= when:
            busy_until = when + length
            plan.append(Planned(when, when, busy_until))
        elif policy == "queue" and len(waiting) < max_queue:
            waiting.append((when, length))
        else:
            plan.append(Planned(when, None, None))
    while waiting:
        q_due, q_len = waiting.pop(0)
        start = max(busy_until, q_due) if busy_until else q_due
        busy_until = start + q_len
        plan.append(Planned(q_due, start, busy_until))
    return sorted(plan, key=lambda p: (p.due, p.start or p.due))


def summarize(plan: Iterable[Planned]) -> dict:
    """Counts and delays of a plan."""
    plan = list(plan)
    started = [p for p in plan if not p.dropped]
    delays = [p.delay.total_seconds() for p in started]
    return {"due": len(plan), "started": len(started), "dropped": len(plan) - len(started),
            "max_delay_seconds": max(delays) if delays else 0,
            "delayed": sum(1 for d in delays if d > 0)}


def concurrency(plan: Iterable[Planned]) -> int:
    """The largest number of runs going on at the same moment (a run ending exactly when another starts does not
    overlap it)."""
    events = []
    for p in plan:
        if not p.dropped:
            events.append((p.start, 1))
            events.append((p.end, -1))
    events.sort(key=lambda e: (e[0], e[1]))
    now = best = 0
    for _, step in events:
        now += step
        best = max(best, now)
    return best
