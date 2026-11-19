"""Allowed time windows: runs may only start inside certain hours; a run due outside is moved or dropped."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable

from .errors import CronError

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

    def next_allowed(self, when: datetime) -> datetime:
        """`when` itself if allowed, otherwise the next minute at which a window opens."""
        t = when.replace(second=0, microsecond=0)
        for _ in range(24 * 60 + 1):
            if self.allows(t):
                return t
            t += timedelta(minutes=1)
        raise CronError("no window ever opens")  # pragma: no cover - a window always opens within a day

    def place(self, due: Iterable[datetime], mode: str = "defer") -> list[tuple[datetime, datetime | None]]:
        """(due, start) for each due time: allowed ones start as due; others are deferred to the next opening
        (`defer`, several deferred runs may then start together) or dropped (`drop`, start None)."""
        if mode not in ("defer", "drop"):
            raise CronError("mode must be 'defer' or 'drop'")
        out = []
        for d in sorted(due):
            if self.allows(d):
                out.append((d, d))
            else:
                out.append((d, self.next_allowed(d) if mode == "defer" else None))
        return out

    def open_minutes_per_day(self) -> int:
        """How many minutes of a day fall inside at least one window."""
        return sum(1 for k in range(24 * 60)
                   if any(w.contains(time(k // 60, k % 60)) for w in self.windows))
