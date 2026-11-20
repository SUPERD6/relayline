"""Blackout calendars: days on which scheduled runs are suppressed (holidays, closed weekdays, freeze periods)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

from .errors import CronError
from .expr import CronExpr
from .schedule import SEARCH_LIMIT, next_after


@dataclass
class BlackoutCalendar:
    """`dates`: single days; `weekdays`: closed weekdays in cron numbering (Sunday 0); `periods`: inclusive
    (first, last) date ranges."""
    dates: set = field(default_factory=set)
    weekdays: set = field(default_factory=set)
    periods: list = field(default_factory=list)

    def __post_init__(self):
        self.dates = {self._as_date(d) for d in self.dates}
        bad = {d for d in self.weekdays if not 0 <= d <= 6}
        if bad:
            raise CronError(f"weekday(s) outside 0-6: {sorted(bad)}")
        self.weekdays = set(self.weekdays)
        periods = []
        for first, last in self.periods:
            first, last = self._as_date(first), self._as_date(last)
            if last < first:
                raise CronError(f"period {first} - {last} ends before it starts")
            periods.append((first, last))
        self.periods = sorted(periods)

    @staticmethod
    def _as_date(value) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            raise CronError(f"not a date: {value!r}") from None

    def add(self, day) -> None:
        self.dates.add(self._as_date(day))

    def add_period(self, first, last) -> None:
        first, last = self._as_date(first), self._as_date(last)
        if last < first:
            raise CronError(f"period {first} - {last} ends before it starts")
        self.periods = sorted(self.periods + [(first, last)])

    def is_closed(self, when) -> bool:
        day = self._as_date(when)
        if day in self.dates or (day.weekday() + 1) % 7 in self.weekdays:
            return True
        return any(first <= day <= last for first, last in self.periods)

    def next_open_day(self, day) -> date:
        """`day` itself when it is open, otherwise the first open day after it."""
        day = self._as_date(day)
        for _ in range(SEARCH_LIMIT.days + 1):
            if not self.is_closed(day):
                return day
            day += timedelta(days=1)
        raise CronError("the calendar has no open day")

    def closed_days(self, first, last) -> list[date]:
        """Every closed day from `first` to `last` inclusive."""
        first, last = self._as_date(first), self._as_date(last)
        out, day = [], first
        while day <= last:
            if self.is_closed(day):
                out.append(day)
            day += timedelta(days=1)
        return out

    def merge(self, other: "BlackoutCalendar") -> "BlackoutCalendar":
        """A calendar closed whenever either one is."""
        return BlackoutCalendar(self.dates | other.dates, self.weekdays | other.weekdays,
                                self.periods + other.periods)


def next_open_after(expr: CronExpr, when: datetime, calendar: BlackoutCalendar) -> datetime:
    """The first firing time after `when` that does not fall on a closed day."""
    t, end = when, when + SEARCH_LIMIT
    while t < end:
        t = next_after(expr, t)
        if not calendar.is_closed(t):
            return t
        # jump to the end of the closed day so a minute-by-minute schedule does not crawl through it
        t = datetime.combine(t.date(), datetime.max.time()).replace(second=0, microsecond=0)
    raise CronError(f"{expr.text!r} never fires on an open day")


def runs_between(expr: CronExpr, start: datetime, end: datetime,
                 calendar: BlackoutCalendar | None = None, limit: int = 100_000) -> list[datetime]:
    """Firing times after `start` and up to `end` inclusive, skipping closed days; at most `limit` of them."""
    out, t = [], start
    while len(out) < limit:
        t = next_after(expr, t) if calendar is None else next_open_after(expr, t, calendar)
        if t > end:
            break
        out.append(t)
    return out


def suppressed(expr: CronExpr, start: datetime, end: datetime, calendar: BlackoutCalendar) -> list[datetime]:
    """Firing times in the window that the calendar suppresses."""
    every = runs_between(expr, start, end)
    return [t for t in every if calendar.is_closed(t)]


_WEEKDAY_WORDS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def parse_calendar(text: str) -> BlackoutCalendar:
    """A calendar from lines like:

        2026-12-25            a single day
        2026-12-24..2027-01-01   an inclusive period
        closed sat sun        closed weekdays (three-letter names)

    Blank lines and anything after `#` are ignored; a bad line raises CronError naming its line number."""
    cal = BlackoutCalendar()
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            if line.lower().startswith("closed "):
                for word in line[7:].split():
                    if word.lower() not in _WEEKDAY_WORDS:
                        raise CronError(f"unknown weekday {word!r}")
                    cal.weekdays.add(_WEEKDAY_WORDS[word.lower()])
            elif ".." in line:
                first, last = (part.strip() for part in line.split("..", 1))
                cal.add_period(first, last)
            else:
                cal.add(line)
        except CronError as exc:
            raise CronError(f"line {number}: {exc}") from None
    return cal


def weekend_calendar(extra: Iterable = ()) -> BlackoutCalendar:
    """Saturdays and Sundays closed, plus any extra dates."""
    return BlackoutCalendar(set(extra), {0, 6})
