"""A five-field cron expression: minute hour day month weekday."""
from __future__ import annotations

import calendar
from datetime import datetime

from .errors import CronError
from .fields import FieldSpec, parse_field

ORDER = ("minute", "hour", "day", "month", "weekday")
ALIASES = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *"}


class CronExpr:
    def __init__(self, fields: dict[str, FieldSpec], text: str):
        self.fields = fields
        self.text = text

    @classmethod
    def parse(cls, text: str) -> "CronExpr":
        source = ALIASES.get(text.strip(), text)
        parts = source.split()
        if len(parts) != 5:
            raise CronError(f"expected 5 fields, found {len(parts)}")
        return cls({name: parse_field(name, part) for name, part in zip(ORDER, parts)}, text.strip())

    def __repr__(self) -> str:
        return f"CronExpr({self.text!r})"

    def day_of_month_matches(self, when: datetime) -> bool:
        """The day-of-month field alone: one of its numbers, or `L` on the last day of that month."""
        spec = self.fields["day"]
        if spec.matches(when.day):
            return True
        return spec.last and when.day == calendar.monthrange(when.year, when.month)[1]

    def day_matches(self, when: datetime) -> bool:
        """Month, day of month and weekday only (the time of day is ignored)."""
        f = self.fields
        if not f["month"].matches(when.month):
            return False
        weekday = (when.weekday() + 1) % 7  # cron counts Sunday as 0
        day_ok, weekday_ok = self.day_of_month_matches(when), f["weekday"].matches(weekday)
        # classic cron: when both day and weekday are restricted, either one may match
        if not f["day"].wildcard and not f["weekday"].wildcard:
            return day_ok or weekday_ok
        return day_ok and weekday_ok

    def matches(self, when: datetime) -> bool:
        f = self.fields
        return f["minute"].matches(when.minute) and f["hour"].matches(when.hour) and self.day_matches(when)
