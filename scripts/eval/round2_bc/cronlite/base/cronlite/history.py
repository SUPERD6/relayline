"""A log of job runs: outcomes, durations, streaks, and a JSON-friendly form."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .errors import CronError


@dataclass(frozen=True)
class Run:
    job: str
    started: datetime
    finished: datetime
    ok: bool
    error: str | None = None

    @property
    def seconds(self) -> float:
        return (self.finished - self.started).total_seconds()

    def to_dict(self) -> dict:
        return {"job": self.job, "started": self.started.isoformat(), "finished": self.finished.isoformat(),
                "ok": self.ok, "error": self.error}

    @classmethod
    def from_dict(cls, data: dict) -> "Run":
        try:
            return cls(data["job"], datetime.fromisoformat(data["started"]),
                       datetime.fromisoformat(data["finished"]), bool(data["ok"]), data.get("error"))
        except (KeyError, ValueError, TypeError) as exc:
            raise CronError(f"bad run record: {exc}") from None


class RunLog:
    def __init__(self, runs: Iterable[Run] = ()):
        self.runs: list[Run] = []
        for run in runs:
            self.add(run)

    def add(self, run: Run) -> None:
        if run.finished < run.started:
            raise CronError(f"run of {run.job!r} finishes before it starts")
        self.runs.append(run)
        self.runs.sort(key=lambda r: (r.started, r.job))

    def record(self, job: str, started: datetime, finished: datetime, ok: bool = True,
               error: str | None = None) -> Run:
        run = Run(job, started, finished, ok, None if ok else (error or "failed"))
        self.add(run)
        return run

    def for_job(self, job: str) -> list[Run]:
        return [r for r in self.runs if r.job == job]

    def jobs(self) -> list[str]:
        return sorted({r.job for r in self.runs})

    def last(self, job: str, ok: bool | None = None) -> Run | None:
        """The latest run of the job (only successes or failures when `ok` is given)."""
        runs = [r for r in self.for_job(job) if ok is None or r.ok == ok]
        return runs[-1] if runs else None

    def streak(self, job: str) -> int:
        """Positive: the number of successes since the last failure; negative: consecutive failures; 0: no runs."""
        runs = self.for_job(job)
        if not runs:
            return 0
        latest, count = runs[-1].ok, 0
        for r in reversed(runs):
            if r.ok != latest:
                break
            count += 1
        return count if latest else -count

    def stats(self, job: str) -> dict:
        runs = self.for_job(job)
        durations = sorted(r.seconds for r in runs)
        ok = sum(r.ok for r in runs)
        return {"runs": len(runs), "failures": len(runs) - ok,
                "success_rate": ok / len(runs) if runs else None,
                "mean_seconds": sum(durations) / len(durations) if durations else None,
                "max_seconds": durations[-1] if durations else None,
                "streak": self.streak(job)}

    def prune(self, before: datetime) -> int:
        """Drop runs that started before `before`; returns how many were dropped."""
        keep = [r for r in self.runs if r.started >= before]
        dropped = len(self.runs) - len(keep)
        self.runs = keep
        return dropped

    def overlapping(self, job: str) -> list[tuple[Run, Run]]:
        """Pairs of consecutive runs of the job where the second started before the first finished."""
        runs = self.for_job(job)
        return [(a, b) for a, b in zip(runs, runs[1:]) if b.started < a.finished]

    def busiest_hour(self) -> int | None:
        """The hour of day (0-23) in which most runs started; ties go to the earliest hour."""
        if not self.runs:
            return None
        counts = [0] * 24
        for r in self.runs:
            counts[r.started.hour] += 1
        return max(range(24), key=lambda h: (counts[h], -h))

    def window(self, start: datetime, length: timedelta) -> list[Run]:
        """Runs that started within [start, start + length)."""
        return [r for r in self.runs if start <= r.started < start + length]

    def failure_reasons(self, job: str | None = None) -> dict[str, int]:
        """How often each error text occurred (all jobs, or one), most frequent first, ties by text."""
        counts: dict[str, int] = {}
        for r in self.runs:
            if not r.ok and (job is None or r.job == job):
                counts[r.error or "failed"] = counts.get(r.error or "failed", 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def daily_counts(self, job: str | None = None) -> dict[str, tuple[int, int]]:
        """{'YYYY-MM-DD': (successes, failures)} by start day, in date order."""
        out: dict[str, list[int]] = {}
        for r in self.runs:
            if job is None or r.job == job:
                cell = out.setdefault(r.started.date().isoformat(), [0, 0])
                cell[0 if r.ok else 1] += 1
        return {day: (ok, bad) for day, (ok, bad) in sorted(out.items())}

    def to_list(self) -> list[dict]:
        return [r.to_dict() for r in self.runs]

    @classmethod
    def from_list(cls, data: Iterable[dict]) -> "RunLog":
        return cls(Run.from_dict(d) for d in data)
