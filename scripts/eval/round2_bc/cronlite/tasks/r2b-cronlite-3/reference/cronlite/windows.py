"""Allowed time windows: runs may only start inside certain hours; a run due outside is moved or dropped."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable

from .analysis import firings
from .blackout import BlackoutCalendar
from .errors import CronError
from .expr import CronExpr
from .schedule import SEARCH_LIMIT

_SPAN = re.compile(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})")


@dataclass(frozen=True)
class Window:
    """Start inclusive, end exclusive. A window whose end is before its start wraps past midnight."""
    start: time
    end: time

    def contains(self, moment: time) -> bool:
        if self.start == self.end:
            return True                      # the whole day
        if self.start < self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end

    def __str__(self) -> str:
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


def parse_window(text: str) -> Window:
    """'09:00-17:30' or '22:00-06:00' (wrapping)."""
    m = _SPAN.fullmatch(text.strip())
    if not m:
        raise CronError(f"expected a window like 09:00-17:00, got {text!r}")
    h1, m1, h2, m2 = (int(g) for g in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        raise CronError(f"no such time in {text!r}")
    return Window(time(h1, m1), time(h2, m2))


class WindowSet:
    def __init__(self, windows: Iterable[Window | str]):
        self.windows = [w if isinstance(w, Window) else parse_window(w) for w in windows]
        if not self.windows:
            raise CronError("at least one window is needed")

    def allows(self, when: datetime) -> bool:
        moment = when.time().replace(second=0, microsecond=0)
        return any(w.contains(moment) for w in self.windows)

    def next_allowed(self, when: datetime, calendar: BlackoutCalendar | None = None) -> datetime:
        """`when` itself if allowed, otherwise the next minute at which a window opens. With a calendar, only minutes
        on open days count: a closed day is skipped whole, even the part of a window that falls on it."""
        t = when.replace(second=0, microsecond=0)
        if calendar is None:
            return self._next_allowed(t)
        for _ in range(SEARCH_LIMIT.days + 2):
            day = calendar.next_open_day(t.date())
            if day != t.date():
                t = datetime.combine(day, time(0, 0))
            t = self._next_allowed(t)
            if not calendar.is_closed(t):
                return t
            t = datetime.combine(t.date() + timedelta(days=1), time(0, 0))
        raise CronError("no window opens on an open day")

    def _next_allowed(self, t: datetime) -> datetime:
        for _ in range(24 * 60 + 1):
            if self.allows(t):
                return t
            t += timedelta(minutes=1)
        raise CronError("no window ever opens")  # pragma: no cover - a window always opens within a day

    def place(self, due: Iterable[datetime], mode: str = "defer", calendar: BlackoutCalendar | None = None,
              max_defer: timedelta | None = None) -> list[tuple[datetime, datetime | None]]:
        """(due, start) for each due time: allowed ones start as due; others are deferred to the next opening
        (`defer`, several deferred runs may then start together) or dropped (`drop`, start None).

        With a calendar, a run due on a closed day is dropped in either mode (it is suppressed, not postponed), and
        a deferred run starts at the next opening on an open day. With `max_defer`, a run that would start more than
        that long after it was due is dropped instead (exactly `max_defer` late still starts)."""
        if mode not in ("defer", "drop"):
            raise CronError("mode must be 'defer' or 'drop'")
        if max_defer is not None and max_defer < timedelta(0):
            raise CronError("max_defer must not be negative")
        out = []
        for d in sorted(due):
            if calendar is not None and calendar.is_closed(d):
                out.append((d, None))
            elif self.allows(d):
                out.append((d, d))
            elif mode == "drop":
                out.append((d, None))
            else:
                start = self.next_allowed(d, calendar)
                if max_defer is not None and start - d > max_defer:
                    start = None
                out.append((d, start))
        return out

    def open_minutes_per_day(self) -> int:
        """How many minutes of a day fall inside at least one window."""
        return sum(1 for k in range(24 * 60)
                   if any(w.contains(time(k // 60, k % 60)) for w in self.windows))


def plan_runs(expr: CronExpr, start: datetime, end: datetime, windows: WindowSet | Iterable[Window | str],
              calendar: BlackoutCalendar | None = None, mode: str = "defer",
              max_defer: timedelta | None = None) -> list[tuple[datetime, datetime | None]]:
    """`WindowSet.place` applied to every firing time of `expr` after `start` up to `end` inclusive."""
    if not isinstance(windows, WindowSet):
        windows = WindowSet(windows)
    return windows.place(firings(expr, start, end), mode, calendar, max_defer)


def placement_counts(placed: Iterable[tuple[datetime, datetime | None]]) -> dict[str, int]:
    """How many runs of a placement start on time, start late, or are dropped."""
    counts = {"on_time": 0, "deferred": 0, "dropped": 0}
    for due, start in placed:
        key = "dropped" if start is None else "on_time" if start == due else "deferred"
        counts[key] += 1
    return counts
