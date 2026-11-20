"""ISO dates in table columns: parsing, formatting and grouping by period."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Iterable

from .errors import CoercionError
from .table import Table

_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DATETIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?")
PERIODS = ("day", "week", "month", "quarter", "year")


def parse_date(text: str) -> date | datetime:
    """`YYYY-MM-DD` gives a date, `YYYY-MM-DD HH:MM[:SS]` (or with T) a naive datetime; anything else ValueError."""
    text = text.strip()
    m = _DATETIME.fullmatch(text)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    m = _DATE.fullmatch(text)
    if m:
        return date(*(int(g) for g in m.groups()))
    raise ValueError(f"not an ISO date: {text!r}")


def parse_dates(table: Table, columns: Iterable[str]) -> Table:
    """The given text columns parsed with `parse_date`; empty or None stays None. A bad value raises CoercionError
    with kind "date"."""
    idx = {table.index(c): c for c in columns}
    rows = []
    for row in table.rows:
        out = []
        for i, v in enumerate(row):
            if i in idx and isinstance(v, str):
                if not v.strip():
                    v = None
                else:
                    try:
                        v = parse_date(v)
                    except ValueError:
                        raise CoercionError(idx[i], v, "date") from None
            out.append(v)
        rows.append(tuple(out))
    return Table(table.columns, rows)


def period_start(value: date, period: str) -> date:
    """The first day of the period containing `value` (weeks start on Monday)."""
    if period not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}")
    d = value.date() if isinstance(value, datetime) else value
    if period == "day":
        return d
    if period == "week":
        return d - timedelta(days=d.weekday())
    if period == "month":
        return d.replace(day=1)
    if period == "quarter":
        return d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1)
    return d.replace(month=1, day=1)


def period_label(value: date, period: str) -> str:
    """A short label: 2026-03-04 (day), 2026-W10 (ISO week), 2026-03 (month), 2026-Q1 (quarter), 2026 (year)."""
    d = period_start(value, period)
    if period == "day":
        return d.isoformat()
    if period == "week":
        year, week, _ = d.isocalendar()
        return f"{year}-W{week:02d}"
    if period == "month":
        return f"{d.year}-{d.month:02d}"
    if period == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    return str(d.year)


def add_period(table: Table, column: str, period: str, name: str | None = None) -> Table:
    """The table with one more column holding the period label of each date in `column` (None stays None)."""
    i = table.index(column)
    name = name or f"{column}_{period}"
    if name in table.columns:
        raise ValueError(f"column {name!r} already exists")
    rows = [row + ((None if row[i] is None else period_label(row[i], period)),) for row in table.rows]
    return Table(table.columns + [name], rows)


def date_range(start: date, end: date, step_days: int = 1) -> list[date]:
    """Dates from start to end inclusive, every `step_days` days."""
    if step_days < 1:
        raise ValueError("step_days must be at least 1")
    out, d = [], start
    while d <= end:
        out.append(d)
        d += timedelta(days=step_days)
    return out


def format_dates(table: Table, columns: Iterable[str], pattern: str = "%Y-%m-%d") -> Table:
    """Date and datetime values of the given columns as text with `pattern`."""
    idx = {table.index(c) for c in columns}
    rows = [tuple(v.strftime(pattern) if i in idx and isinstance(v, date) else v for i, v in enumerate(row))
            for row in table.rows]
    return Table(table.columns, rows)
